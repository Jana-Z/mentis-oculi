#!/usr/bin/env python3
"""Build the static data bundle for the "Can you beat the AI?" sliding-puzzle game.

Reads puzzle instances from ../../../datasets and recorded model responses from
../../../results, selects a handful of instances (one per difficulty level),
computes whether each model's answer actually solves the puzzle, copies the
needed images into docs/static/game/puzzles/, and writes game_data.json.

Run from anywhere:  python3 docs/static/game/build_game_data.py
"""
import json
import os
import shutil
import subprocess
from pathlib import Path

# ---------------------------------------------------------------- paths
HERE = Path(__file__).resolve().parent                 # docs/static/game
REPO = HERE.parents[2]                                 # repo root
DATASETS = REPO / "datasets" / "sliding-puzzle" / "output"
RESULTS = REPO / "results" / "responses"
OUT_DIR = HERE / "puzzles"
OUT_JSON = HERE / "game_data.json"
OUT_JS = HERE / "game_data.js"

# Models to pit the user against. `variant` is the response sub-folder.
MODELS = [
    {"key": "gemini-3-pro", "label": "Gemini 3 Pro", "dir": "gemini-3-pro-preview", "variant": "simple", "umm": False},
    {"key": "gpt-5.1", "label": "GPT-5.1", "dir": "gpt-5.1", "variant": "simple", "umm": False},
    {"key": "emu-3.5", "label": "EMU 3.5", "dir": "emu3.5", "variant": "generate_images", "umm": True},
]

LEVELS = ["01", "02", "03", "04", "05"]
CANDIDATE_IDS = range(1, 31)   # puzzles 1..30 have recorded model responses per level

# EMU's generate_images run references PNGs relative to each level's response
# folder. Those files are gitignored / not in the repo, so point EMU_IMAGES_ROOT
# at wherever they actually live (env var). The resolver also tries the in-repo
# location in case they've been dropped there.
EMU_VARIANT_DIR = RESULTS / "emu3.5" / "generate_images" / "sliding-puzzle"
EMU_IMAGES_ROOT = os.environ.get("EMU_IMAGES_ROOT", "")


def resolve_emu_image(level, rel):
    """Find an EMU-generated image on disk given its JSON-relative path."""
    bases = [EMU_VARIANT_DIR / f"level_{level}"]
    if EMU_IMAGES_ROOT:
        root = Path(EMU_IMAGES_ROOT).expanduser()
        bases += [
            root / f"level_{level}",
            root / "sliding-puzzle" / f"level_{level}",
            root / "emu3.5" / "generate_images" / "sliding-puzzle" / f"level_{level}",
            root,
        ]
    for b in bases:
        cand = b / rel
        if cand.is_file():
            return cand
    return None


def bundle_emu_image(src, dst_dir, k):
    """Copy an EMU image into the bundle, downscaled to a small JPEG (they're
    720px photographic PNGs shown ~96px tall). Falls back to a raw copy."""
    if shutil.which("sips"):
        out = dst_dir / f"emu_{k}.jpg"
        subprocess.run(
            ["sips", "-Z", "360", "-s", "format", "jpeg", "-s", "formatOptions", "80",
             str(src), "--out", str(out)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
        if out.is_file():
            return out.name
    out = dst_dir / f"emu_{k}{src.suffix.lower()}"
    shutil.copy(src, out)
    return out.name

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
            emu = per_model.get("emu-3.5", {})
            emu_has_images = 1 if emu.get("generated_images") else 0
            # Feature the UMM's generated images first (so every level shows one),
            # then prefer instances where all models answered and the outcome is
            # interesting (some wrong, at least one right), tie-break lowest id.
            score = (emu_has_images, all_answered, nonempty, wrong, any_right, -i)
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

        # Copy EMU's generated images (if we can find them) into the bundle and
        # rewrite the paths to static/ so the page can display them directly.
        emu = per_model.get("emu-3.5")
        if emu:
            copied = []
            for k, rel in enumerate(emu.get("generated_images", [])):
                src = resolve_emu_image(lvl, rel)
                if src is None:
                    continue
                out_name = bundle_emu_image(src, dst, k)
                copied.append(f"static/game/puzzles/level{lvl}_{pid}/{out_name}")
            emu["generated_images"] = copied

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
        n_emu = len((per_model.get("emu-3.5") or {}).get("generated_images", []))
        print(f"level_{lvl}: chose {pid} ({meta['num_solution_moves']} moves) -> {summary} | emu_imgs={n_emu}")

    json.dump(game, open(OUT_JSON, "w"), indent=2)
    # Also emit a JS global so the page works when opened via file:// (where
    # fetch() is blocked by the browser's same-origin policy).
    with open(OUT_JS, "w") as f:
        f.write("window.GAME_DATA = ")
        json.dump(game, f, indent=2)
        f.write(";\n")
    print(f"\nWrote {OUT_JSON} and {OUT_JS} with {len(game['puzzles'])} puzzles.")


if __name__ == "__main__":
    main()
