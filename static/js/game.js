'use strict';

const $ = (id) => document.getElementById(id);
const names = { gpt: 'GPT', claude: 'Claude' };
const pieces = { gpt: 'R', claude: 'Y' };
const ROWS = 6;
const COLS = 7;
let configuration = null;
const effortLevels = {gpt: ['default'], claude: ['default']};
const effortLabels = {default: 'Default', none: 'None', minimal: 'Minimal', low: 'Low', medium: 'Medium', high: 'High', xhigh: 'X-high', max: 'Max', ultra: 'Ultra', persistent: 'Persistent'};
const settingsKey = 'connect4-settings';
let preferences = {};
try { preferences = JSON.parse(localStorage.getItem(settingsKey)) || {}; } catch {}
let mode = 'loading';
let state = null;
let loopActive = false;
let timer = null;
let renderedGame = null;
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function setStatus(title, detail) {
    $('game-status').textContent = title;
    $('status-detail').textContent = detail;
}

function setMode(next) {
    mode = next;
    const active = ['running', 'pausing'].includes(mode);
    const loading = ['loading', 'starting'].includes(mode);
    $('play-mode').disabled = active || loading;
    for (const key of Object.keys(names)) {
        $(key + '-model').disabled = active || loading || !$(key + '-model').value;
        $(key + '-effort').disabled = active || loading || effortLevels[key].length <= 1;
    }
    $('btn-run').disabled = loading || (configuration ? !['gpt', 'claude'].every(key => $(key + '-model').value) : mode !== 'error');
    $('btn-run').querySelector('span').textContent = ({loading: 'Loading…', starting: 'Starting…', error: 'Try again'})[mode] || 'Start match';
    $('btn-pause').classList.toggle('hidden', !active);
    $('btn-pause').disabled = mode === 'pausing';
    $('btn-pause').textContent = mode === 'pausing' ? 'Pausing…' : 'Pause';
    $('btn-resume').classList.toggle('hidden', !(state && ['paused', 'error'].includes(mode)));
    $('btn-resume').textContent = mode === 'error' ? 'Retry move' : 'Resume match';
    $('btn-new').disabled = active || loading;
    $('session-title').textContent = ({loading: 'Loading', idle: 'Ready', starting: 'Starting', running: 'Match in progress', pausing: 'Finishing turn', paused: 'Match paused', error: 'Match interrupted', complete: 'Game over'})[mode];
    $('session-indicator').className = 'status-dot ' + mode;
}

function showMatch() {
    $('setup').classList.add('hidden');
    $('match-view').classList.remove('hidden');
    document.querySelector('.skip-link').href = '#arena';
    document.querySelector('.skip-link').textContent = 'Skip to match';
    loadMatchHistory();
}

function selectedModel(key) {
    return configuration?.models[$('play-mode').value]?.[key]?.models.find(model => model.id === $(key + '-model').value);
}

function readEffort(key) {
    return effortLevels[key][Number($(key + '-effort').value)] || 'default';
}

function updateEffortLabel(key) {
    const value = readEffort(key);
    $(key + '-effort-value').textContent = effortLevels[key].length > 1 ? effortLabels[value] || value
        : $('play-mode').value === 'test' ? 'Not used' : $('play-mode').value === 'api' ? 'Set by model' : !selectedModel(key) ? 'Unavailable'
        : 'Not supported';
    $(key + '-effort').setAttribute('aria-valuetext', $(key + '-effort-value').textContent);
    $(key + '-effort').style.setProperty('--fill', Number($(key + '-effort').value) / (Number($(key + '-effort').max) || 1));
    for (const [index, tick] of [...$(key + '-effort-ticks').children].entries()) {
        tick.classList.toggle('is-selected', index === Number($(key + '-effort').value));
    }
}

function populateEffort(key, preferred) {
    const model = selectedModel(key);
    effortLevels[key] = model?.efforts || ['default'];
    const value = effortLevels[key].includes(preferred) ? preferred : model?.default_effort || 'default';
    const slider = $(key + '-effort');
    slider.max = effortLevels[key].length - 1;
    slider.value = Math.max(0, effortLevels[key].indexOf(value));
    slider.disabled = effortLevels[key].length <= 1 || ['loading', 'starting', 'running', 'pausing'].includes(mode);
    $(key + '-effort-max').textContent = effortLevels[key].length > 1 ? effortLabels[effortLevels[key].at(-1)] : '';
    const ticks = $(key + '-effort-ticks');
    ticks.replaceChildren();
    if (effortLevels[key].length > 1) {
        for (const effort of effortLevels[key]) {
            const tick = document.createElement('span');
            tick.title = effortLabels[effort] || effort;
            ticks.appendChild(tick);
        }
    }
    updateEffortLabel(key);
}

// Fill each player's model list for a connection, keeping the last choice made in that connection.
function populateModels(selectedMode, preferred = {}) {
    const saved = preferences.models?.[selectedMode] || {};
    for (const key of Object.keys(names)) {
        const info = configuration.models[selectedMode][key];
        const select = $(key + '-model');
        select.replaceChildren();
        for (const model of info.models) {
            const option = document.createElement('option');
            option.value = model.id;
            option.textContent = model.name;
            select.appendChild(option);
        }
        if (!info.models.length) {
            const empty = document.createElement('option');
            empty.value = '';
            empty.textContent = 'Unavailable';
            select.appendChild(empty);
        }
        const previous = preferred[key + '_model'] || saved[key + '_model'] || info.default;
        const requested = info.aliases?.[previous] || previous;
        select.value = info.models.some(item => item.id === requested) ? requested : info.default;
        $(key + '-model-note').textContent = info.message || '';
        $(key + '-model-note').classList.toggle('hidden', !info.message);
        populateEffort(key, preferred[key + '_effort'] || saved[key + '_effort']);
    }
}

function rememberSettings() {
    const selected = $('play-mode').value;
    preferences.mode = selected;
    preferences.models = preferences.models || {};
    preferences.models[selected] = {gpt_model: $('gpt-model').value, claude_model: $('claude-model').value, gpt_effort: readEffort('gpt'), claude_effort: readEffort('claude')};
    try { localStorage.setItem(settingsKey, JSON.stringify(preferences)); } catch {}
}

async function newMatch() {
    if (loopActive) return;
    $('btn-new').disabled = true;
    try {
        await request('reset', {method: 'POST'});
        state = null;
        renderedGame = null;
        clearThinking();
        $('error-message').classList.add('hidden');
        $('match-view').classList.add('hidden');
        $('setup').classList.remove('hidden');
        document.querySelector('.skip-link').href = '#setup';
        document.querySelector('.skip-link').textContent = 'Skip to setup';
        if (configuration) populateModels($('play-mode').value);
        setMode('idle');
        loadMatchHistory();
        $('setup-title').focus({preventScroll: true});
        window.scrollTo(0, 0);
    } catch (error) { showError(error); }
}

async function request(path, options = {}) {
    const response = await fetch('/api/' + path, options);
    let data;
    try {
        data = await response.json();
    } catch {
        throw new Error('The server returned an unexpected response. Check that the app is running, then try again.');
    }
    if (!response.ok || data.success === false || data.error) {
        throw new Error(data.error || 'The request could not be completed. Please try again.');
    }
    return data;
}

function showError(error) {
    $('error-message').textContent = error.message || 'Connection lost. Check that the app is running, then try again.';
    $('error-message').classList.remove('hidden');
    setMode('error');
    setStatus('Match interrupted.', state ? 'Retry the move or start a new match.' : '');
}

function clearThinking() {
    clearInterval(timer);
    timer = null;
    for (const model of Object.keys(names)) {
        $(model + '-thinking').classList.add('hidden');
        $(model + '-idle').classList.remove('hidden');
        $(model + '-panel').classList.remove('is-thinking');
    }
}

function showThinking(model) {
    clearThinking();
    $(model + '-thinking').classList.remove('hidden');
    $(model + '-idle').classList.add('hidden');
    $(model + '-panel').classList.add('is-thinking');
    $(model + '-timer').textContent = '0.0s';
    const start = performance.now();
    timer = setInterval(() => {
        $(model + '-timer').textContent = ((performance.now() - start) / 1000).toFixed(1) + 's';
    }, 100);
    setStatus(names[model] + ' is thinking.', '');
}

// The four in a row that won the game, found from the last disc played, as [row, col] pairs.
function winningCells(current) {
    const move = current.last_move;
    if (!current.winner || current.winner === 'draw' || !move) return [];
    const piece = pieces[current.winner];
    const row = move.row, col = move.col - 1;
    const owns = (r, c) => r >= 0 && r < ROWS && c >= 0 && c < COLS && current.board[r][c] === piece;
    for (const [dr, dc] of [[0, 1], [1, 0], [1, 1], [1, -1]]) {
        const line = [[row, col]];
        for (let r = row + dr, c = col + dc; owns(r, c); r += dr, c += dc) line.push([r, c]);
        for (let r = row - dr, c = col - dc; owns(r, c); r -= dr, c -= dc) line.unshift([r, c]);
        if (line.length >= 4) return line;
    }
    return [];
}

function renderBoard(current, animate) {
    const line = winningCells(current);
    const winning = new Set(line.map(([r, c]) => r + ':' + c));
    const last = current.last_move;
    $('board').setAttribute('aria-label', 'Connect 4 board. Game ' + current.current_game + ' of ' + current.total_games + '.');
    for (const cell of $('board').children) {
        const row = Number(cell.dataset.row), col = Number(cell.dataset.col);
        const value = current.board[row][col];
        const previous = cell.dataset.value || '.';
        cell.dataset.value = value;
        const label = 'Column ' + (col + 1) + ', row ' + (ROWS - row) + ': ';
        cell.setAttribute('aria-label', label + ({R: 'red', Y: 'yellow'}[value] || 'empty') + (winning.has(row + ':' + col) ? ', winning disc' : ''));
        cell.classList.toggle('R', value === 'R');
        cell.classList.toggle('Y', value === 'Y');
        if (value === 'R' || value === 'Y') {
            // The drop class stays until the disc has landed, so a re-render never cuts the fall short.
            if (previous !== value && animate) {
                cell.classList.add('new-move');
                cell.style.setProperty('--drop-rows', row + 1);
            }
            if (!cell.firstChild) cell.innerHTML = '<span class="disc" aria-hidden="true"></span>';
        } else {
            cell.classList.remove('new-move');
            cell.replaceChildren();
        }
        cell.classList.toggle('last-move', Boolean(last && last.row === row && last.col - 1 === col && !winning.size));
        cell.classList.toggle('winner', winning.has(row + ':' + col));
    }
    const strike = $('winning-line');
    if (line.length) {
        const center = ([r, c]) => ({x: c * 100 + 50, y: r * 100 + 50});
        const start = center(line[0]);
        const end = center(line.at(-1));
        const graphic = strike.querySelector('line');
        for (const [attribute, value] of Object.entries({x1: start.x, y1: start.y, x2: end.x, y2: end.y})) graphic.setAttribute(attribute, value);
        strike.dataset.winner = pieces[current.winner];
        strike.classList.add('is-visible');
    } else {
        strike.classList.remove('is-visible');
        delete strike.dataset.winner;
    }
}

// The winner wears the crown once the game ends.
function renderScoreboard(current) {
    const crowned = current.game_over && current.winner !== 'draw' ? current.winner : null;
    for (const model of Object.keys(names)) document.querySelector('.' + model + '-side').classList.toggle('has-crown', crowned === model);
}

// Confetti for a win: a burst from the winner's mascot and cannons from both bottom corners.
const confettiColors = ['#d61f29', '#f5c211', '#0071e3', '#34c759', '#ff9f0a', '#af52de'];
let confetti = [];
let confettiRunning = false;

function celebrate(current) {
    const winner = current.winner !== 'draw' ? current.winner : null;
    if (!winner || document.hidden || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    let canvas = $('confetti');
    if (!canvas) {
        canvas = document.createElement('canvas');
        canvas.id = 'confetti';
        canvas.className = 'confetti';
        canvas.setAttribute('aria-hidden', 'true');
        document.body.append(canvas);
    }
    const avatar = document.querySelector('.' + winner + '-side .avatar').getBoundingClientRect();
    const bursts = [
        {x: avatar.left + avatar.width / 2, y: avatar.top + avatar.height / 2, angle: Math.PI / 2, spread: 2.6, speed: [250, 750], count: 110},
        {x: 0, y: innerHeight, angle: Math.PI / 3, spread: .7, speed: [900, 1500], count: 120},
        {x: innerWidth, y: innerHeight, angle: Math.PI * 2 / 3, spread: .7, speed: [900, 1500], count: 120},
    ];
    for (const burst of bursts) {
        for (let i = 0; i < burst.count; i++) {
            const angle = burst.angle + (Math.random() - .5) * burst.spread;
            const speed = burst.speed[0] + Math.random() * (burst.speed[1] - burst.speed[0]);
            confetti.push({
                x: burst.x, y: burst.y, vx: Math.cos(angle) * speed, vy: -Math.sin(angle) * speed,
                w: 6 + Math.random() * 6, h: 3 + Math.random() * 4, rotation: Math.random() * Math.PI, spin: (Math.random() - .5) * 12,
                flutter: Math.random() * Math.PI * 2, color: confettiColors[Math.floor(Math.random() * confettiColors.length)], age: 0,
            });
        }
    }
    if (!confettiRunning) {
        confettiRunning = true;
        requestAnimationFrame(time => drawConfetti(canvas, time, time));
    }
}

// Each piece falls under gravity with air drag and flutters as it turns; the loop stops once every piece has left the screen.
function drawConfetti(canvas, time, last) {
    const dt = Math.min((time - last) / 1000, .05);
    const ratio = devicePixelRatio || 1;
    if (canvas.width !== Math.round(innerWidth * ratio) || canvas.height !== Math.round(innerHeight * ratio)) {
        canvas.width = Math.round(innerWidth * ratio);
        canvas.height = Math.round(innerHeight * ratio);
    }
    const context = canvas.getContext('2d');
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, innerWidth, innerHeight);
    confetti = confetti.filter(piece => piece.y < innerHeight + 30 && piece.age < 6);
    for (const piece of confetti) {
        const drag = Math.exp(-1.6 * dt);
        piece.vx *= drag;
        piece.vy = piece.vy * drag + 1100 * dt;
        piece.x += (piece.vx + Math.sin(piece.flutter) * 40) * dt;
        piece.y += piece.vy * dt;
        piece.rotation += piece.spin * dt;
        piece.flutter += 9 * dt;
        piece.age += dt;
        context.save();
        context.translate(piece.x, piece.y);
        context.rotate(piece.rotation);
        context.scale(1, Math.cos(piece.flutter));
        context.globalAlpha = Math.min(1, 6 - piece.age);
        context.fillStyle = piece.color;
        context.fillRect(-piece.w / 2, -piece.h / 2, piece.w, piece.h);
        context.restore();
    }
    if (confetti.length) requestAnimationFrame(next => drawConfetti(canvas, next, time));
    else confettiRunning = false;
}

function renderMode(selected) {
    $('play-mode').value = selected;
    $('test-badge').classList.toggle('hidden', selected !== 'test');
    $('mode-description').textContent = ({local: 'Signed-in CLIs', api: 'API keys required', test: 'Simulated players'})[selected];
}

function render(current) {
    const changedGame = renderedGame !== current.current_game;
    state = current;
    names.gpt = current.gpt_display_name;
    names.claude = current.claude_display_name;
    renderedGame = current.current_game;
    renderScoreboard(current);
    renderBoard(current, !changedGame);
    for (const model of Object.keys(names)) {
        $(model + '-name').textContent = names[model];
        $(model + '-provider').textContent = current.mode === 'test' ? 'Simulated' : model === 'gpt' ? 'OpenAI' : 'Anthropic';
        $(model + '-mode').textContent = ({local: model === 'gpt' ? 'Codex SDK' : 'Claude CLI', api: 'API'})[current.mode] || '';
        const effort = current[model + '_effort'] || 'default';
        $(model + '-effort-detail').textContent = current.mode === 'test' ? 'Not used' : current.mode === 'api' ? 'Set by model' : effortLabels[effort] || effort;
        $(model + '-stats').setAttribute('aria-label', names[model] + ' results');
        for (const result of ['wins', 'losses', 'draws']) {
            $(model + '-' + result).textContent = current[model + '_stats'][result] || 0;
        }
        $(model + '-last-time').textContent = Number(current[model + '_last_time'] || 0).toFixed(1) + 's';
        $(model + '-total-time').textContent = Number(current[model + '_total_time'] || 0).toFixed(1) + 's';
        $(model + '-reasoning').textContent = current[model + '_reasoning'] || 'No moves yet.';
        $(model + '-idle').textContent = current.game_over ? 'Game finished' : current.current_player === model ? 'Up next' : 'Waiting for its turn';
        if (changedGame) $(model + '-last-move').textContent = '—';
    }
    if (current.game_over) setStatus(current.winner === 'draw' ? 'Draw.' : names[current.winner] + ' wins.', '');
}

async function loadMatchHistory() {
    try {
        const archive = await request('match-history', {cache: 'no-store'});
        renderHistory(archive.rounds, archive.totals);
    } catch {
        renderHistory([]);
        $('history-empty').textContent = 'Match history is unavailable.';
    }
}

// A player as the archive saved them, with the effort they played at.
function playerLabel(name, effort) {
    return effort && effort !== 'default' ? `${name} · ${effortLabels[effort] || effort}` : name;
}

function gamePlayers(game) {
    return [playerLabel(game.gpt_name, game.gpt_effort), playerLabel(game.claude_name, game.claude_effort)].filter(Boolean).join(' vs ') || '—';
}

function gameResult(game) {
    return game.winner === 'gpt' ? (game.gpt_name || 'GPT') + ' won' : game.winner === 'claude' ? (game.claude_name || 'Claude') + ' won' : 'Draw';
}

// One row per saved game on the setup page: who won it, the players at their effort, and when it finished.
function renderUniversalGames(games) {
    const rows = [...games].reverse().map(game => {
        const row = document.createElement('li');
        row.className = 'universal-match';
        const badge = document.createElement('span');
        badge.className = 'match-badge';
        badge.dataset.winner = game.winner;
        if (game.winner === 'gpt' || game.winner === 'claude') {
            const pip = document.createElement('span');
            pip.className = 'pip';
            pip.dataset.result = game.winner;
            badge.appendChild(pip);
        } else badge.textContent = 'Draw';
        badge.title = gameResult(game);
        const info = document.createElement('span');
        info.className = 'match-players';
        const players = document.createElement('b');
        players.textContent = gamePlayers(game);
        const when = document.createElement('small');
        when.textContent = [game.finished_at || '—', game.turns ? game.turns + ' moves' : ''].filter(Boolean).join(' · ');
        info.append(players, when);
        row.append(badge, info);
        return row;
    });
    $('universal-matches').replaceChildren(...rows);
    $('universal-matches').classList.toggle('hidden', rows.length === 0);
}

function renderHistory(games, totals = {gpt: 0, claude: 0, draw: 0}) {
    $('history-empty').textContent = 'No games yet.';
    $('history-empty').classList.toggle('hidden', games.length > 0);
    $('history-table-wrap').classList.toggle('hidden', games.length === 0);
    $('history-count').textContent = games.length + (games.length === 1 ? ' game' : ' games');
    for (const element of document.querySelectorAll('[data-match-total]')) element.textContent = totals[element.dataset.matchTotal] || 0;
    $('universal-meta').textContent = $('history-count').textContent;
    $('overall-score').setAttribute('aria-label', `All-time games: GPT won ${totals.gpt || 0}, Claude won ${totals.claude || 0}, ${totals.draw || 0} draws`);
    renderUniversalGames(games);
    $('stats-body').replaceChildren();
    for (const game of [...games].reverse()) {
        const row = document.createElement('tr');
        for (const value of [game.finished_at || '—', gamePlayers(game), gameResult(game)]) {
            const cell = document.createElement('td');
            cell.textContent = value;
            row.appendChild(cell);
        }
        $('stats-body').appendChild(row);
    }
}

function finishGame() {
    setMode('complete');
    setStatus(state.winner === 'draw' ? 'Draw.' : names[state.winner] + ' wins.', '');
}

async function runGameLoop() {
    if (loopActive) return;
    loopActive = true;
    setMode('running');
    try {
        while (mode === 'running') {
            const current = await request('game-state');
            render(current);
            if (current.game_over) {
                finishGame();
                break;
            }
            if (mode !== 'running') break;
            showThinking(current.current_player);
            const move = await request('next-move', { method: 'POST' });
            clearThinking();
            render(move.game_state);
            if (state.game_over) celebrate(state);
            if (move.player) $(move.player + '-last-move').textContent = 'Column ' + move.column;
            if (state.game_over) {
                loadMatchHistory();
                finishGame();
                break;
            }
            setStatus(names[move.player] + ' played column ' + move.column + '.', '');
            if (mode !== 'running') break;
            await sleep(state.mode === 'test' ? 450 : 1000);
        }
    } catch (error) {
        showError(error);
    } finally {
        clearThinking();
        loopActive = false;
        if (mode === 'pausing') {
            setMode('paused');
            setStatus('Paused.', '');
        }
    }
}

async function startGames(event) {
    event?.preventDefault();
    if (loopActive || ['loading', 'starting'].includes(mode)) return;
    $('error-message').classList.add('hidden');
    if (!configuration) {
        await restoreSession();
        return;
    }
    const settings = {
        mode: $('play-mode').value,
        gpt_model: $('gpt-model').value, claude_model: $('claude-model').value,
        gpt_effort: readEffort('gpt'), claude_effort: readEffort('claude'),
    };
    setMode('starting');
    try {
        const data = await request('start-games', {
            method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(settings),
        });
        rememberSettings();
        renderedGame = null;
        for (const detail of document.querySelectorAll('.player-more')) detail.open = false;
        $('history').open = false;
        render(data.game_state);
        showMatch();
        $('arena').focus({preventScroll: true});
        window.scrollTo(0, 0);
        await runGameLoop();
    } catch (error) { showError(error); }
}

$('board').addEventListener('animationend', event => {
    if (event.animationName === 'settle') event.target.closest('.cell')?.classList.remove('new-move');
});
$('setup-form').addEventListener('submit', startGames);
$('btn-new').addEventListener('click', newMatch);
$('btn-resume').addEventListener('click', () => {
    if (loopActive) return;
    $('error-message').classList.add('hidden');
    runGameLoop();
});
$('btn-pause').addEventListener('click', () => {
    if (mode !== 'running') return;
    setMode('pausing');
    setStatus('Pausing after this turn.', '');
});
$('play-mode').addEventListener('change', () => {
    const selected = $('play-mode').value;
    renderMode(selected);
    populateModels(selected);
    setMode(mode);
});
for (const key of Object.keys(names)) {
    $(key + '-model').addEventListener('change', () => {
        populateEffort(key);
        setMode(mode);
    });
    $(key + '-effort').addEventListener('input', () => updateEffortLabel(key));
}

// A match still held by the server comes back paused after a reload.
async function restoreSession() {
    loadMatchHistory();
    setMode('loading');
    try {
        configuration = await request('config');
        const selected = configuration.models[preferences.mode] ? preferences.mode : configuration.default_mode;
        renderMode(selected);
        populateModels(selected);
        const saved = await request('game-state');
        if (saved.started) {
            renderMode(saved.mode);
            populateModels(saved.mode, saved);
            render(saved);
            showMatch();
            if (saved.game_over) finishGame();
            else {
                setMode('paused');
                setStatus('Match paused.', '');
            }
        } else setMode('idle');
    } catch (error) { showError(error); }
}

// Liquid Glass controls catch light where the pointer is.
document.addEventListener('pointermove', event => {
    const glass = event.target.closest?.('.button, select');
    if (!glass) return;
    const box = glass.getBoundingClientRect();
    glass.style.setProperty('--mx', `${event.clientX - box.left}px`);
    glass.style.setProperty('--my', `${event.clientY - box.top}px`);
}, {passive: true});

restoreSession();
