import { Codex } from '@openai/codex-sdk';
import { pathToFileURL } from 'node:url';

export const moveSchema = {
    type: 'object',
    properties: {
        column: { type: 'integer', enum: [1, 2, 3, 4, 5, 6, 7] },
        explanation: { type: 'string' },
    },
    required: ['column', 'explanation'],
    additionalProperties: false,
};

export async function runCodex(input, Client = Codex) {
    if (typeof input.prompt !== 'string' || !input.prompt.trim()) throw new Error('A board prompt is required.');
    const env = { ...process.env };
    for (const key of ['OPENAI_API_KEY', 'CODEX_API_KEY', 'OPENAI_BASE_URL']) delete env[key];
    const client = new Client({
        env,
        ...(env.CODEX_CLI_PATH ? { codexPathOverride: env.CODEX_CLI_PATH } : {}),
        config: {
            forced_login_method: 'chatgpt',
            model_provider: 'openai',
            features: { shell_tool: false },
        },
        configOverrides: ['mcp_servers={}', 'hooks={}'],
    });
    const thread = client.startThread({
        workingDirectory: process.cwd(),
        skipGitRepoCheck: true,
        sandboxMode: 'read-only',
        approvalPolicy: 'never',
        networkAccessEnabled: false,
        webSearchMode: 'disabled',
        ...(input.model ? { model: input.model } : {}),
        ...(input.effort && input.effort !== 'default' ? { modelReasoningEffort: input.effort } : {}),
    });
    const result = await thread.run(input.prompt, { outputSchema: moveSchema });
    const move = JSON.parse(result.finalResponse);
    if (!moveSchema.properties.column.enum.includes(move.column) || typeof move.explanation !== 'string') {
        throw new Error('Codex returned an invalid column.');
    }
    return { column: move.column, explanation: move.explanation.slice(0, 600) };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
    try {
        let input = '';
        for await (const chunk of process.stdin) input += chunk;
        process.stdout.write(JSON.stringify(await runCodex(JSON.parse(input))));
    } catch {
        process.stderr.write('Codex SDK turn failed. Check CLI sign-in, installation, and model access.\n');
        process.exitCode = 1;
    }
}
