from openai import OpenAI
from pydantic import BaseModel, Field
from dotenv import load_dotenv
load_dotenv()
client = OpenAI()


# Structured response for Connect 4 move
class MoveAnswer(BaseModel):
    column: int = Field(ge=1, le=7)


# Models that use minimal reasoning (fast, no displayed reasoning)
MINIMAL_REASONING_MODELS = {'gpt-5-mini'}

# Models that use low reasoning effort (reasoning displayed, but lower effort)
LOW_REASONING_MODELS = {'gpt-5.1-low'}


def call_chatgpt_move(user_prompt: str, model: str = "gpt-5.1", model_key: str = None) -> tuple[int, str | None]:
    """
    Call ChatGPT to make a Connect 4 move.
    Returns (column, reasoning_summary) where column is 1-7.
    """
    # Use model_key if provided, otherwise infer from model name
    key = model_key or model
    use_full_reasoning = key not in MINIMAL_REASONING_MODELS
    use_low_reasoning = key in LOW_REASONING_MODELS
    
    system_prompt = """You are a Connect 4 AI player.

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

OUTPUT: A single column number 1-7."""

    if use_full_reasoning:
        # Full reasoning model call (medium or low effort, display reasoning)
        reasoning_effort = "low" if use_low_reasoning else "medium"
        response = client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            text_format=MoveAnswer,
            reasoning={
                "effort": reasoning_effort,
                "summary": "auto"
            },
        )
        
        column = response.output_parsed.column

        # Get reasoning summary
        reasoning_summary = None
        for item in response.output:
            if getattr(item, "type", None) == "reasoning":
                parts = []
                for s in (item.summary or []):
                    if getattr(s, "text", None):
                        parts.append(s.text)
                if parts:
                    reasoning_summary = "\n".join(parts)
                break

        return column, reasoning_summary
    else:
        # Minimal reasoning for speed (don't display reasoning)
        response = client.responses.parse(
            model=model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            text_format=MoveAnswer,
            reasoning={
                "effort": "minimal"
            },
        )
        
        column = response.output_parsed.column
        return column, None  # Don't return reasoning for mini model


# Test
if __name__ == "__main__":
    test_prompt = """You are Player A (GPT - Red) playing Connect 4. Turn 1.

YOUR PIECE: R (Red)
OPPONENT: Y (Yellow)

CURRENT BOARD:
  1 2 3 4 5 6 7
  ─────────────
1│. . . . . . .│
2│. . . . . . .│
3│. . . . . . .│
4│. . . . . . .│
5│. . . . . . .│
6│. . . . . . .│
  ─────────────

VALID COLUMNS TO PLAY: 1, 2, 3, 4, 5, 6, 7

Choose ONE column number (1-7) to drop your piece."""

    column, summary = call_chatgpt_move(test_prompt)
    print("Column:", column)
    print("\n🧠 Reasoning Summary:\n", summary or "No reasoning summary found.")
