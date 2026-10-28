import * as THREE from 'three';

// The board in WebGL: a blue plastic Connect 4 frame seen straight on, with ridged red and yellow checkers
// that fall down their column under gravity and bounce to rest. It mirrors the DOM grid in game.js, which
// stays in place for screen readers and as the fallback when WebGL is unavailable.
// Units are board cells: the 7 × 6 grid spans x -3.5…3.5 and y -3…3, and the stage shows x -4.6…4.6,
// y -4.5…4.4, matching the percentages in style.css.
const board = document.getElementById('board');
const stage = document.getElementById('board-stage');
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)');
const view = {left: -4.6, right: 4.6, top: 4.4, bottom: -4.5};
const fov = 18;
const holeRadius = .4;
const panel = {left: -3.85, right: 3.85, top: 3.25, bottom: -3.3, depth: .14, bevel: .035};
const piece = {radius: .44, root: .418, teeth: 36, depth: .1, bevel: .025};
const colors = {board: '#1238a6', R: '#d61f29', Y: '#f5c211'};
// Physics, in cells and seconds: gravity, how much speed survives each bounce, and when a bounce is too
// small to see so the checker simply comes to rest.
const gravity = 40, restitution = .32, restSpeed = 1.1;
const spawnY = 3.95;

if (board && stage) start();

function start() {
    const canvas = document.createElement('canvas');
    canvas.className = 'board-canvas';
    canvas.setAttribute('aria-hidden', 'true');
    let renderer;
    try {
        renderer = new THREE.WebGLRenderer({canvas, alpha: true, antialias: true, failIfMajorPerformanceCaveat: true});
    } catch {
        return;
    }
    // Software-only WebGL is far too slow for this scene, so those browsers keep the CSS board.
    const gl = renderer.getContext();
    const debug = gl.getExtension('WEBGL_debug_renderer_info');
    if (/swiftshader|llvmpipe|software/i.test(gl.getParameter(debug ? debug.UNMASKED_RENDERER_WEBGL : gl.RENDERER))) {
        renderer.dispose();
        return;
    }
    renderer.setClearColor(0x000000, 0);
    renderer.toneMapping = THREE.NeutralToneMapping;
    renderer.toneMappingExposure = 1.05;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    // Straight on, never angled: the camera looks along -z at the middle of the stage, and the narrow lens
    // keeps the frame flat while still showing the inside walls of the holes and the tops of the feet.
    const centerY = (view.top + view.bottom) / 2;
    const camera = new THREE.PerspectiveCamera(fov, (view.right - view.left) / (view.top - view.bottom), 1, 80);
    camera.position.set(0, centerY, (view.top - view.bottom) / 2 / Math.tan(THREE.MathUtils.degToRad(fov / 2)));
    camera.lookAt(0, centerY, 0);

    const scene = new THREE.Scene();
    scene.environment = studioEnvironment(renderer);
    const key = new THREE.DirectionalLight(0xffffff, 2.4);
    key.position.set(-4, 7, 10);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    Object.assign(key.shadow.camera, {left: -6.5, right: 6.5, top: 6.5, bottom: -6.5, near: 1, far: 30});
    key.shadow.bias = -.0004;
    key.shadow.normalBias = .02;
    key.shadow.radius = 4;
    const fill = new THREE.DirectionalLight(0xe8efff, .55);
    fill.position.set(5, -1, 6);
    scene.add(key, fill, new THREE.HemisphereLight(0xffffff, 0xd9e0ee, .45));

    const plastic = (color, options = {}) => new THREE.MeshPhysicalMaterial({color, roughness: .32, metalness: 0, clearcoat: .6, clearcoatRoughness: .22, envMapIntensity: .75, ...options});
    const blue = plastic(colors.board);
    scene.add(buildFrame(blue));
    scene.add(contactShadow());

    const checker = checkerGeometry();
    const materials = {R: plastic(colors.R, {roughness: .3, clearcoat: .8, clearcoatRoughness: .12}), Y: plastic(colors.Y, {roughness: .3, clearcoat: .8, clearcoatRoughness: .12})};
    const pieces = new Map();
    let frame = 0;
    let last = 0;

    function cellPosition(row, col) {
        return {x: col - 3, y: 2.5 - row};
    }

    function createPiece(color, row, col, drop) {
        const group = new THREE.Group();
        for (const geometry of checker) {
            const mesh = new THREE.Mesh(geometry, materials[color]);
            mesh.castShadow = true;
            mesh.receiveShadow = true;
            group.add(mesh);
        }
        const {x, y} = cellPosition(row, col);
        group.position.set(x, drop ? spawnY : y, 0);
        group.rotation.z = Math.random() * Math.PI * 2;
        scene.add(group);
        return {color, group, rest: y, vy: 0, falling: drop, spin: 0, wobble: 0, wobbleAge: 0, winner: false, material: null};
    }

    function removePiece(item) {
        item.group.removeFromParent();
        item.material?.dispose();
    }

    // A winning checker gets its own copy of the plastic so it can glow on its own.
    function setWinner(item, winner) {
        if (item.winner === winner) return;
        item.winner = winner;
        item.material?.dispose();
        item.material = winner ? materials[item.color].clone() : null;
        for (const mesh of item.group.children) mesh.material = item.material || materials[item.color];
    }

    // Mirror the DOM grid. A cell that game.js marks as a new move drops in from the top of its column.
    function sync() {
        for (const cell of board.children) {
            const key = cell.dataset.row + ':' + cell.dataset.col;
            const value = cell.dataset.value;
            let item = pieces.get(key);
            if (item && item.color !== value) {
                removePiece(item);
                pieces.delete(key);
                item = null;
            }
            if (!item && (value === 'R' || value === 'Y')) {
                item = createPiece(value, Number(cell.dataset.row), Number(cell.dataset.col), cell.classList.contains('new-move') && !reducedMotion.matches && !document.hidden);
                pieces.set(key, item);
            }
            if (item) setWinner(item, cell.classList.contains('winner'));
        }
        wake();
    }

    function step(item, dt) {
        item.vy -= gravity * dt;
        item.group.position.y += item.vy * dt;
        if (item.group.position.y <= item.rest) {
            item.group.position.y = item.rest;
            const impact = -item.vy;
            if (impact > restSpeed) {
                // Each bounce keeps a share of the speed, and the knock sets the checker turning and rocking in its slot.
                item.vy = impact * restitution;
                item.spin += (Math.random() - .5) * impact * .35;
                item.wobble = Math.min(.05, impact * .0025) * (Math.random() < .5 ? -1 : 1);
                item.wobbleAge = 0;
            } else {
                item.vy = 0;
                item.falling = false;
            }
        }
    }

    function render(time) {
        // A late frame catches up in small sub-steps, so a busy or backgrounded page never slows the fall.
        const dt = Math.min((time - (last || time)) / 1000, .25);
        last = time;
        let moving = false;
        for (const item of pieces.values()) {
            if (item.falling) {
                // Small fixed steps keep fast impacts from tunnelling past the resting height.
                for (let t = 0; t < dt && item.falling; t += 1 / 240) step(item, Math.min(1 / 240, dt - t));
                moving = true;
            }
            if (item.spin || item.wobble) {
                item.group.rotation.z += item.spin * dt;
                item.spin *= Math.exp(-4 * dt);
                item.wobbleAge += dt;
                const rock = item.wobble * Math.exp(-7 * item.wobbleAge) * Math.cos(item.wobbleAge * 34);
                item.group.rotation.y = rock;
                item.group.rotation.x = rock * .6;
                if (Math.abs(item.spin) < .01 && item.wobbleAge > 1) {
                    item.spin = item.wobble = 0;
                    item.group.rotation.x = item.group.rotation.y = 0;
                }
                moving = true;
            }
            if (item.winner && item.material) {
                const glow = item.falling || reducedMotion.matches ? .3 : .2 + .3 * (1 + Math.sin(time / 240)) / 2;
                item.material.emissive.set(colors[item.color]).multiplyScalar(glow);
                moving = moving || !reducedMotion.matches;
            }
        }
        renderer.render(scene, camera);
        frame = moving ? requestAnimationFrame(render) : 0;
        if (!moving) last = 0;
    }

    function wake() {
        if (!frame) frame = requestAnimationFrame(render);
    }

    new ResizeObserver(() => {
        const {width, height} = stage.getBoundingClientRect();
        if (!width || !height) return;
        renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
        renderer.setSize(width, height, false);
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
        wake();
    }).observe(stage);
    new MutationObserver(sync).observe(board, {subtree: true, attributes: true, attributeFilter: ['class', 'data-value']});
    stage.appendChild(canvas);
    stage.classList.add('has-3d');
    sync();
}

function roundedRect(shape, left, bottom, width, height, radius) {
    const right = left + width, top = bottom + height;
    shape.moveTo(left + radius, bottom);
    shape.lineTo(right - radius, bottom);
    shape.quadraticCurveTo(right, bottom, right, bottom + radius);
    shape.lineTo(right, top - radius);
    shape.quadraticCurveTo(right, top, right - radius, top);
    shape.lineTo(left + radius, top);
    shape.quadraticCurveTo(left, top, left, top - radius);
    shape.lineTo(left, bottom + radius);
    shape.quadraticCurveTo(left, bottom, left + radius, bottom);
    return shape;
}

function extrude(shape, depth, bevel, curveSegments = 12) {
    return new THREE.ExtrudeGeometry(shape, {depth, curveSegments, bevelEnabled: true, bevelThickness: bevel, bevelSize: bevel * .85, bevelSegments: 4});
}

// Front and back grids with the checkers' slot between them, side posts, the release bar along the
// bottom and a foot under each post, all in the same blue plastic.
function buildFrame(material) {
    const frame = new THREE.Group();
    const grid = roundedRect(new THREE.Shape(), panel.left, panel.bottom, panel.right - panel.left, panel.top - panel.bottom, .24);
    for (let row = 0; row < 6; row++) {
        for (let col = 0; col < 7; col++) {
            const hole = new THREE.Path();
            hole.absarc(col - 3, 2.5 - row, holeRadius, 0, Math.PI * 2, true);
            grid.holes.push(hole);
        }
    }
    const panelGeometry = extrude(grid, panel.depth, panel.bevel, 40);
    const front = new THREE.Mesh(panelGeometry, material);
    front.position.z = .3 - panel.depth - panel.bevel;
    const back = new THREE.Mesh(panelGeometry, material);
    back.position.z = -.3 + panel.bevel;
    frame.add(front, back);

    const post = extrude(roundedRect(new THREE.Shape(), -.21, -3.95, .42, 7.37, .14), .74, .05);
    const bar = extrude(roundedRect(new THREE.Shape(), panel.left, -3.5, panel.right - panel.left, .2, .06), .5, .03);
    // A foot seen from the side: a long base that slopes up to where the post stands on it.
    const footShape = new THREE.Shape();
    footShape.moveTo(-1.25, -4.15);
    for (const [u, v] of [[1.25, -4.15], [1.12, -4.01], [.36, -3.87], [-.36, -3.87], [-1.12, -4.01]]) footShape.lineTo(u, v);
    footShape.closePath();
    const foot = extrude(footShape, .56, .03);
    foot.rotateY(Math.PI / 2);
    foot.translate(-.28, 0, 0);
    for (const side of [-1, 1]) {
        const postMesh = new THREE.Mesh(post, material);
        postMesh.position.set(side * 4.06, 0, -.37);
        const footMesh = new THREE.Mesh(foot, material);
        footMesh.position.x = side * 4.06;
        frame.add(postMesh, footMesh);
    }
    const barMesh = new THREE.Mesh(bar, material);
    barMesh.position.z = -.25;
    frame.add(barMesh);
    frame.traverse(mesh => {
        mesh.castShadow = true;
        mesh.receiveShadow = true;
    });
    return frame;
}

// A checker: a disc with a ridged rim like the real pieces, a raised ring near the edge of each face and a
// small ring in the middle. It stands facing the viewer, so its axis is z.
function checkerGeometry() {
    const outline = new THREE.Shape();
    const step = Math.PI * 2 / piece.teeth;
    for (let tooth = 0; tooth < piece.teeth; tooth++) {
        const a = tooth * step;
        for (const [offset, radius] of [[0, piece.root], [.18, piece.radius], [.5, piece.radius], [.68, piece.root]]) {
            const angle = a + offset * step;
            const x = Math.cos(angle) * radius, y = Math.sin(angle) * radius;
            if (tooth === 0 && offset === 0) outline.moveTo(x, y);
            else outline.lineTo(x, y);
        }
    }
    outline.closePath();
    const body = new THREE.ExtrudeGeometry(outline, {depth: piece.depth, bevelEnabled: true, bevelThickness: piece.bevel, bevelSize: .016, bevelSegments: 3});
    body.translate(0, 0, -piece.depth / 2);
    const face = piece.depth / 2 + piece.bevel;
    const parts = [body];
    for (const side of [-1, 1]) {
        const rim = new THREE.TorusGeometry(.33, .03, 16, 72);
        rim.translate(0, 0, side * (face - .006));
        const center = new THREE.TorusGeometry(.14, .018, 12, 48);
        center.translate(0, 0, side * (face - .004));
        parts.push(rim, center);
    }
    return parts;
}

// A soft, blurred shadow on the table under the frame and its feet.
function contactShadow() {
    const canvas = document.createElement('canvas');
    // A round gradient, stretched into a long ellipse by the plane it is drawn on.
    canvas.width = canvas.height = 256;
    const context = canvas.getContext('2d');
    const gradient = context.createRadialGradient(128, 128, 0, 128, 128, 128);
    gradient.addColorStop(0, 'rgba(10, 20, 50, .3)');
    gradient.addColorStop(.55, 'rgba(10, 20, 50, .13)');
    gradient.addColorStop(1, 'rgba(10, 20, 50, 0)');
    context.fillStyle = gradient;
    context.fillRect(0, 0, 256, 256);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    const shadow = new THREE.Mesh(new THREE.PlaneGeometry(10.5, 3), new THREE.MeshBasicMaterial({map: texture, transparent: true, depthWrite: false, toneMapped: false}));
    shadow.rotation.x = -Math.PI / 2;
    shadow.position.y = -4.14;
    shadow.renderOrder = -1;
    return shadow;
}

// A soft white studio for reflections: a light grey room with broad overhead and side softboxes.
function studioEnvironment(renderer) {
    const room = new THREE.Scene();
    room.add(new THREE.Mesh(new THREE.BoxGeometry(14, 14, 14), new THREE.MeshBasicMaterial({color: 0xcfd2d8, side: THREE.BackSide})));
    for (const [intensity, position, width, height] of [[5, [-3, 5, 5], 6, 2], [2.4, [5, 1, 4], 2, 5], [1.6, [0, -4, 6], 6, 1.5], [2, [-5, 0, -2], 2, 4]]) {
        const box = new THREE.Mesh(new THREE.PlaneGeometry(width, height), new THREE.MeshBasicMaterial({color: new THREE.Color(0xffffff).multiplyScalar(intensity), side: THREE.DoubleSide}));
        box.position.set(...position);
        box.lookAt(0, 0, 0);
        room.add(box);
    }
    const generator = new THREE.PMREMGenerator(renderer);
    const environment = generator.fromScene(room, .03).texture;
    generator.dispose();
    return environment;
}
