import json
import time
import logging
import anthropic
from dotenv import load_dotenv

load_dotenv()
client = anthropic.Anthropic()

# Retry configuration for handling thinking-only responses
MAX_RETRIES = 3
RETRY_DELAY_BASE = 1  # seconds (exponential backoff: 1s, 2s, 4s)

# Models that DON'T use thinking (standard models)
NON_THINKING_MODELS = {'claude-haiku-4.5-standard'}

MOVE_SYSTEM_PROMPT = """You are a Connect 4 AI player.

RULES:
- Board is 7 columns (1-7) × 6 rows
- You are playing as Red (R) or Yellow (Y) - check the prompt
- Choose ONE column (1-7) to drop your piece
- Pieces fall to the lowest empty position in the chosen column
- Win by getting 4 of your pieces in a row (horizontal, vertical, or diagonal)

STRATEGY:
- Block opponent's winning moves
- Build towards 4 in a row
- Control the center columns when possible
- Look for diagonal opportunities

OUTPUT FORMAT (strict JSON):
{"column": 4}

No extra text. Output only valid JSON with a single column number 1-7.""".strip()


MOVE_SCHEMA = {
    "type": "object",
    "properties": {
        "column": {"type": "integer"}
    },
    "required": ["column"],
    "additionalProperties": False
}


def call_claude_move(user_prompt: str, model: str = "claude-haiku-4-5-20251001") -> tuple[int, str | None]:
    """
    Call Claude to make a Connect 4 move.
    Returns (column, reasoning_summary) where column is 1-7.
    """
    # Check if this is a thinking model based on the model key passed from app.py
    # We need to check the original selection key, not the API model ID
    # The app passes the model ID, so we'll use a different approach
    use_thinking = model != "claude-haiku-4-5-20251001" or "standard" not in str(model).lower()
    
    # Actually, we need a cleaner way to determine this
    # Let's accept an optional parameter or check via a global/passed flag
    # For now, since model IDs are identical, we'll need to pass extra info
    # But to keep it simple, let's add an extra parameter
    
    for attempt in range(MAX_RETRIES):
        if use_thinking:
            # Thinking model call
            response = client.beta.messages.create(
                model=model,
                max_tokens=2048,
                thinking={
                    "type": "enabled",
                    "budget_tokens": 1024,
                },
                betas=["structured-outputs-2025-11-13"],
                system=MOVE_SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": user_prompt}
                ],
                output_format={
                    "type": "json_schema",
                    "schema": MOVE_SCHEMA
                }
            )

            # Grab thinking summary
            thinking_summary = None
            thinking_parts = []
            for block in response.content:
                if getattr(block, "type", None) == "thinking":
                    s = getattr(block, "thinking", None) or getattr(block, "summary", None) or ""
                    if s:
                        thinking_parts.append(s)
            if thinking_parts:
                thinking_summary = "\n".join(thinking_parts).strip()

            # Parse JSON response
            json_text = ""
            for block in response.content:
                if getattr(block, "type", None) == "text":
                    t = getattr(block, "text", "") or ""
                    if t.strip():
                        json_text += t

            if not json_text.strip():
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAY_BASE * (2 ** attempt)
                    logging.warning(f"Claude move returned thinking-only response, retry {attempt+1}/{MAX_RETRIES} in {delay}s")
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"No text response from Claude model after {MAX_RETRIES} attempts. Response blocks: {[b.type for b in response.content]}")

            try:
                data = json.loads(json_text)
            except json.JSONDecodeError:
                raise RuntimeError(f"Expected JSON from model, got:\n{json_text}")

            column = int(data["column"])
            return column, thinking_summary
        else:
            # Standard model call (no thinking)
            response = client.beta.messages.create(
                model=model,
                max_tokens=2048,
                betas=["structured-outputs-2025-11-13"],
                system=MOVE_SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": user_prompt}
                ],
                output_format={
                    "type": "json_schema",
                    "schema": MOVE_SCHEMA
                }
            )

            # Parse JSON response
            json_text = ""
            for block in response.content:
                if getattr(block, "type", None) == "text":
                    t = getattr(block, "text", "") or ""
                    if t.strip():
                        json_text += t

            if not json_text.strip():
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAY_BASE * (2 ** attempt)
                    logging.warning(f"Claude move returned empty response, retry {attempt+1}/{MAX_RETRIES} in {delay}s")
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"No text response from Claude model after {MAX_RETRIES} attempts.")

            try:
                data = json.loads(json_text)
            except json.JSONDecodeError:
                raise RuntimeError(f"Expected JSON from model, got:\n{json_text}")

            column = int(data["column"])
            return column, None
    
    raise RuntimeError("Unexpected error in call_claude_move")


def call_claude_move_with_thinking_flag(user_prompt: str, model: str, use_thinking: bool) -> tuple[int, str | None]:
    """
    Call Claude to make a Connect 4 move with explicit thinking flag.
    Returns (column, reasoning_summary) where column is 1-7.
    """
    for attempt in range(MAX_RETRIES):
        if use_thinking:
            response = client.beta.messages.create(
                model=model,
                max_tokens=2048,
                thinking={
                    "type": "enabled",
                    "budget_tokens": 1024,
                },
                betas=["structured-outputs-2025-11-13"],
                system=MOVE_SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": user_prompt}
                ],
                output_format={
                    "type": "json_schema",
                    "schema": MOVE_SCHEMA
                }
            )

            thinking_summary = None
            thinking_parts = []
            for block in response.content:
                if getattr(block, "type", None) == "thinking":
                    s = getattr(block, "thinking", None) or getattr(block, "summary", None) or ""
                    if s:
                        thinking_parts.append(s)
            if thinking_parts:
                thinking_summary = "\n".join(thinking_parts).strip()

            json_text = ""
            for block in response.content:
                if getattr(block, "type", None) == "text":
                    t = getattr(block, "text", "") or ""
                    if t.strip():
                        json_text += t

            if not json_text.strip():
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAY_BASE * (2 ** attempt)
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"No text response from Claude model after {MAX_RETRIES} attempts.")

            data = json.loads(json_text)
            return int(data["column"]), thinking_summary
        else:
            response = client.beta.messages.create(
                model=model,
                max_tokens=2048,
                betas=["structured-outputs-2025-11-13"],
                system=MOVE_SYSTEM_PROMPT,
                messages=[
                    {"role": "user", "content": user_prompt}
                ],
                output_format={
                    "type": "json_schema",
                    "schema": MOVE_SCHEMA
                }
            )

            json_text = ""
            for block in response.content:
                if getattr(block, "type", None) == "text":
                    t = getattr(block, "text", "") or ""
                    if t.strip():
                        json_text += t

            if not json_text.strip():
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAY_BASE * (2 ** attempt)
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"No text response from Claude model after {MAX_RETRIES} attempts.")

            data = json.loads(json_text)
            return int(data["column"]), None
    
    raise RuntimeError("Unexpected error in call_claude_move_with_thinking_flag")


# Test
if __name__ == "__main__":
    test_prompt = """You are Player B (Claude - Yellow) playing Connect 4. Turn 2.

YOUR PIECE: Y (Yellow)
OPPONENT: R (Red)

CURRENT BOARD:
  1 2 3 4 5 6 7
  ─────────────
1│. . . . . . .│
2│. . . . . . .│
3│. . . . . . .│
4│. . . . . . .│
5│. . . . . . .│
6│. . . R . . .│
  ─────────────

RECENT MOVES:
Turn 1: Red → Column 4

VALID COLUMNS TO PLAY: 1, 2, 3, 4, 5, 6, 7

Choose ONE column number (1-7) to drop your piece."""

    column, summary = call_claude_move(test_prompt)
    print("Column:", column)
    print("\n🧠 Reasoning Summary:\n", summary or "No reasoning summary found.")