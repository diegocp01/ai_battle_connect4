from flask import Flask, render_template, jsonify, request
import random
from datetime import datetime
import time
import os

# Import the model functions
from openai_model_v1 import call_chatgpt_move
from anthropic_model_v1 import call_claude_move_with_thinking_flag

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Server-side game state storage
GAME_STATE = {}

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


def init_game_state(gpt_model='gpt-5.1', claude_model='claude-haiku-4.5'):
    """Initialize a fresh game state."""
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
        'gpt_model': gpt_model,
        'claude_model': claude_model,
        'gpt_model_id': GPT_MODELS.get(gpt_model, 'gpt-5.1'),
        'claude_model_id': CLAUDE_MODELS.get(claude_model, 'claude-haiku-4-5-20251001'),
        'gpt_display_name': GPT_DISPLAY_NAMES.get(gpt_model, 'GPT 5.1 Medium'),
        'claude_display_name': CLAUDE_DISPLAY_NAMES.get(claude_model, 'Claude Haiku 4.5 Thinking'),
    }


def generate_move_prompt(player_name, piece, board, valid_cols, move_history, turn_count):
    """Generate prompt for AI to make a Connect 4 move."""
    board_str = board_to_string(board)
    
    # Format move history (limit to last 10)
    history_text = ""
    if move_history:
        recent = move_history[-10:]
        history_lines = [f"Turn {i+1}: {'Red' if p == 'gpt' else 'Yellow'} → Column {c}" 
                        for i, (p, c) in enumerate(recent)]
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


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/start-games', methods=['POST'])
def start_games():
    """Start a new series of games."""
    global GAME_STATE
    data = request.get_json()
    num_games = int(data.get('num_games', 1))
    num_games = max(1, min(10, num_games))
    
    gpt_model = data.get('gpt_model', 'gpt-5.1')
    claude_model = data.get('claude_model', 'claude-haiku-4.5')
    
    state = init_game_state(gpt_model=gpt_model, claude_model=claude_model)
    state['total_games'] = num_games
    GAME_STATE = state
    
    return jsonify({
        'success': True,
        'game_state': get_client_state(state)
    })


@app.route('/api/game-state', methods=['GET'])
def get_game_state_route():
    """Get current game state."""
    global GAME_STATE
    if not GAME_STATE:
        GAME_STATE = init_game_state()
    return jsonify(get_client_state(GAME_STATE))


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
    state['turn_count'] += 1
    
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
    
    # Generate prompt and call AI
    if current_player == 'gpt':
        player_name = "Player A (GPT - Red)"
        prompt = generate_move_prompt(player_name, piece, state['board'], 
                                       valid_cols, state['move_history'], state['turn_count'])
        
        start_time = time.time()
        try:
            column, reasoning = call_chatgpt_move(prompt, state['gpt_model_id'], model_key=state['gpt_model'])
        except Exception as e:
            return jsonify({'error': f'GPT API error: {str(e)}'}), 500
        elapsed = time.time() - start_time
        
        state['gpt_reasoning'] = reasoning or 'Move selected.'
        state['gpt_last_time'] = round(elapsed, 2)
        state['gpt_total_time'] = round(state['gpt_total_time'] + elapsed, 2)
    else:
        player_name = "Player B (Claude - Yellow)"
        prompt = generate_move_prompt(player_name, piece, state['board'], 
                                       valid_cols, state['move_history'], state['turn_count'])
        
        # Determine if this model uses thinking
        use_thinking = state['claude_model'] not in ('claude-haiku-4.5-standard', 'claude-sonnet-4.5-standard')
        
        start_time = time.time()
        try:
            column, reasoning = call_claude_move_with_thinking_flag(
                prompt, state['claude_model_id'], use_thinking
            )
        except Exception as e:
            return jsonify({'error': f'Claude API error: {str(e)}'}), 500
        elapsed = time.time() - start_time
        
        state['claude_reasoning'] = reasoning or 'Move selected.'
        state['claude_last_time'] = round(elapsed, 2)
        state['claude_total_time'] = round(state['claude_total_time'] + elapsed, 2)
    
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
            'turns': state['turn_count'],
            'gpt_time': state['gpt_total_time'],
            'claude_time': state['claude_total_time']
        })
    elif is_board_full(state['board']):
        state['game_over'] = True
        state['winner'] = 'draw'
        state['gpt_stats']['draws'] += 1
        state['claude_stats']['draws'] += 1
        
        state['game_history'].append({
            'game': state['current_game'],
            'time': datetime.now().strftime('%H:%M:%S'),
            'winner': 'Draw',
            'turns': state['turn_count'],
            'gpt_time': state['gpt_total_time'],
            'claude_time': state['claude_total_time']
        })
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


@app.route('/api/next-game', methods=['POST'])
def next_game():
    """Start the next game in the series."""
    global GAME_STATE
    state = GAME_STATE
    if not state:
        return jsonify({'error': 'No game in progress'}), 400
    
    if state['current_game'] >= state['total_games']:
        return jsonify({'error': 'All games completed'}), 400
    
    # Preserve stats, history, and model settings
    gpt_stats = state['gpt_stats']
    claude_stats = state['claude_stats']
    history = state['game_history']
    total_games = state['total_games']
    current_game = state['current_game'] + 1
    gpt_model = state['gpt_model']
    claude_model = state['claude_model']
    
    # Create fresh game state
    new_state = init_game_state(gpt_model=gpt_model, claude_model=claude_model)
    new_state['gpt_stats'] = gpt_stats
    new_state['claude_stats'] = claude_stats
    new_state['game_history'] = history
    new_state['total_games'] = total_games
    new_state['current_game'] = current_game
    
    GAME_STATE = new_state
    
    return jsonify({
        'success': True,
        'game_state': get_client_state(new_state)
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
    }


if __name__ == '__main__':
    app.run(debug=True, port=5001)
