// DOM Elements
const modalOverlay = document.getElementById('modal-overlay');
const gameCountSelect = document.getElementById('game-count');
const gptModelSelect = document.getElementById('gpt-model');
const claudeModelSelect = document.getElementById('claude-model');
const btnRun = document.getElementById('btn-run');
const gameContainer = document.getElementById('game-container');
const statsSection = document.getElementById('stats-section');
const phaseIndicator = document.getElementById('phase-indicator');

// Model name display elements
const gptModelNameEl = document.getElementById('gpt-model-name');
const claudeModelNameEl = document.getElementById('claude-model-name');

// Game state display elements
const gameNumberEl = document.getElementById('game-number');
const totalGamesEl = document.getElementById('total-games');
const gameStatusEl = document.getElementById('game-status');

// Board element
const boardEl = document.getElementById('connect4-board');

// GPT elements
const gptThinkingEl = document.getElementById('gpt-thinking');
const gptWinsEl = document.getElementById('gpt-wins');
const gptLossesEl = document.getElementById('gpt-losses');
const gptDrawsEl = document.getElementById('gpt-draws');
const gptReasoningEl = document.getElementById('gpt-reasoning');
const gptTimerEl = document.getElementById('gpt-timer');
const gptLastTimeEl = document.getElementById('gpt-last-time');
const gptTotalTimeEl = document.getElementById('gpt-total-time');
const gptLastMoveEl = document.getElementById('gpt-last-move');

// Claude elements
const claudeThinkingEl = document.getElementById('claude-thinking');
const claudeWinsEl = document.getElementById('claude-wins');
const claudeLossesEl = document.getElementById('claude-losses');
const claudeDrawsEl = document.getElementById('claude-draws');
const claudeReasoningEl = document.getElementById('claude-reasoning');
const claudeTimerEl = document.getElementById('claude-timer');
const claudeLastTimeEl = document.getElementById('claude-last-time');
const claudeTotalTimeEl = document.getElementById('claude-total-time');
const claudeLastMoveEl = document.getElementById('claude-last-move');

// Stats table
const statsBody = document.getElementById('stats-body');

// Constants
const COLS = 7;
const ROWS = 6;

// Game state
let isRunning = false;
let timerInterval = null;
let timerStartTime = null;
let currentTimerEl = null;

// Initialize board
function initBoard() {
    boardEl.innerHTML = '';

    for (let row = 0; row < ROWS; row++) {
        for (let col = 0; col < COLS; col++) {
            const cell = document.createElement('div');
            cell.className = 'cell';
            cell.dataset.row = row;
            cell.dataset.col = col;
            boardEl.appendChild(cell);
        }
    }
}

// Initialize
initBoard();
btnRun.addEventListener('click', startGames);

function startTimer(timerEl) {
    stopTimer();
    timerStartTime = Date.now();
    currentTimerEl = timerEl;
    timerEl.textContent = '0.0s';

    timerInterval = setInterval(() => {
        const elapsed = (Date.now() - timerStartTime) / 1000;
        timerEl.textContent = elapsed.toFixed(1) + 's';
    }, 100);
}

function stopTimer() {
    if (timerInterval) {
        clearInterval(timerInterval);
        timerInterval = null;
    }
}

async function startGames() {
    const numGames = parseInt(gameCountSelect.value);
    const gptModel = gptModelSelect.value;
    const claudeModel = claudeModelSelect.value;

    try {
        const response = await fetch('/api/start-games', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                num_games: numGames,
                gpt_model: gptModel,
                claude_model: claudeModel
            })
        });

        const data = await response.json();
        if (data.success) {
            modalOverlay.classList.add('hidden');
            gameContainer.classList.remove('hidden');
            statsSection.classList.remove('hidden');

            initBoard();
            updateUI(data.game_state);
            runGameLoop();
        }
    } catch (error) {
        console.error('Error starting games:', error);
        alert('Failed to start games. Check console for details.');
    }
}

async function runGameLoop() {
    if (isRunning) return;
    isRunning = true;

    while (isRunning) {
        // Get current state
        const stateResponse = await fetch('/api/game-state');
        const state = await stateResponse.json();

        if (state.all_games_complete) {
            gameStatusEl.textContent = '🏆 All games complete!';
            phaseIndicator.textContent = 'Series Complete';
            isRunning = false;
            break;
        }

        if (state.game_over) {
            // Show result briefly, then start next game
            await sleep(3000);

            const nextResponse = await fetch('/api/next-game', { method: 'POST' });
            const nextData = await nextResponse.json();

            if (nextData.success) {
                initBoard();
                updateUI(nextData.game_state);
                gptReasoningEl.textContent = 'Waiting for move...';
                claudeReasoningEl.textContent = 'Waiting for move...';
                gptLastMoveEl.textContent = '—';
                claudeLastMoveEl.textContent = '—';
            } else {
                isRunning = false;
                break;
            }

            await sleep(1000);
            continue;
        }

        // Show thinking indicator for current player
        phaseIndicator.textContent = '🎮 Playing';

        if (state.current_player === 'gpt') {
            gptThinkingEl.classList.remove('hidden');
            claudeThinkingEl.classList.add('hidden');
            gameStatusEl.textContent = "🔴 GPT is thinking...";
            startTimer(gptTimerEl);
        } else {
            claudeThinkingEl.classList.remove('hidden');
            gptThinkingEl.classList.add('hidden');
            gameStatusEl.textContent = "🟡 Claude is thinking...";
            startTimer(claudeTimerEl);
        }

        // Make the move
        try {
            const moveResponse = await fetch('/api/next-move', { method: 'POST' });
            const moveData = await moveResponse.json();

            stopTimer();
            gptThinkingEl.classList.add('hidden');
            claudeThinkingEl.classList.add('hidden');

            if (moveData.success) {
                updateUI(moveData.game_state);

                // Update last move display
                const colDisplay = `Column ${moveData.column}`;
                if (moveData.player === 'gpt') {
                    gptLastMoveEl.textContent = colDisplay;
                } else {
                    claudeLastMoveEl.textContent = colDisplay;
                }

                // Show result
                if (moveData.game_state.game_over) {
                    const winner = moveData.game_state.winner;
                    if (winner === 'draw') {
                        gameStatusEl.textContent = "🤝 It's a draw!";
                    } else {
                        gameStatusEl.textContent = winner === 'gpt' ?
                            '🎉 GPT (Red) wins!' : '🎉 Claude (Yellow) wins!';
                    }
                    phaseIndicator.textContent = 'Game Over';
                } else {
                    const playerEmoji = moveData.player === 'gpt' ? '🔴' : '🟡';
                    const playerName = moveData.player === 'gpt' ? 'GPT' : 'Claude';
                    gameStatusEl.textContent = `${playerEmoji} ${playerName} played Column ${moveData.column}`;
                }
            } else {
                console.error('Move error:', moveData.error);
                gameStatusEl.textContent = 'Error: ' + moveData.error;
                isRunning = false;
                break;
            }
        } catch (error) {
            console.error('API error:', error);
            gameStatusEl.textContent = 'API Error - check console';
            stopTimer();
            gptThinkingEl.classList.add('hidden');
            claudeThinkingEl.classList.add('hidden');
            isRunning = false;
            break;
        }

        await sleep(1500);
    }
}

function updateUI(state) {
    // Update game number
    gameNumberEl.textContent = state.current_game;
    totalGamesEl.textContent = state.total_games;

    // Update board
    updateBoard(state.board, state.last_move);

    // Update stats
    gptWinsEl.textContent = state.gpt_stats.wins;
    gptLossesEl.textContent = state.gpt_stats.losses;
    gptDrawsEl.textContent = state.gpt_stats.draws || 0;
    claudeWinsEl.textContent = state.claude_stats.wins;
    claudeLossesEl.textContent = state.claude_stats.losses;
    claudeDrawsEl.textContent = state.claude_stats.draws || 0;

    // Update timing
    gptLastTimeEl.textContent = state.gpt_last_time + 's';
    gptTotalTimeEl.textContent = state.gpt_total_time + 's';
    claudeLastTimeEl.textContent = state.claude_last_time + 's';
    claudeTotalTimeEl.textContent = state.claude_total_time + 's';

    // Update reasoning
    if (state.gpt_reasoning) {
        gptReasoningEl.textContent = state.gpt_reasoning;
    }
    if (state.claude_reasoning) {
        claudeReasoningEl.textContent = state.claude_reasoning;
    }

    // Update game history table
    updateStatsTable(state.game_history);

    // Update model display names
    if (state.gpt_display_name) {
        gptModelNameEl.textContent = state.gpt_display_name;
    }
    if (state.claude_display_name) {
        claudeModelNameEl.textContent = state.claude_display_name;
    }
}

function updateBoard(board, lastMove) {
    const cells = boardEl.querySelectorAll('.cell');

    cells.forEach(cell => {
        const row = parseInt(cell.dataset.row);
        const col = parseInt(cell.dataset.col);
        const value = board[row][col];

        // Reset classes
        cell.className = 'cell';

        if (value === 'R') {
            cell.classList.add('piece-red');
        } else if (value === 'Y') {
            cell.classList.add('piece-yellow');
        }

        // Highlight last move
        if (lastMove && lastMove.row === row && lastMove.col === (col)) {
            cell.classList.add('last-move');
        }
    });
}

function updateStatsTable(history) {
    statsBody.innerHTML = '';

    history.forEach(game => {
        const row = document.createElement('tr');

        let winnerClass = 'winner-draw';
        if (game.winner !== 'Draw') {
            // Check if winner contains GPT or Claude
            if (game.winner.includes('GPT')) {
                winnerClass = 'winner-gpt';
            } else if (game.winner.includes('Claude')) {
                winnerClass = 'winner-claude';
            }
        }

        row.innerHTML = `
            <td>${game.game}</td>
            <td>${game.time}</td>
            <td class="${winnerClass}">${game.winner}</td>
            <td>${game.turns || 0}</td>
            <td>${game.gpt_time || 0}</td>
            <td>${game.claude_time || 0}</td>
        `;

        statsBody.appendChild(row);
    });
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}
