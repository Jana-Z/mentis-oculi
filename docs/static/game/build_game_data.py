#!/usr/bin/env python3
"""Build the static data bundle for the "Can you beat the AI?" sliding-puzzle game.

Reads puzzle instances from ../../../datasets and recorded model responses from
../../../results, selects a handful of instances (one per difficulty level),
computes whether each model's answer actually solves the puzzle, copies the
needed images into docs/static/game/puzzles/, and writes game_data.json.

Run from anywhere:  python3 docs/static/game/build_game_data.py
"""
import json
import shutil
from pathlib import Path

# ---------------------------------------------------------------- paths
HERE = Path(__file__).resolve().parent                 # docs/static/game
REPO = HERE.parents[2]                                 # repo root
DATASETS = REPO / "datasets" / "sliding-puzzle" / "output"
RESULTS = REPO / "results" / "responses"
OUT_DIR = HERE / "puzzles"
OUT_JSON = HERE / "game_data.json"

# Models to pit the user against. `variant` is the response sub-folder.
MODELS = [
    {"key": "gemini-3-pro", "label": "Gemini 3 Pro", "dir": "gemini-3-pro-preview", "variant": "simple", "umm": False},
    {"key": "gpt-5.1", "label": "GPT-5.1", "dir": "gpt-5.1", "variant": "simple", "umm": False},
    {"key": "emu-3.5", "label": "EMU 3.5", "dir": "emu3.5", "variant": "generate_images", "umm": True},
]

LEVELS = ["01", "02", "03", "04", "05"]
CANDIDATE_IDS = range(1, 16)   # puzzles 1..15 have recorded responses (30 per level)

# ---------------------------------------------------------------- helpers
DELTA = {"up": (-1, 0), "down": (1, 0), "left": (0, -1), "right": (0, 1)}


def find_blank(state):
    for r, row in enumerate(state):
        for c, v in enumerate(row):
            if v == -1:
                return r, c
    return None


def apply_moves(initial, moves):
    """Apply a whitespace-separated move string to `initial`; return final grid.

    A move slides the blank in the named direction (swaps it with the neighbour).
    Out-of-bounds moves are skipped (lenient). Unknown tokens are ignored."""
    state = [row[:] for row in initial]
    n = len(state)
    r, c = find_blank(state)
    for tok in str(moves).replace(",", " ").split():
        tok = tok.strip().lower()
        if tok not in DELTA:
            continue
        dr, dc = DELTA[tok]
        nr, nc = r + dr, c + dc
        if 0 <= nr < n and 0 <= nc < len(state[0]):
            state[r][c], state[nr][nc] = state[nr][nc], state[r][c]
            r, c = nr, nc
    return state


def solves(initial, target, moves):
    return apply_moves(initial, moves) == target


def load_responses(model, level):
    f = RESULTS / model["dir"] / model["variant"] / "sliding-puzzle" / f"level_{level}" / "responses_0.json"
    if not f.exists():
        return {}
    data = json.load(open(f))
    out = {}
    for r in data.get("responses", []):
        pid = Path(r["puzzle_dir"]).name  # e.g. puzzle_0007
        out[pid] = r
    return out


def puzzle_meta(level, pid):
    f = DATASETS / f"level_{level}" / pid / "metadata.json"
    return json.load(open(f)) if f.exists() else None


# ---------------------------------------------------------------- build
def main():
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True)

    # Pre-load model responses per level.
    responses = {lvl: {m["key"]: load_responses(m, lvl) for m in MODELS} for lvl in LEVELS}

    game = {"task": "sliding-puzzle", "models": [{"key": m["key"], "label": m["label"], "umm": m["umm"]} for m in MODELS], "puzzles": []}

    for lvl in LEVELS:
        # Pick the most compelling instance for this level. We want puzzles where
        # every model actually *attempted* an answer (non-empty move sequence) so the
        # reveal shows confident-but-wrong AI reasoning rather than blank responses.
        # Score = (all three answered, number wrong, at least one model right),
        # tie-broken by lowest id. "At least one right" keeps it a real contest.
        candidates = []
        for i in CANDIDATE_IDS:
            pid = f"puzzle_{i:04d}"
            meta = puzzle_meta(lvl, pid)
            if meta is None:
                continue
            per_model = {}
            responded = 0
            nonempty = 0
            wrong = 0
            any_right = False
            for m in MODELS:
                r = responses[lvl][m["key"]].get(pid)
                if not r:
                    continue
                responded += 1
                ans = (r.get("output_parsed") or {}).get("answer", "") or ""
                if ans:
                    nonempty += 1
                ok = bool(ans) and solves(meta["initial_state"], meta["target_state"], ans)
                any_right = any_right or ok
                if not ok:
                    wrong += 1
                per_model[m["key"]] = {
                    "answer": ans,
                    "correct": ok,
                    "reasoning": r.get("output_text", "") or "",
                    "generated_images": r.get("generated_images", []) or [],
                }
            if responded < len(MODELS):
                continue
            all_answered = nonempty == len(MODELS)
            score = (all_answered, nonempty, wrong, any_right, -i)
            candidates.append((score, pid, meta, per_model))

        if not candidates:
            print(f"level_{lvl}: no fully-covered candidate found, skipping")
            continue

        _, pid, meta, per_model = max(candidates, key=lambda t: t[0])
        # Copy the two reference images for this instance.
        dst = OUT_DIR / f"level{lvl}_{pid}"
        dst.mkdir()
        for img in ("target.png", "initial.png"):
            src = DATASETS / f"level_{lvl}" / pid / img
            if src.exists():
                shutil.copy(src, dst / img)

        game["puzzles"].append({
            "id": f"level{lvl}_{pid}",
            "level": int(lvl),
            "num_moves": meta["num_solution_moves"],
            "grid_size": meta["grid_size"],
            "initial_state": meta["initial_state"],
            "target_state": meta["target_state"],
            "solution_moves": meta["solution_moves"],
            "target_image": f"static/game/puzzles/level{lvl}_{pid}/target.png",
            "models": per_model,
        })
        summary = ", ".join(f"{k}={'OK' if v['correct'] else 'X'}" for k, v in per_model.items())
        print(f"level_{lvl}: chose {pid} ({meta['num_solution_moves']} moves) -> {summary}")

    json.dump(game, open(OUT_JSON, "w"), indent=2)
    print(f"\nWrote {OUT_JSON} with {len(game['puzzles'])} puzzles.")


if __name__ == "__main__":
    main()
