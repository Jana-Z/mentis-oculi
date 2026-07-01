/* MentisOculi "Can you beat the AI?" sliding-puzzle game.
 * Fully client-side: reads static/game/game_data.json (puzzles + recorded model
 * answers), lets the user solve each puzzle by tapping tiles, then reveals how
 * the frontier models did on the identical instance. */

(function () {
    "use strict";

    const DELTA = { up: [-1, 0], down: [1, 0], left: [0, -1], right: [0, 1] };

    let DATA = null;        // parsed game_data.json
    let idx = 0;            // current puzzle index
    const state = [];       // per-puzzle runtime state

    // ---- pure helpers ---------------------------------------------------
    function clone(grid) { return grid.map((r) => r.slice()); }
    function equal(a, b) { return JSON.stringify(a) === JSON.stringify(b); }

    function findBlank(grid) {
        for (let r = 0; r < grid.length; r++)
            for (let c = 0; c < grid[r].length; c++)
                if (grid[r][c] === -1) return [r, c];
        return null;
    }

    // Apply a whitespace-separated move string; returns the resulting grid.
    // Mirrors the Python build-time simulation (blank slides in named direction).
    function applyMoves(initial, moves) {
        const grid = clone(initial);
        const n = grid.length;
        let [r, c] = findBlank(grid);
        String(moves || "").replace(/,/g, " ").split(/\s+/).forEach((tok) => {
            const d = DELTA[tok.toLowerCase()];
            if (!d) return;
            const nr = r + d[0], nc = c + d[1];
            if (nr >= 0 && nr < n && nc >= 0 && nc < grid[0].length) {
                grid[r][c] = grid[nr][nc];
                grid[nr][nc] = -1;
                r = nr; c = nc;
            }
        });
        return grid;
    }

    // Map every tile value -> [row, col] of its correct slot in the solved image.
    function solvedPositions(targetState) {
        const pos = {};
        targetState.forEach((row, r) => row.forEach((v, c) => { pos[v] = [r, c]; }));
        return pos;
    }

    // ---- rendering ------------------------------------------------------
    // Build a board element from a grid. `interactive` wires up tap-to-move.
    function renderBoard(grid, puzzle, opts) {
        opts = opts || {};
        const n = grid.length;
        const pos = solvedPositions(puzzle.target_state);
        const board = document.createElement("div");
        board.className = "sp-board" + (opts.small ? " sp-board--small" : "");
        board.style.setProperty("--n", n);

        const blank = findBlank(grid);

        grid.forEach((row, r) => row.forEach((v, c) => {
            const tile = document.createElement("div");
            tile.className = "sp-tile";
            if (v === -1) {
                tile.classList.add("sp-tile--blank");
            } else {
                const [sr, sc] = pos[v];
                tile.style.backgroundImage = `url("${puzzle.target_image}")`;
                tile.style.backgroundSize = `${n * 100}% ${n * 100}%`;
                tile.style.backgroundPosition =
                    `${n > 1 ? (sc / (n - 1)) * 100 : 0}% ${n > 1 ? (sr / (n - 1)) * 100 : 0}%`;
            }

            if (opts.interactive) {
                const adj = blank && Math.abs(blank[0] - r) + Math.abs(blank[1] - c) === 1;
                if (adj && v !== -1) {
                    tile.classList.add("sp-tile--movable");
                    enableDrag(tile, board, r, c);
                }
            }
            board.appendChild(tile);
        }));
        return board;
    }

    // Drag a tile toward the empty space: it follows the pointer along the axis
    // to the gap and snaps in when dragged past halfway. A plain tap also moves it.
    function enableDrag(tile, board, r, c) {
        tile.addEventListener("pointerdown", (e) => {
            if (state[idx].submitted) return;
            const blankEl = board.querySelector(".sp-tile--blank");
            if (!blankEl) return;
            e.preventDefault();

            const tr = tile.getBoundingClientRect();
            const br = blankEl.getBoundingClientRect();
            const vx = br.left - tr.left, vy = br.top - tr.top; // vector into the gap
            const vlen2 = vx * vx + vy * vy || 1;
            const startX = e.clientX, startY = e.clientY;
            let moved = 0;

            try { tile.setPointerCapture(e.pointerId); } catch (_) { /* capture optional */ }
            tile.classList.add("sp-tile--dragging");

            const onMove = (ev) => {
                const dx = ev.clientX - startX, dy = ev.clientY - startY;
                moved = Math.hypot(dx, dy);
                let f = (dx * vx + dy * vy) / vlen2;   // projection onto gap vector
                f = Math.max(0, Math.min(1, f));
                tile.style.transform = `translate(${f * vx}px, ${f * vy}px)`;
            };
            const onUp = (ev) => {
                tile.removeEventListener("pointermove", onMove);
                tile.removeEventListener("pointerup", onUp);
                tile.removeEventListener("pointercancel", onUp);
                tile.classList.remove("sp-tile--dragging");
                const dx = ev.clientX - startX, dy = ev.clientY - startY;
                const f = (dx * vx + dy * vy) / vlen2;
                if (moved < 6 || f > 0.5) move(r, c);  // tap or dragged past halfway
                else tile.style.transform = "";        // snap back
            };
            tile.addEventListener("pointermove", onMove);
            tile.addEventListener("pointerup", onUp);
            tile.addEventListener("pointercancel", onUp);
        });
    }

    function move(r, c) {
        const st = state[idx];
        if (st.submitted) return;
        const grid = st.board;
        const blank = findBlank(grid);
        if (!blank || Math.abs(blank[0] - r) + Math.abs(blank[1] - c) !== 1) return;
        grid[blank[0]][blank[1]] = grid[r][c];
        grid[r][c] = -1;
        st.moves += 1;
        if (equal(grid, DATA.puzzles[idx].target_state)) st.solved = true;
        renderPuzzle();
    }

    // ---- progress bar ---------------------------------------------------
    function renderProgress() {
        const wrap = document.getElementById("game-progress");
        wrap.innerHTML = "";
        DATA.puzzles.forEach((p, i) => {
            const dot = document.createElement("div");
            dot.className = "game-dot";
            const st = state[i];
            if (i === idx) dot.classList.add("is-current");
            if (st.submitted) dot.classList.add(st.userCorrect ? "is-solved" : "is-done");
            dot.title = `Puzzle ${i + 1}`;
            wrap.appendChild(dot);
        });
    }

    // ---- screens --------------------------------------------------------
    function renderPuzzle() {
        renderProgress();
        const app = document.getElementById("game-app");
        const puzzle = DATA.puzzles[idx];
        const st = state[idx];
        app.innerHTML = "";

        const card = document.createElement("div");
        card.className = "game-card";

        card.appendChild(el(`
            <div class="game-card-head">
                <span class="game-pill">Puzzle ${idx + 1} / ${DATA.puzzles.length}</span>
                <span class="game-pill game-pill--ghost">Level ${puzzle.level}</span>
                <span class="game-hint">Shortest solution: ${puzzle.num_moves} move${puzzle.num_moves > 1 ? "s" : ""}</span>
            </div>`));

        // The models were only shown the scrambled tiles and asked to reconstruct
        // the original coherent image — they never saw a goal. So we reveal the goal
        // only on the first puzzle (to teach the task), then hide it afterwards.
        const showGoal = idx === 0;

        card.appendChild(el(`<p class="game-instructions">Drag a tile into the empty space to slide it, and rebuild the original coherent image.${showGoal ? " This first one shows you the finished picture." : ""}</p>`));

        if (showGoal) {
            card.appendChild(el(`<div class="game-note">Heads up — from the next puzzle on, the goal is <strong>hidden</strong>. And unlike you, the models got no visual feedback: they had to solve it entirely in their &ldquo;head&rdquo;. The moving tiles here are just for ease of use.</div>`));
        }

        const boards = document.createElement("div");
        boards.className = "sp-boards";

        if (showGoal) {
            const goalCol = document.createElement("div");
            goalCol.className = "sp-col";
            goalCol.appendChild(el(`<div class="sp-col-label">Goal</div>`));
            goalCol.appendChild(renderBoard(puzzle.target_state, puzzle, { small: true }));
            boards.appendChild(goalCol);
        }

        const yourCol = document.createElement("div");
        yourCol.className = "sp-col";
        yourCol.appendChild(el(`<div class="sp-col-label">${showGoal ? "Your puzzle" : "Rebuild the image"}</div>`));
        yourCol.appendChild(renderBoard(st.board, puzzle, { interactive: !st.submitted }));
        boards.appendChild(yourCol);

        card.appendChild(boards);

        if (st.solved && !st.submitted)
            card.appendChild(el(`<div class="game-banner is-win">Solved in ${st.moves} move${st.moves === 1 ? "" : "s"}! 🎉 Now reveal the AI answers.</div>`));

        // Controls
        const controls = document.createElement("div");
        controls.className = "game-controls";
        controls.appendChild(el(`<span class="game-moves">Moves: ${st.moves}</span>`));

        const reset = button("Reset", "is-light", () => {
            st.board = clone(puzzle.initial_state);
            st.moves = 0; st.solved = false;
            renderPuzzle();
        });
        reset.disabled = st.submitted;
        controls.appendChild(reset);

        const reveal = button(st.solved ? "Reveal AI answers" : "I give up — reveal", "is-primary", () => {
            st.submitted = true;
            st.userCorrect = equal(st.board, puzzle.target_state);
            renderResult();
        });
        controls.appendChild(reveal);
        card.appendChild(controls);

        app.appendChild(card);
    }

    function verdictChip(ok) {
        return `<span class="chip ${ok ? "chip--ok" : "chip--no"}">${ok ? "✓ Solved" : "✗ Failed"}</span>`;
    }

    function miniBoardFor(grid, puzzle) {
        const holder = document.createElement("div");
        holder.appendChild(renderBoard(grid, puzzle, { small: true }));
        return holder;
    }

    function prettyAnswer(ans) {
        if (!ans) return '<em class="game-muted">(no answer)</em>';
        return `<code>${escapeHtml(ans)}</code>`;
    }

    function renderResult() {
        renderProgress();
        const app = document.getElementById("game-app");
        const puzzle = DATA.puzzles[idx];
        const st = state[idx];
        app.innerHTML = "";

        const card = document.createElement("div");
        card.className = "game-card";
        card.appendChild(el(`
            <div class="game-card-head">
                <span class="game-pill">Puzzle ${idx + 1} / ${DATA.puzzles.length}</span>
                <span class="game-pill game-pill--ghost">Level ${puzzle.level}</span>
            </div>`));

        // Reveal the original image (the goal was hidden while solving).
        const orig = document.createElement("div");
        orig.className = "result-original";
        orig.appendChild(el(`<div class="score-mini-label">The original image</div>`));
        orig.appendChild(renderBoard(puzzle.target_state, puzzle, { small: true }));
        card.appendChild(orig);

        // Scoreboard rows: You first, then models.
        const board = document.createElement("div");
        board.className = "score-list";

        board.appendChild(scoreRow({
            name: "You", ok: st.userCorrect, isYou: true,
            answerHtml: st.userCorrect
                ? `Rebuilt the original image in ${st.moves} move${st.moves === 1 ? "" : "s"}`
                : `Did not match the original image`,
        }));

        const makeRow = (m) => {
            const md = puzzle.models[m.key] || {};
            const finalGrid = applyMoves(puzzle.initial_state, md.answer || "");
            return scoreRow({
                name: m.label, ok: !!md.correct, umm: m.umm,
                answerHtml: prettyAnswer(md.answer),
                reasoning: md.reasoning,
                mini: miniBoardFor(finalGrid, puzzle),
                generated: (md.generated_images || []).filter((p) => String(p).startsWith("static/")),
                umm_note: m.umm,
            });
        };

        DATA.models.filter((m) => m.primary).forEach((m) => board.appendChild(makeRow(m)));
        card.appendChild(board);

        // Secondary models tucked behind a dropdown so the reveal stays compact.
        const secondary = DATA.models.filter((m) => !m.primary && puzzle.models[m.key]);
        if (secondary.length) {
            const det = document.createElement("details");
            det.className = "more-models";
            det.innerHTML = `<summary>Show ${secondary.length} more models</summary>`;
            const sub = document.createElement("div");
            sub.className = "score-list";
            secondary.forEach((m) => sub.appendChild(makeRow(m)));
            det.appendChild(sub);
            card.appendChild(det);
        }

        // Next / finish
        const controls = document.createElement("div");
        controls.className = "game-controls game-controls--end";
        const last = idx === DATA.puzzles.length - 1;
        controls.appendChild(button(last ? "See final score" : "Next puzzle →", "is-primary", () => {
            if (last) { renderSummary(); }
            else { idx += 1; renderPuzzle(); }
        }));
        card.appendChild(controls);

        app.appendChild(card);
        card.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function scoreRow(o) {
        const row = document.createElement("div");
        row.className = "score-row" + (o.isYou ? " score-row--you" : "");

        const head = document.createElement("div");
        head.className = "score-head";
        head.innerHTML =
            `<div class="score-name">${o.umm ? '<span class="tag-umm">UMM</span> ' : ""}${escapeHtml(o.name)}</div>` +
            `<div class="score-verdict">${verdictChip(o.ok)}</div>`;
        row.appendChild(head);

        const body = document.createElement("div");
        body.className = "score-body";
        body.innerHTML = `<div class="score-answer">${o.answerHtml}</div>`;

        if (o.mini) {
            const wrap = document.createElement("div");
            wrap.className = "score-mini";
            wrap.appendChild(el(`<div class="score-mini-label">Where it ended up</div>`));
            wrap.appendChild(o.mini);
            body.appendChild(wrap);
        }

        if (o.generated && o.generated.length) {
            const g = document.createElement("div");
            g.className = "score-generated";
            g.appendChild(el(`<div class="score-mini-label">What EMU&nbsp;3.5 drew as its solution</div>`));
            o.generated.forEach((src) => {
                const im = document.createElement("img");
                im.src = src; im.loading = "lazy"; im.alt = "EMU 3.5 generated image";
                g.appendChild(im);
            });
            body.appendChild(g);
        } else if (o.umm_note) {
            body.appendChild(el(`<p class="score-umm-note">EMU&nbsp;3.5 is a <strong>unified multimodal model</strong> that tries to <em>draw</em> its solution as an image — but for this puzzle it failed to produce one after several attempts.</p>`));
        }

        if (o.reasoning) {
            const det = document.createElement("details");
            det.className = "score-reasoning";
            det.innerHTML = `<summary>Show its reasoning</summary><pre>${escapeHtml(o.reasoning)}</pre>`;
            body.appendChild(det);
        }

        row.appendChild(body);
        return row;
    }

    function renderSummary() {
        renderProgress();
        const app = document.getElementById("game-app");
        app.innerHTML = "";
        const n = DATA.puzzles.length;

        const you = state.reduce((s, st) => s + (st.userCorrect ? 1 : 0), 0);
        const modelScore = {};
        DATA.models.forEach((m) => { modelScore[m.key] = 0; });
        DATA.puzzles.forEach((p) => DATA.models.forEach((m) => {
            if (p.models[m.key] && p.models[m.key].correct) modelScore[m.key] += 1;
        }));
        const total = DATA.models.length;
        const beaten = DATA.models.filter((m) => you > modelScore[m.key]).length;
        const tied = DATA.models.filter((m) => you === modelScore[m.key]).length;

        const card = document.createElement("div");
        card.className = "game-card game-summary";
        card.appendChild(el(`<h2 class="title is-3 has-text-centered">You solved ${you} / ${n}</h2>`));

        let verdict;
        if (beaten === total) verdict = `You beat <strong>all ${total} models</strong>! 🏆`;
        else if (beaten > 0) verdict = `You beat <strong>${beaten}</strong> of ${total} models${tied ? ` and tied ${tied}` : ""}.`;
        else if (tied) verdict = `You tied ${tied} of ${total} models.`;
        else verdict = `The models edged you out this time.`;
        card.appendChild(el(`<p class="game-verdict has-text-centered">${verdict}</p>`));

        // Final comparison shows every model, primary ones first.
        const ordered = DATA.models.slice().sort((a, b) => (b.primary === true) - (a.primary === true));
        const list = document.createElement("div");
        list.className = "summary-bars";
        list.appendChild(summaryBar("You", you, n, true));
        ordered.forEach((m) => list.appendChild(summaryBar(m.label, modelScore[m.key], n, false, m.umm)));
        card.appendChild(list);

        const controls = document.createElement("div");
        controls.className = "game-controls game-controls--end";
        controls.appendChild(button("Play again", "is-light", () => { initState(); idx = 0; renderPuzzle(); }));
        const back = document.createElement("a");
        back.className = "button is-primary";
        back.href = "index.html";
        back.textContent = "Read the paper";
        controls.appendChild(back);
        card.appendChild(controls);

        app.appendChild(card);
        card.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    function summaryBar(name, score, total, isYou, umm) {
        const row = el(`<div class="summary-row ${isYou ? "is-you" : ""}"></div>`);
        row.appendChild(el(`<div class="summary-name">${umm ? '<span class="tag-umm">UMM</span> ' : ""}${escapeHtml(name)}</div>`));
        const track = el(`<div class="summary-track"></div>`);
        const fill = el(`<div class="summary-fill"></div>`);
        fill.style.width = `${(score / total) * 100}%`;
        track.appendChild(fill);
        row.appendChild(track);
        row.appendChild(el(`<div class="summary-score">${score}/${total}</div>`));
        return row;
    }

    // ---- tiny DOM utils -------------------------------------------------
    function el(html) {
        const t = document.createElement("template");
        t.innerHTML = html.trim();
        return t.content.firstElementChild;
    }
    function button(label, cls, onClick) {
        const b = document.createElement("button");
        b.className = `button ${cls} game-btn`;
        b.textContent = label;
        b.addEventListener("click", onClick);
        return b;
    }
    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, (ch) => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
        }[ch]));
    }

    // ---- bootstrap ------------------------------------------------------
    function initState() {
        state.length = 0;
        DATA.puzzles.forEach((p) => state.push({
            board: clone(p.initial_state),
            moves: 0,
            solved: equal(p.initial_state, p.target_state),
            submitted: false,
            userCorrect: false,
        }));
    }

    function start(data) {
        DATA = data;
        if (!DATA || !DATA.puzzles || !DATA.puzzles.length) throw new Error("no puzzles");
        initState();
        renderPuzzle();
    }

    // Prefer the inlined global (works over file://); fall back to fetch (HTTP).
    if (window.GAME_DATA) {
        try { start(window.GAME_DATA); }
        catch (err) { showLoadError(err); }
    } else {
        fetch("static/game/game_data.json")
            .then((r) => r.json())
            .then(start)
            .catch(showLoadError);
    }

    function showLoadError(err) {
        document.getElementById("game-app").innerHTML =
            `<div class="notification is-warning">Could not load the puzzles. (${escapeHtml(err.message)})</div>`;
    }
})();
