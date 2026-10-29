from flask import Flask, render_template, jsonify, request
from urllib.parse import urlparse
import random
from datetime import datetime
from pathlib import Path
import threading
import json
import time
import uuid
import os

from providers import MODES, ProviderError, call_local, call_test, model_catalog, select_models

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Server-side game state storage
GAME_STATE = {}

# Every finished round is saved here so the setup page can show all-time stats.
MATCH_HISTORY_PATH = Path(os.getenv('ARENA_HISTORY_PATH') or Path(__file__).resolve().parent / 'data' / 'round-history.json')
HISTORY_LOCK = threading.Lock()

# Connect 4 board configuration
COLS = 7
ROWS = 6

# Model name mappings
GPT_MODELS = {
    'gpt-5-mini': 'gpt-5-mini',
    'gpt-5.1-low': 'gpt-5.1',
    'gpt-5.1': 'gpt-5.1',
    'gpt-5.2': 'gpt-5.2'
}

CLAUDE_MODELS = {
    'claude-haiku-4.5-standard': 'claude-haiku-4-5-20251001',
    'claude-haiku-4.5': 'claude-haiku-4-5-20251001',
    'claude-sonnet-4.5-standard': 'claude-sonnet-4-5-20250929',
    'claude-sonnet-4.5': 'claude-sonnet-4-5-20250929'
}

GPT_DISPLAY_NAMES = {
    'gpt-5-mini': 'GPT 5 Mini',
    'gpt-5.1-low': 'GPT 5.1 Low',
    'gpt-5.1': 'GPT 5.1 Medium',
    'gpt-5.2': 'GPT 5.2 Medium'
}

CLAUDE_DISPLAY_NAMES = {
    'claude-haiku-4.5-standard': 'Claude Haiku 4.5',
    'claude-haiku-4.5': 'Claude Haiku 4.5 Thinking',
    'claude-sonnet-4.5-standard': 'Claude Sonnet 4.5',
    'claude-sonnet-4.5': 'Claude Sonnet 4.5 Thinking'
}


def create_empty_board():
    """Create an empty Connect 4 board (7 cols x 6 rows)."""
    return [['.' for _ in range(COLS)] for _ in range(ROWS)]


def board_to_string(board):
    """Convert board to visual string for AI prompts."""
    lines = []
    lines.append("  1 2 3 4 5 6 7")
    lines.append("  ─────────────")
    for row_idx, row in enumerate(board):
        row_str = f"{row_idx + 1}│" + " ".join(row) + "│"
        lines.append(row_str)
    lines.append("  ─────────────")
    return "\n".join(lines)


def get_valid_columns(board):
    """Return list of columns that aren't full (1-indexed)."""
    valid = []
    for col in range(COLS):
        if board[0][col] == '.':
            valid.append(col + 1)  # 1-indexed for user/AI
    return valid


def drop_piece(board, col, piece):
    """
    Drop a piece into the specified column.
    Returns (success, row_placed) where row is 0-indexed from top.
    col is 1-indexed.
    """
    col_idx = col - 1  # Convert to 0-indexed
    
    if col_idx < 0 or col_idx >= COLS:
        return False, -1
    
    # Find the lowest empty row in this column
    for row in range(ROWS - 1, -1, -1):
        if board[row][col_idx] == '.':
            board[row][col_idx] = piece
            return True, row
    
    return False, -1  # Column is full


def check_winner(board, piece):
    """Check if the specified piece has won (4 in a row)."""
    # Check horizontal
    for row in range(ROWS):
        for col in range(COLS - 3):
            if (board[row][col] == piece and
                board[row][col + 1] == piece and
                board[row][col + 2] == piece and
                board[row][col + 3] == piece):
                return True
    
    # Check vertical
    for row in range(ROWS - 3):
        for col in range(COLS):
            if (board[row][col] == piece and
                board[row + 1][col] == piece and
                board[row + 2][col] == piece and
                board[row + 3][col] == piece):
                return True
    
    # Check diagonal (down-right)
    for row in range(ROWS - 3):
        for col in range(COLS - 3):
            if (board[row][col] == piece and
                board[row + 1][col + 1] == piece and
                board[row + 2][col + 2] == piece and
                board[row + 3][col + 3] == piece):
                return True
    
    # Check diagonal (up-right)
    for row in range(3, ROWS):
        for col in range(COLS - 3):
            if (board[row][col] == piece and
                board[row - 1][col + 1] == piece and
                board[row - 2][col + 2] == piece and
                board[row - 3][col + 3] == piece):
                return True
    
    return False


def is_board_full(board):
    """Check if the board is completely full (draw)."""
    return all(board[0][col] != '.' for col in range(COLS))


def read_round_history():
    """Return every saved round, oldest first."""
    if not MATCH_HISTORY_PATH.exists():
        return []
    try:
        rounds = json.loads(MATCH_HISTORY_PATH.read_text()).get('rounds', [])
    except (OSError, ValueError, AttributeError):
        raise RuntimeError('Match history is damaged.')
    return rounds if isinstance(rounds, list) else []


def save_round(state, winner):
    """Append a finished round to the history file. Test rounds are not saved."""
    if state['mode'] == 'test':
        return
    entry = {
        'match_id': state['match_id'],
        'round': state['current_game'],
        'rounds_total': state['total_games'],
        'winner': winner,
        'turns': state['turn_count'],
        'mode': state['mode'],
        'gpt_name': state['gpt_display_name'],
        'claude_name': state['claude_display_name'],
        'gpt_effort': state['gpt_effort'],
        'claude_effort': state['claude_effort'],
        'finished_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
    }
    with HISTORY_LOCK:
        try:
            rounds = read_round_history()
        except RuntimeError:
            app.logger.warning('Round history at %s is damaged; this round was not saved.', MATCH_HISTORY_PATH)
            return
        MATCH_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = MATCH_HISTORY_PATH.with_suffix('.tmp')
        temporary.write_text(json.dumps({'rounds': rounds + [entry]}, indent=2) + '\n')
        os.replace(temporary, MATCH_HISTORY_PATH)


def init_game_state(mode='local', players=None):
    """Initialize a fresh game state. `players` holds each side's model, effort and display name."""
    players = players or {}
    gpt_model = players.get('gpt_model', 'gpt-5.1')
    claude_model = players.get('claude_model', 'claude-haiku-4.5')
    # Randomly decide who goes first
    gpt_first = random.choice([True, False])
    
    return {
        'board': create_empty_board(),
        'current_player': 'gpt' if gpt_first else 'claude',
        'first_player': 'gpt' if gpt_first else 'claude',
        'game_over': False,
        'winner': None,  # 'gpt', 'claude', or 'draw'
        'turn_count': 0,
        'move_history': [],  # List of (player, column) tuples
        'gpt_reasoning': '',
        'claude_reasoning': '',
        'gpt_stats': {'wins': 0, 'losses': 0, 'draws': 0},
        'claude_stats': {'wins': 0, 'losses': 0, 'draws': 0},
        'current_game': 1,
        'total_games': 1,
        'game_history': [],
        'gpt_total_time': 0.0,
        'claude_total_time': 0.0,
        'gpt_last_time': 0.0,
        'claude_last_time': 0.0,
        'last_move': None,  # (col, row) of last placed piece
        # Model settings
        'players': players,
        'gpt_model': gpt_model,
        'claude_model': claude_model,
        'gpt_effort': players.get('gpt_effort', 'default'),
        'claude_effort': players.get('claude_effort', 'default'),
        'gpt_model_id': GPT_MODELS.get(gpt_model, gpt_model),
        'claude_model_id': CLAUDE_MODELS.get(claude_model, claude_model),
        'gpt_display_name': players.get('gpt_name') or GPT_DISPLAY_NAMES.get(gpt_model, 'GPT'),
        'claude_display_name': players.get('claude_name') or CLAUDE_DISPLAY_NAMES.get(claude_model, 'Claude'),
        'mode': mode,
        'match_id': uuid.uuid4().hex,
    }


def generate_move_prompt(player_name, piece, board, valid_cols, move_history, turn_count):
    """Generate prompt for AI to make a Connect 4 move."""
    board_str = board_to_string(board)
    
    # Format move history (limit to last 10)
    history_text = ""
    if move_history:
        recent = move_history[-10:]
        first_turn = len(move_history) - len(recent) + 1
        history_lines = [f"Turn {i}: {'Red' if p == 'gpt' else 'Yellow'} → Column {c}"
                        for i, (p, c) in enumerate(recent, start=first_turn)]
        if len(move_history) > 10:
            history_text = f"(showing last 10 of {len(move_history)} moves)\n"
        history_text += "\n".join(history_lines)
    else:
        history_text = "No moves yet - this is the first move!"
    
    valid_cols_str = ", ".join(str(c) for c in valid_cols)
    
    return f"""You are {player_name} playing Connect 4. Turn {turn_count}.

YOUR PIECE: {piece} ({'Red' if piece == 'R' else 'Yellow'})
OPPONENT: {'Y (Yellow)' if piece == 'R' else 'R (Red)'}

CURRENT BOARD:
{board_str}

Legend: R = Red, Y = Yellow, . = Empty

RECENT MOVES:
{history_text}

VALID COLUMNS TO PLAY: {valid_cols_str}

RULES:
- Pieces drop to the lowest empty row in the chosen column
- Win by getting 4 of your pieces in a row (horizontal, vertical, or diagonal)
- Block your opponent from getting 4 in a row

Choose ONE column number (1-7) to drop your piece."""


API_MODELS = {'gpt': (GPT_DISPLAY_NAMES, 'gpt-5.1'), 'claude': (CLAUDE_DISPLAY_NAMES, 'claude-haiku-4.5')}


@app.before_request
def local_requests_only():
    # Local mode runs CLIs on this machine, so only this app's own page may post to it.
    if request.method == 'POST' and request.headers.get('Origin'):
        if urlparse(request.headers['Origin']).netloc != request.host:
            return jsonify({'error': 'Use the app from its own localhost page.'}), 403


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/config')
def configuration():
    """Models each connection can use. Local models are read from the signed-in CLIs."""
    return jsonify({'default_mode': 'local', 'models': model_catalog(API_MODELS)})


@app.route('/api/match-history')
def match_history():
    """Every saved round, plus rounds won by each side."""
    try:
        rounds = read_round_history()
    except RuntimeError:
        return jsonify({'error': 'Match history is unavailable.'}), 503
    totals = {'gpt': 0, 'claude': 0, 'draw': 0}
    for entry in rounds:
        if entry.get('winner') in totals:
            totals[entry['winner']] += 1
    response = jsonify({'rounds': rounds, 'totals': totals})
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.route('/api/reset', methods=['POST'])
def reset_match():
    """Forget the current match so the setup page starts fresh."""
    global GAME_STATE
    GAME_STATE = {}
    return jsonify({'success': True})


@app.route('/api/start-games', methods=['POST'])
def start_games():
    """Start a new game."""
    global GAME_STATE
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Send a JSON object with mode and models.'}), 400
    mode = data.get('mode', 'local')
    if mode not in MODES:
        return jsonify({'error': 'Choose Local CLIs, API keys, or Test.'}), 400
    try:
        players = select_models(mode, data, API_MODELS)
    except ProviderError as error:
        return jsonify({'error': str(error)}), 400
    
    state = init_game_state(mode=mode, players=players)
    GAME_STATE = state
    
    return jsonify({
        'success': True,
        'game_state': get_client_state(state)
    })


@app.route('/api/game-state', methods=['GET'])
def get_game_state_route():
    """Get current game state."""
    global GAME_STATE
    started = bool(GAME_STATE)
    if not GAME_STATE:
        GAME_STATE = init_game_state()
    return jsonify({**get_client_state(GAME_STATE), 'started': started})


@app.route('/api/next-move', methods=['POST'])
def next_move():
    """Execute the next move."""
    global GAME_STATE
    state = GAME_STATE
    if not state:
        return jsonify({'error': 'No game in progress'}), 400
    
    if state['game_over']:
        return jsonify({'error': 'Game is over'}), 400
    
    current_player = state['current_player']
    turn = state['turn_count'] + 1
    
    # Determine piece for current player
    piece = 'R' if current_player == 'gpt' else 'Y'
    
    # Get valid columns
    valid_cols = get_valid_columns(state['board'])
    if not valid_cols:
        state['game_over'] = True
        state['winner'] = 'draw'
        return jsonify({
            'success': True,
            'game_state': get_client_state(state)
        })
    
    player_name = "Player A (GPT - Red)" if current_player == 'gpt' else "Player B (Claude - Yellow)"
    prompt = generate_move_prompt(player_name, piece, state['board'], valid_cols, state['move_history'], turn)
    
    # Ask the player for a column
    start_time = time.time()
    try:
        if state['mode'] == 'test':
            column, reasoning = call_test(state['board'], piece, valid_cols, drop_piece, check_winner)
        elif state['mode'] == 'local':
            column, reasoning = call_local(current_player, prompt, valid_cols,
                                           state[current_player + '_model'], state[current_player + '_effort'])
        elif current_player == 'gpt':
            from openai_model_v1 import call_chatgpt_move
            column, reasoning = call_chatgpt_move(prompt, state['gpt_model_id'], model_key=state['gpt_model'])
        else:
            from anthropic_model_v1 import call_claude_move_with_thinking_flag
            use_thinking = state['claude_model'] not in ('claude-haiku-4.5-standard', 'claude-sonnet-4.5-standard')
            column, reasoning = call_claude_move_with_thinking_flag(prompt, state['claude_model_id'], use_thinking)
    except ProviderError as error:
        return jsonify({'error': str(error)}), 502
    except Exception as e:
        label = 'GPT' if current_player == 'gpt' else 'Claude'
        return jsonify({'error': f'{label} API error: {str(e)}'}), 500
    elapsed = time.time() - start_time
    
    state['turn_count'] = turn
    state[current_player + '_reasoning'] = reasoning or 'Move selected.'
    state[current_player + '_last_time'] = round(elapsed, 2)
    state[current_player + '_total_time'] = round(state[current_player + '_total_time'] + elapsed, 2)
    
    # Validate and execute move
    if column not in valid_cols:
        # If AI gave invalid column, pick first valid one
        column = valid_cols[0]
    
    success, row = drop_piece(state['board'], column, piece)
    if not success:
        return jsonify({'error': f'Failed to drop piece in column {column}'}), 400
    
    state['move_history'].append((current_player, column))
    state['last_move'] = {'col': column, 'row': row, 'player': current_player}
    
    # Check for winner
    if check_winner(state['board'], piece):
        state['game_over'] = True
        state['winner'] = current_player
        
        # Update stats
        if current_player == 'gpt':
            state['gpt_stats']['wins'] += 1
            state['claude_stats']['losses'] += 1
            winner_name = state['gpt_display_name']
        else:
            state['claude_stats']['wins'] += 1
            state['gpt_stats']['losses'] += 1
            winner_name = state['claude_display_name']
        
        state['game_history'].append({
            'game': state['current_game'],
            'time': datetime.now().strftime('%H:%M:%S'),
            'winner': winner_name,
            'winner_model': current_player,
            'turns': state['turn_count'],
            'gpt_time': state['gpt_total_time'],
            'claude_time': state['claude_total_time']
        })
        save_round(state, current_player)
    elif is_board_full(state['board']):
        state['game_over'] = True
        state['winner'] = 'draw'
        state['gpt_stats']['draws'] += 1
        state['claude_stats']['draws'] += 1
        
        state['game_history'].append({
            'game': state['current_game'],
            'time': datetime.now().strftime('%H:%M:%S'),
            'winner': 'Draw',
            'winner_model': None,
            'turns': state['turn_count'],
            'gpt_time': state['gpt_total_time'],
            'claude_time': state['claude_total_time']
        })
        save_round(state, 'draw')
    else:
        # Switch turns
        state['current_player'] = 'claude' if current_player == 'gpt' else 'gpt'
    
    GAME_STATE = state
    
    return jsonify({
        'success': True,
        'player': current_player,
        'column': column,
        'row': row,
        'game_state': get_client_state(state)
    })


def get_client_state(state):
    """Get state formatted for the client."""
    return {
        'board': state['board'],
        'current_player': state['current_player'],
        'first_player': state['first_player'],
        'turn_count': state['turn_count'],
        'game_over': state['game_over'],
        'winner': state['winner'],
        'last_move': state['last_move'],
        'move_history': state['move_history'][-10:],  # Last 10 moves
        
        'gpt_reasoning': state['gpt_reasoning'][:500] if state['gpt_reasoning'] else '',
        'claude_reasoning': state['claude_reasoning'][:500] if state['claude_reasoning'] else '',
        
        'gpt_stats': state['gpt_stats'],
        'claude_stats': state['claude_stats'],
        'current_game': state['current_game'],
        'total_games': state['total_games'],
        'game_history': state['game_history'],
        'all_games_complete': state['game_over'] and state['current_game'] >= state['total_games'],
        
        'gpt_total_time': state.get('gpt_total_time', 0.0),
        'claude_total_time': state.get('claude_total_time', 0.0),
        'gpt_last_time': state.get('gpt_last_time', 0.0),
        'claude_last_time': state.get('claude_last_time', 0.0),
        
        'gpt_display_name': state.get('gpt_display_name', 'GPT 5.1 Medium'),
        'claude_display_name': state.get('claude_display_name', 'Claude Haiku 4.5 Thinking'),
        'gpt_model': state['gpt_model'],
        'claude_model': state['claude_model'],
        'gpt_effort': state['gpt_effort'],
        'claude_effort': state['claude_effort'],
        'mode': state['mode'],
    }


if __name__ == '__main__':
    app.run(debug=True, port=5001)
