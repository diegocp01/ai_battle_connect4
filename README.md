# Overview

This is a Connect 4 game where GPT plays against Claude on a 3D board: GPT drops the red checkers and Claude the yellow ones.

![Connect 4 Demo](static/img/image.png?v=2)

# Connections

Pick one under *Connection* on the setup screen:

- **Local CLIs** (default): uses the Codex and Claude Code CLIs you are already signed in to. No API keys needed. The model lists and reasoning-effort levels are read from the CLIs.
- **API keys**: calls the OpenAI and Anthropic APIs with the keys in `.env`.
- **Test**: two simulated players, no LLM calls. Useful for trying the interface.

# Quickstart

Install the Python dependencies:
```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

For Local CLIs, install Node.js 20+ and the Codex SDK, and sign in to both CLIs (`codex` and `claude`):
```bash
npm ci
```

For API keys, create a `.env` file (see `.env.example`):
```bash
OPENAI_API_KEY=your_openai_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key
```

Run the app:
```bash
python app.py
```

Then open http://127.0.0.1:5001. Finished real rounds are saved to `data/round-history.json` and shown under *Universal stats* and *Match history*.
