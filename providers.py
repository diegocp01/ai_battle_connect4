"""Player adapters. Test mode never imports SDKs or starts subprocesses."""
import json
import os
import random
import re
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
from functools import lru_cache
from claude_catalog import parse_catalog

ROOT = Path(__file__).resolve().parent
MODES = ('local', 'api', 'test')
COLUMNS = list(range(1, 8))
MOVE_SCHEMA = {
    'type': 'object',
    'properties': {
        'column': {'type': 'integer', 'enum': COLUMNS},
        'explanation': {'type': 'string'},
    },
    'required': ['column', 'explanation'],
    'additionalProperties': False,
}


class ProviderError(RuntimeError):
    pass


VALID_EFFORTS = ('none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra', 'persistent')


@lru_cache(maxsize=8)
def _claude_catalog(binary, modified, period):
    packet = {'type': 'control_request', 'request_id': 'arena-model-discovery', 'request': {'subtype': 'initialize'}}
    command = [binary, '-p', '--input-format', 'stream-json', '--output-format', 'stream-json',
               '--verbose', '--tools', '', '--setting-sources', '', '--settings', '{"disableAllHooks":true}',
               '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}', '--no-session-persistence',
               '--permission-mode', 'dontAsk', '--no-chrome']
    messages = run_process(command, json.dumps(packet) + '\n', 'Claude model discovery', timeout=15, json_lines=True)
    return parse_catalog(messages)


def claude_model_catalog():
    binary = shutil.which(os.getenv('CLAUDE_BIN', 'claude'))
    if not binary:
        return {'models': [], 'default': '', 'aliases': {}, 'message': 'Install and sign in to Claude Code, then reload.'}
    try:
        return _claude_catalog(binary, Path(binary).stat().st_mtime_ns, int(time.monotonic() // 300))
    except (OSError, ProviderError):
        return {'models': [], 'default': '', 'aliases': {}, 'message': 'Claude model discovery failed. Check CLI sign-in and reload.'}


def _option(model_id, name, efforts=(), default_effort='default'):
    levels = ['default', *dict.fromkeys(efforts)]
    return {'id': model_id, 'name': name, 'efforts': levels,
            'default_effort': default_effort if default_effort in levels else 'default',
            'effort_supported': len(levels) > 1}


def newest_family(models, family):
    candidates = []
    for model in models:
        model_id = model['id']
        pattern = r'^gpt-(\d+(?:[.-]\d+)*)-' + re.escape(family) + r'$' if family == 'luna' else r'^claude-' + re.escape(family) + r'-(\d+(?:[.-]\d+)*)(?:\[1m\])?$'
        match = re.fullmatch(pattern, model_id)
        if match:
            candidates.append((tuple(int(part) for part in re.split(r'[.-]', match.group(1))), not model_id.endswith('[1m]'), model_id))
    return max(candidates)[2] if candidates else None


@lru_cache(maxsize=8)
def _live_codex_models(node, runtime, period):
    return run_process([node, str(ROOT / 'bridges/codex-models.mjs')], '', 'Codex model discovery', timeout=15)


def codex_model_catalog(cache=None, discover=True):
    """Read all picker-visible models from the same CLI runtime used by the SDK."""
    reported, live = [], False
    node = shutil.which('node')
    if discover and cache is None and node and (ROOT / 'node_modules/@openai/codex').is_dir():
        try:
            reported = _live_codex_models(node, os.getenv('CODEX_CLI_PATH', 'sdk-bundled'), int(time.monotonic() // 300))
            if not isinstance(reported, list):
                raise ProviderError('Invalid Codex model list.')
            live = True
        except ProviderError:
            pass
    if not live:
        cache = Path(cache) if cache else Path(os.getenv('CODEX_HOME') or Path.home() / '.codex') / 'models_cache.json'
        try:
            if cache.stat().st_size <= 1_000_000:
                reported = json.loads(cache.read_text()).get('models', [])
        except (OSError, ValueError, AttributeError):
            pass
    models = []
    for item in reported if isinstance(reported, list) else []:
        if not isinstance(item, dict) or item.get('visibility') == 'hide' or item.get('hidden'):
            continue
        model_id = item.get('model') or item.get('slug') or item.get('id')
        if not isinstance(model_id, str) or not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,100}', model_id) or model_id == 'default':
            continue
        if any(model['id'] == model_id for model in models):
            continue
        capabilities = item.get('supportedReasoningEfforts', item.get('supported_reasoning_levels', []))
        efforts = [level.get('reasoningEffort', level.get('effort')) for level in capabilities
                   if isinstance(level, dict) and level.get('reasoningEffort', level.get('effort')) in VALID_EFFORTS]
        models.append(_option(model_id, str(item.get('displayName') or item.get('display_name') or model_id)[:100], efforts,
                              item.get('defaultReasoningEffort', item.get('default_reasoning_level'))))
    default = newest_family(models, 'luna') or (models[0]['id'] if models else '')
    message = '' if newest_family(models, 'luna') else ('Luna is not in the CLI model list. Choose an available model.' if models else 'No Codex models reported. Sign in to Codex and reload.')
    return {'models': models, 'default': default, 'aliases': {'default': default} if default else {}, 'message': message}


def model_catalog(api_models, discover=True):
    """Local models come from CLI metadata only. Discovery initializes Claude without sending a prompt."""
    codex = codex_model_catalog(discover=discover)
    claude = claude_model_catalog() if discover else {'models': [], 'default': '', 'aliases': {}, 'message': ''}
    haiku = newest_family(claude['models'], 'haiku')
    if haiku:
        claude = {**claude, 'default': haiku}
    # API models carry their reasoning level in the model choice itself.
    api = {key: {'models': [_option(model_id, name) for model_id, name in names.items()], 'default': default}
           for key, (names, default) in api_models.items()}
    return {
        'local': {'gpt': codex, 'claude': claude},
        'api': api,
        'test': {
            'gpt': {'models': [_option('default', 'Test player A')], 'default': 'default'},
            'claude': {'models': [_option('default', 'Test player B')], 'default': 'default'},
        },
    }


def select_models(mode, settings, api_models):
    catalog = model_catalog(api_models, discover=mode == 'local')[mode]
    selected = {}
    for key in ('gpt', 'claude'):
        requested = settings.get(key + '_model', catalog[key]['default'])
        if mode == 'test':
            requested = 'default'
        requested = catalog[key].get('aliases', {}).get(requested, requested) if isinstance(requested, str) else requested
        info = next((item for item in catalog[key]['models'] if item['id'] == requested), None)
        if not info:
            raise ProviderError(catalog[key].get('message') or 'Choose a model from the available options.')
        effort = settings.get(key + '_effort', info['default_effort'])
        if mode == 'test':
            effort = 'default'
        if effort not in info['efforts']:
            raise ProviderError('Choose an effort level supported by the selected model.')
        selected[key + '_model'] = requested
        selected[key + '_effort'] = effort
        selected[key + '_name'] = info['name']
    return selected


def local_environment():
    """Keep CLI sign-in state, but never pass API credentials into local mode."""
    excluded = {
        'OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENAI_BASE_URL',
        'ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_BASE_URL',
        'CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY',
    }
    return {key: value for key, value in os.environ.items() if key not in excluded}


def run_process(command, payload, label, *, timeout=None, json_lines=False, environment=None):
    timeout = timeout or max(1, int(os.getenv('MODEL_TIMEOUT_SECONDS', '180')))
    # Empty working directory avoids loading this repository as an agent task.
    with tempfile.TemporaryDirectory(prefix='ai-arena-') as working_dir:
        try:
            process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, cwd=working_dir,
                env=environment if environment is not None else local_environment(), start_new_session=(os.name == 'posix'),
            )
        except OSError as error:
            raise ProviderError(f'{label} could not start. Check its installation and PATH.') from error
        try:
            output, _ = process.communicate(payload, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            if os.name == 'posix':
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            process.communicate()
            raise ProviderError(f'{label} timed out after {timeout}s. Retry or increase MODEL_TIMEOUT_SECONDS.') from error
        if process.returncode:
            # CLI diagnostics can contain credentials or private configuration.
            raise ProviderError(f'{label} failed. Open its CLI to check sign-in and model access, then retry.')
        try:
            if json_lines:
                return [json.loads(line) for line in output.splitlines() if line.strip()]
            return json.loads(output)
        except (TypeError, json.JSONDecodeError) as error:
            raise ProviderError(f'{label} did not return a valid JSON response. Update the CLI and retry.') from error


def parse_move(data, valid_cols):
    if not isinstance(data, dict) or data.get('column') not in COLUMNS:
        raise ProviderError('The player returned an invalid column.')
    explanation = data.get('explanation', '')
    if not isinstance(explanation, str):
        raise ProviderError('The player returned an invalid explanation.')
    if data['column'] not in valid_cols:
        raise ProviderError(f"The player chose column {data['column']}, which is full.")
    return data['column'], explanation[:600]


def call_local(model, prompt, valid_cols, selected_model=None, effort=None):
    selected = None if selected_model == 'default' else selected_model
    instructions = (
        'Play Connect 4 using only the supplied board. Do not use tools, files, '
        'or external information. Return JSON with a legal column and a brief '
        'one-sentence explanation of the move, not internal reasoning.\n\n' + prompt
    )
    if model == 'gpt':
        node = shutil.which('node')
        if not node or not (ROOT / 'node_modules/@openai/codex-sdk').is_dir():
            raise ProviderError('Codex SDK is not ready. Install Node.js and run npm ci in the app folder.')
        data = run_process(
            [node, str(ROOT / 'bridges/codex.mjs')],
            json.dumps({'prompt': instructions, 'model': selected, 'effort': effort if effort != 'default' else None}), 'Codex SDK',
        )
    else:
        claude = shutil.which(os.getenv('CLAUDE_BIN', 'claude'))
        if not claude:
            raise ProviderError('Claude CLI was not found. Install claude, sign in, and restart the app.')
        command = [
            claude, '-p', '--output-format', 'json', '--json-schema', json.dumps(MOVE_SCHEMA),
            '--tools', '', '--permission-mode', 'dontAsk', '--no-session-persistence',
            '--setting-sources', '', '--settings', '{"disableAllHooks":true}',
            '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}', '--no-chrome',
        ]
        if selected:
            command += ['--model', selected]
        if effort and effort != 'default':
            command += ['--effort', effort]
        environment = local_environment()
        if effort and effort != 'default':
            environment['CLAUDE_CODE_EFFORT_LEVEL'] = effort
        result = run_process(command, instructions, 'Claude CLI', environment=environment)
        if not isinstance(result, dict) or result.get('is_error'):
            raise ProviderError('Claude CLI could not complete the turn. Run claude to check sign-in and model access.')
        data = result.get('structured_output')
        if data is None:
            try:
                data = json.loads(result.get('result', ''))
            except (TypeError, json.JSONDecodeError) as error:
                raise ProviderError('Claude CLI did not return a structured move. Update the CLI and retry.') from error
    return parse_move(data, valid_cols)


def call_test(board, piece, valid_cols, drop_piece, check_winner):
    """Simulated player: win if it can, block if it must, otherwise lean toward the centre."""
    opponent = 'Y' if piece == 'R' else 'R'
    for target, why in ((piece, 'wins'), (opponent, 'blocks a win')):
        for col in valid_cols:
            trial = [row[:] for row in board]
            drop_piece(trial, col, target)
            if check_winner(trial, target):
                return col, f'Test mode: column {col} {why}. No LLM was called.'
    col = min(valid_cols, key=lambda c: abs(c - 4) + random.random() * 3)
    return col, f'Test mode: chose column {col}, leaning toward the centre. No LLM was called.'
