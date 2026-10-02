#!/usr/bin/env python3
"""Build the static data bundle for the "Can you beat the AI?" sliding-puzzle game.

Reads puzzle instances from ../../../datasets and recorded model responses from
../../../results, selects one instance per difficulty level, computes whether each
model's answer actually solves the puzzle, copies the needed images (including
models' generated images) into docs/static/game/puzzles/, and writes the bundle.

Model-generated image PNGs are gitignored / not in this repo. Point them in via:
    RESULTS_IMAGES_ROOT=/path/to/mentis-oculi/results/responses \\
        python3 docs/static/game/build_game_data.py

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

# `primary` models are the headline contest (always shown). `secondary` models
# appear behind a "show more" dropdown. `variant` is the response sub-folder;
# generate_images variants also carry the model's own generated images.
MODELS = [
    {"key": "gemini-3-pro", "label": "Gemini 3 Pro", "dir": "gemini-3-pro-preview", "variant": "simple", "umm": False, "primary": True},
    {"key": "gpt-5.1", "label": "GPT-5.1", "dir": "gpt-5.1", "variant": "simple", "umm": False, "primary": True},
    {"key": "emu-3.5", "label": "EMU 3.5", "dir": "emu3.5", "variant": "generate_images", "umm": True, "primary": True},
    {"key": "gemini-2.5-flash", "label": "Gemini 2.5 Flash", "dir": "gemini-2.5-flash", "variant": "simple", "umm": False, "primary": False},
    {"key": "qwen3-vl", "label": "Qwen3-VL", "dir": "qwen3-vl-235b-a22b-thinking", "variant": "simple", "umm": False, "primary": False},
    {"key": "mirage", "label": "Mirage", "dir": "mirage", "variant": "simple", "umm": False, "primary": False},
    {"key": "gemini-2.5-flash-image", "label": "Gemini 2.5 Flash Image", "dir": "gemini-2.5-flash-image", "variant": "generate_images", "umm": True, "primary": False},
    {"key": "gemini-3-pro-image", "label": "Gemini 3 Pro Image", "dir": "gemini-3-pro-image-preview", "variant": "generate_images", "umm": True, "primary": False},
]
PRIMARY_KEYS = [m["key"] for m in MODELS if m["primary"]]

LEVELS = ["01", "02", "03", "04", "05"]
CANDIDATE_IDS = range(1, 31)   # puzzles 1..30 have recorded model responses per level
MAX_IMAGES = 6                 # cap generated images shown per model per puzzle

# Where model-generated image PNGs live (responses root of the sibling repo).
IMAGES_ROOT = os.environ.get("RESULTS_IMAGES_ROOT", "")


def resolve_image(model, level, rel):
    """Find a model-generated image on disk given its JSON-relative path."""
    subpath = Path(model["dir"]) / model["variant"] / "sliding-puzzle" / f"level_{level}" / rel
    bases = [RESULTS / subpath]
    if IMAGES_ROOT:
        bases.append(Path(IMAGES_ROOT).expanduser() / subpath)
    for b in bases:
        if b.is_file():
            return b
    return None


def bundle_image(src, dst_dir, prefix, k):
    """Copy a generated image into the bundle, downscaled to a small JPEG (they're
    ~720px photographic PNGs shown ~96px tall). Falls back to a raw copy."""
    if shutil.which("sips"):
        out = dst_dir / f"{prefix}_{k}.jpg"
        subprocess.run(
            ["sips", "-Z", "360", "-s", "format", "jpeg", "-s", "formatOptions", "80",
             str(src), "--out", str(out)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
        if out.is_file():
            return out.name
    out = dst_dir / f"{prefix}_{k}{src.suffix.lower()}"
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

    responses = {lvl: {m["key"]: load_responses(m, lvl) for m in MODELS} for lvl in LEVELS}

    game = {
        "task": "sliding-puzzle",
        "models": [{"key": m["key"], "label": m["label"], "umm": m["umm"], "primary": m["primary"]} for m in MODELS],
        "puzzles": [],
    }

    for lvl in LEVELS:
        # Selection is driven by the PRIMARY models (the headline contest). We want
        # instances where every primary model answered, the UMM produced images (so
        # every level shows one), and the outcome is interesting (some wrong, at
        # least one right), tie-broken by lowest id.
        candidates = []
        for i in CANDIDATE_IDS:
            pid = f"puzzle_{i:04d}"
            meta = puzzle_meta(lvl, pid)
            if meta is None:
                continue
            per_model = {}
            for m in MODELS:
                r = responses[lvl][m["key"]].get(pid)
                if not r:
                    continue
                ans = (r.get("output_parsed") or {}).get("answer", "") or ""
                per_model[m["key"]] = {
                    "answer": ans,
                    "correct": bool(ans) and solves(meta["initial_state"], meta["target_state"], ans),
                    "reasoning": r.get("output_text", "") or "",
                    "generated_images": r.get("generated_images", []) or [],
                }

            prim = [per_model[k] for k in PRIMARY_KEYS if k in per_model]
            if len(prim) < len(PRIMARY_KEYS):
                continue  # need all primary models to have responded
            nonempty = sum(1 for p in prim if p["answer"])
            wrong = sum(1 for p in prim if not p["correct"])
            any_right = any(p["correct"] for p in prim)
            all_answered = nonempty == len(PRIMARY_KEYS)
            emu_has_images = 1 if per_model.get("emu-3.5", {}).get("generated_images") else 0
            score = (emu_has_images, all_answered, nonempty, wrong, any_right, -i)
            candidates.append((score, pid, meta, per_model))

        if not candidates:
            print(f"level_{lvl}: no fully-covered candidate found, skipping")
            continue

        _, pid, meta, per_model = max(candidates, key=lambda t: t[0])
        dst = OUT_DIR / f"level{lvl}_{pid}"
        dst.mkdir()
        for img in ("target.png", "initial.png"):
            src = DATASETS / f"level_{lvl}" / pid / img
            if src.exists():
                shutil.copy(src, dst / img)

        # Copy each model's generated images into the bundle and rewrite the paths
        # to static/ so the page can display them directly.
        for m in MODELS:
            entry = per_model.get(m["key"])
            if not entry:
                continue
            copied = []
            for k, rel in enumerate(entry.get("generated_images", [])[:MAX_IMAGES]):
                src = resolve_image(m, lvl, rel)
                if src is None:
                    continue
                out_name = bundle_image(src, dst, m["key"], k)
                copied.append(f"static/game/puzzles/level{lvl}_{pid}/{out_name}")
            entry["generated_images"] = copied

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
        summary = ", ".join(f"{k}={'OK' if per_model[k]['correct'] else 'X'}" for k in PRIMARY_KEYS if k in per_model)
        n_imgs = sum(len(v.get("generated_images", [])) for v in per_model.values())
        print(f"level_{lvl}: chose {pid} ({meta['num_solution_moves']} moves) -> {summary} | gen_imgs={n_imgs}")

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
