"""Paper Folding Puzzle Generator
--------------------------------
Generates paper folding puzzles similar to those in IQ tests.

For each puzzle:
1. Start with a square paper on an n×n grid
2. Apply 3-5 random folds (horizontal, vertical, or 45° diagonal)
3. Punch a hole through the folded layers
4. Generate visual chain-of-thought showing the unfolding process
5. Create combined views and metadata

Output Structure:
----------------
output/
├── dataset_metadata.json
├── puzzle_0001/
│   ├── question.png          # All folds + hole punch
│   ├── silhouette.png        # Final unfolded result
│   ├── combined.png          # Question + answer in one frame
│   ├── cot_00.png            # First unfold
│   ├── cot_01.png            # Second unfold
│   ├── cot_XX.png            # ... (one per fold)
│   ├── wrong_0.png, wrong_1.png, wrong_2.png, wrong_3.png  # Wrong answer choices
│   └── metadata.json
└── ...

Dependencies
------------
* matplotlib – for plotting
* shapely – for geometric operations
* pillow – for image manipulation
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import shutil
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt
from PIL import Image
from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.ops import split, unary_union


# ──────────────────────────────────────────────────────────────────────────────
# Style guide constants (shared palette)
# ──────────────────────────────────────────────────────────────────────────────
CERULEAN = "#0090C1"       # Primary brand
RASPBERRY = "#E85D75"      # Highlight / goal
AQUAMARINE = "#2EC4B6"     # Movable or secondary (background hue)
SUNSHINE = "#FFD670"       # Helper / reference
MIDNIGHT = "#1B263B"       # Outlines / text
CANVAS_SIZE = (6, 6)        # 6×6 inches

# ──────────────────────────────────────────────────────────────────────────────
# Helper functions
# ──────────────────────────────────────────────────────────────────────────────

def _reflect_point(pt: Tuple[float, float], axis: Dict) -> Tuple[float, float]:
    """Reflect a single point across the given fold axis."""
    x, y = pt
    kind = axis["type"]
    size = axis["size"]
    c = axis["offset"]

    if kind == "horizontal":
        return (x, 2 * c - y)

    if kind == "vertical":
        return (2 * c - x, y)

    if kind == "diag_pos":  # y = x + c
        return (y - c, x + c)

    if kind == "diag_neg":  # y = −x + c
        return (c - y, c - x)

    raise ValueError(f"Unknown axis type: {kind}")


def _reflect_linestring(ls: LineString, axis: Dict) -> LineString:
    """Return a reflected copy of *ls* across *axis*."""
    return LineString([_reflect_point(pt, axis) for pt in ls.coords])


def _reflect_polygon(poly: Polygon, axis: Dict) -> Polygon:
    """Reflect an entire polygon across the axis."""
    reflected_coords = [_reflect_point(pt, axis) for pt in poly.exterior.coords]
    return Polygon(reflected_coords)


def _make_intersection(ls: LineString, poly: Polygon) -> List:
    intersection = ls.intersection(poly)
    if not intersection.is_empty:
        if isinstance(intersection, LineString):
            return [intersection]
        elif isinstance(intersection, MultiLineString):
            return list(intersection.geoms)
    return []


def _generate_point(poly: Polygon, size: float, *, edges: List[LineString] | None = None, points: List[Point] | None = None, min_d: float = 0.2, max_attempts: int = 1000) -> Point:
    if edges == None:
        coords = list(poly.exterior.coords)
        edges = [LineString([coords[i], coords[i+1]]) for i in range(len(coords) - 1)]
    attempts = 0
    while attempts < max_attempts:
        attempts += 1
        candidate = Point(random.uniform(0, size), random.uniform(0, size))
        min_distance = min(e.distance(candidate) for e in edges)
        if points:
            min_distance_points = min(p.distance(candidate) for p in points)
            min_distance = min(min_distance, min_distance_points)
        if poly.contains(candidate) and min_distance >= min_d:
            return candidate
    # Fallback: relax constraint slightly if we can't find a point
    while True:
        candidate = Point(random.uniform(0, size), random.uniform(0, size))
        min_distance = min(e.distance(candidate) for e in edges)
        if points:
            min_distance_points = min(p.distance(candidate) for p in points)
            min_distance = min(min_distance, min_distance_points)
        if poly.contains(candidate) and min_distance >= min_d * 0.5:
            return candidate


def _is_sufficiently_different(wrong_holes: List[Point], correct_holes: List[Point], min_difference: float = 0.3) -> bool:
    """Check if wrong answer has at least one hole sufficiently far from all correct holes.
    
    Args:
        wrong_holes: List of holes in the wrong answer
        correct_holes: List of holes in the correct answer
        min_difference: Minimum distance required for at least one hole
        
    Returns:
        True if the wrong answer is sufficiently different from the correct answer
    """
    if not wrong_holes or not correct_holes:
        return True
    
    # Different number of holes is a strong indicator of difference
    # But we still need to check distances to ensure visual distinguishability
    
    # Check if at least one wrong hole is far from all correct holes
    has_far_wrong_hole = False
    for wrong_hole in wrong_holes:
        min_dist_to_correct = min(wrong_hole.distance(correct_hole) for correct_hole in correct_holes)
        if min_dist_to_correct >= min_difference:
            has_far_wrong_hole = True
            break
    
    # Also check if at least one correct hole is far from all wrong holes (missing hole case)
    has_far_correct_hole = False
    for correct_hole in correct_holes:
        min_dist_to_wrong = min(correct_hole.distance(wrong_hole) for wrong_hole in wrong_holes)
        if min_dist_to_wrong >= min_difference:
            has_far_correct_hole = True
            break
    
    return has_far_wrong_hole or has_far_correct_hole


def _are_answer_sets_distinguishable(answer_hole_sets: List[List[Point]], min_difference: float = 0.3) -> bool:
    """Check if all answer choices are mutually distinguishable.
    
    Args:
        answer_hole_sets: List of hole sets (each set is a list of Point objects)
        min_difference: Minimum distance required between any two answers
        
    Returns:
        True if all answers are sufficiently different from each other
    """
    if len(answer_hole_sets) < 2:
        return True
    
    # Check each pair of answers
    for i in range(len(answer_hole_sets)):
        for j in range(i + 1, len(answer_hole_sets)):
            if not _is_sufficiently_different(answer_hole_sets[i], answer_hole_sets[j], min_difference):
                return False
    
    return True


def _axis_geometry(axis: Dict) -> LineString:
    """Return a Shapely *LineString* representing the fold axis (long enough)."""
    kind = axis["type"]
    size = axis["size"]
    c = axis["offset"]

    if kind == "horizontal":
        return LineString([(0, c), (size, c)])

    if kind == "vertical":
        return LineString([(c, 0), (c, size)])

    if kind == "diag_pos":  # y = x + c
        return LineString([(-size, -size + c), (2 * size, 2 * size + c)])

    if kind == "diag_neg":  # y = −x + c
        return LineString([(-size, size + c), (2 * size, -2 * size + c)])

    raise ValueError(f"Unknown axis type: {kind}")


def _draw_fold_axis(ax, axis: Dict, *, show_direction: bool = False) -> None:
    """Disabled per updated style: no fold axis overlay."""
    return


# ──────────────────────────────────────────────────────────────────────────────
# Core algorithm
# ──────────────────────────────────────────────────────────────────────────────

def generate_sequence(
    n: int = 3,
    min_steps: int = 3,
    max_steps: int = 5,
    seed: int | None = None,
    *,
    save_dir: str | Path = "output",
    puzzle_id: int = 1,
    min_distinguishable_distance: float = 0.3,
) -> Dict:
    """Generate folding & unfolding sequence with internal edge rendering.
    
    Returns metadata dictionary for this puzzle.
    """

    # ── setup ────────────────────────────────────────────────────────────────
    if seed is not None:
        random.seed(seed)
    size: float = float(n)
    save_path = Path(save_dir)
    save_path.mkdir(parents=True, exist_ok=True)
    
    # Create temp directory for intermediate files
    temp_dir = save_path / "temp"
    temp_dir.mkdir(exist_ok=True)

    square = Polygon([(0, 0), (size, 0), (size, size), (0, size)])

    shapes: List[Polygon] = [square]
    edges_history: List[List[LineString]] = [[
        LineString([(0, 0), (size, 0)]),
        LineString([(size, 0), (size, size)]),
        LineString([(size, size), (0, size)]),
        LineString([(0, size), (0, 0)]),
    ]]
    axes: List[Dict] = []

    # ── choose folds ─────────────────────────────────────────────────────────
    num_folds = random.randint(min_steps, max_steps)
    grid_lines = [float(i) for i in range(1, n)]
    diag_pos_lines = [float(i) for i in range(1 - n, n)]
    diag_neg_lines = [float(i) for i in range(1, 2 * n)]

    centre_pt = Point(size / 2, size / 2)
    current_poly: Polygon = square
    current_edges: List[LineString] = edges_history[0]

    # ── folding loop ─────────────────────────────────────────────────────────
    while len(axes) < num_folds:
        axis_type = random.choice(["horizontal", "vertical", "diag_pos", "diag_neg",])

        if axis_type in ("horizontal", "vertical"):
            coord = random.choice(grid_lines)
            axis = {"type": axis_type, "offset": coord, "size": size}
        elif axis_type == "diag_pos":
            coord = random.choice(diag_pos_lines)
            axis = {"type": axis_type, "offset": coord, "size": size}
        elif axis_type == "diag_neg":
            coord = random.choice(diag_neg_lines)
            axis = {"type": axis_type, "offset": coord, "size": size}

        axis_line = _axis_geometry(axis)
        pieces = list(split(current_poly, axis_line).geoms)
        if len(pieces) != 2:
            continue  # degenerate split, retry

        # Identify stationary & moving halves
        if pieces[0].contains(centre_pt):
            stationary, to_fold = pieces[0], pieces[1]
        elif pieces[1].contains(centre_pt):
            stationary, to_fold = pieces[1], pieces[0]
        else:
            stationary, to_fold = (
                (pieces[0], pieces[1])
                if pieces[0].distance(centre_pt) <= pieces[1].distance(centre_pt)
                else (pieces[1], pieces[0])
            )
        new_poly = unary_union([stationary, _reflect_polygon(to_fold, axis)])

        # ── edge transformation ────────────────────────────────────────────
        new_edges: List[LineString] = []
        for e in current_edges:
            new_edges.extend(_make_intersection(e, new_poly))
            reflect_e = _reflect_linestring(e, axis)
            new_edges.extend(_make_intersection(reflect_e, new_poly))
        new_edges.extend(_make_intersection(axis_line, new_poly))

        # Update state
        current_edges = new_edges
        current_poly = new_poly
        shapes.append(current_poly)
        edges_history.append(current_edges)
        axes.append(axis)

    # ── rendering fold steps ─────────────────────────────────────────────────
    for i in range(1, len(shapes)):
        # Draw fold state and overlay the corresponding fold axis for context
        _plot_state(square, shapes[i], edges_history[i], [], temp_dir / f"step_{i:02d}_fold.png", fold_axis=axes[i-1])

    # ── punch hole ───────────────────────────────────────────────────────────
    hole_point = _generate_point(current_poly, size, edges=edges_history[-1])
    _plot_state(square, shapes[-1], edges_history[-1], [hole_point], temp_dir / f"step_{len(shapes):02d}_hole.png",)

    # ── unfolding (chain of thought) ─────────────────────────────────────────
    holes: List[Point] = [hole_point]
    wrong_holes: List[List[Point]] = []
    
    # Store CoT images
    cot_images = []

    if num_folds == 1:
        # Generate 4 wrong answers that are distinguishable from correct and from each other
        max_set_retries = 50
        max_retries = 100
        
        for set_attempt in range(max_set_retries):
            temp_wrong_holes = []
            
            # Wrong answer 1: correct holes + extra hole
            for _ in range(max_retries):
                candidate = _generate_point(shapes[1], size, points=holes)
                candidate_holes = [i for i in holes] + [candidate]
                if _is_sufficiently_different(candidate_holes, holes, min_distinguishable_distance):
                    temp_wrong_holes.append(candidate_holes)
                    break
            else:
                candidate = _generate_point(shapes[1], size, points=holes)
                temp_wrong_holes.append([i for i in holes] + [candidate])  # fallback
            
            # Wrong answer 2: correct holes + different extra hole
            for _ in range(max_retries):
                candidate = _generate_point(shapes[1], size, points=holes)
                candidate_holes = [i for i in holes] + [candidate]
                all_answers = [holes] + temp_wrong_holes + [candidate_holes]
                if (_is_sufficiently_different(candidate_holes, holes, min_distinguishable_distance) and
                    _are_answer_sets_distinguishable(all_answers, min_distinguishable_distance)):
                    temp_wrong_holes.append(candidate_holes)
                    break
            else:
                candidate = _generate_point(shapes[1], size, points=holes)
                temp_wrong_holes.append([i for i in holes] + [candidate])  # fallback
            
            # Wrong answer 3: only one different hole
            for _ in range(max_retries):
                candidate = _generate_point(shapes[1], size, points=holes)
                candidate_holes = [candidate]
                all_answers = [holes] + temp_wrong_holes + [candidate_holes]
                if (_is_sufficiently_different(candidate_holes, holes, min_distinguishable_distance) and
                    _are_answer_sets_distinguishable(all_answers, min_distinguishable_distance)):
                    temp_wrong_holes.append(candidate_holes)
                    break
            else:
                candidate = _generate_point(shapes[1], size, points=holes)
                temp_wrong_holes.append([candidate])  # fallback
            
            # Wrong answer 4: another single different hole
            for _ in range(max_retries):
                candidate = _generate_point(shapes[1], size, points=holes)
                candidate_holes = [candidate]
                all_answers = [holes] + temp_wrong_holes + [candidate_holes]
                if (_is_sufficiently_different(candidate_holes, holes, min_distinguishable_distance) and
                    _are_answer_sets_distinguishable(all_answers, min_distinguishable_distance)):
                    temp_wrong_holes.append(candidate_holes)
                    break
            else:
                candidate = _generate_point(shapes[1], size, points=holes)
                temp_wrong_holes.append([candidate])  # fallback
            
            # Final validation: check if all answers are mutually distinguishable
            all_final_answers = [holes] + temp_wrong_holes
            if _are_answer_sets_distinguishable(all_final_answers, min_distinguishable_distance):
                wrong_holes = temp_wrong_holes
                break
        else:
            # If we couldn't generate a good set, use the last attempt
            wrong_holes = temp_wrong_holes

    for idx, axis in enumerate(reversed(axes), start=1):
        shape_to_plot = shapes[-(idx + 1)]
        edges_to_plot = edges_history[-(idx + 1)]

        new_holes: List[Point] = []
        seen: set[Tuple[float, float]] = set()
        for h in holes:
            if shape_to_plot.contains(h):
                key = (round(h.x, 6), round(h.y, 6))
                if key not in seen:
                    seen.add(key)
                    new_holes.append(h)
            h_ref = Point(*_reflect_point((h.x, h.y), axis))
            if shape_to_plot.contains(h_ref):
                key = (round(h_ref.x, 6), round(h_ref.y, 6))
                if key not in seen:
                    seen.add(key)
                    new_holes.append(h_ref)
        holes = new_holes
        
        # Save CoT image
        cot_filename = f"cot_{idx-1:02d}.png"
        _plot_state(square, shape_to_plot, edges_to_plot, holes, save_path / cot_filename)
        cot_images.append(cot_filename)
        
        # Also save to temp for concatenation
        _plot_state(square, shape_to_plot, edges_to_plot, holes, temp_dir / f"step_{len(shapes)+idx:02d}_unfold.png",)

        if idx == num_folds - 1:
            max_set_retries = 50
            max_retries = 100
            
            for set_attempt in range(max_set_retries):
                temp_wrong_holes = []
                
                # Wrong answer 1: all correct holes + extra hole
                for _ in range(max_retries):
                    candidate = _generate_point(shapes[1], size, points=new_holes)
                    candidate_holes = [i for i in new_holes] + [candidate]
                    if _is_sufficiently_different(candidate_holes, new_holes, min_distinguishable_distance):
                        temp_wrong_holes.append(candidate_holes)
                        break
                else:
                    candidate = _generate_point(shapes[1], size, points=new_holes)
                    temp_wrong_holes.append([i for i in new_holes] + [candidate])  # fallback

                # Wrong answer 2: missing one hole
                for _ in range(max_retries):
                    chosen = random.randrange(len(new_holes))
                    if len(new_holes) > 1:
                        candidate_holes = [new_holes[i] for i in range(len(new_holes)) if i != chosen]
                        all_answers = [new_holes] + temp_wrong_holes + [candidate_holes]
                        if (_is_sufficiently_different(candidate_holes, new_holes, min_distinguishable_distance) and
                            _are_answer_sets_distinguishable(all_answers, min_distinguishable_distance)):
                            temp_wrong_holes.append(candidate_holes)
                            break
                    else:
                        candidate = _generate_point(shapes[1], size, points=new_holes)
                        candidate_holes = [candidate]
                        all_answers = [new_holes] + temp_wrong_holes + [candidate_holes]
                        if (_is_sufficiently_different(candidate_holes, new_holes, min_distinguishable_distance) and
                            _are_answer_sets_distinguishable(all_answers, min_distinguishable_distance)):
                            temp_wrong_holes.append(candidate_holes)
                            break
                else:
                    if len(new_holes) > 1:
                        temp_wrong_holes.append([new_holes[i] for i in range(len(new_holes)) if i != chosen])
                    else:
                        candidate = _generate_point(shapes[1], size, points=new_holes)
                        temp_wrong_holes.append([candidate])  # fallback

                # Wrong answer 3: missing one hole + extra hole
                for _ in range(max_retries):
                    chosen = random.randrange(len(new_holes))
                    candidate = _generate_point(shapes[1], size, points=new_holes)
                    candidate_holes = [new_holes[i] for i in range(len(new_holes)) if i != chosen] + [candidate]
                    all_answers = [new_holes] + temp_wrong_holes + [candidate_holes]
                    if (_is_sufficiently_different(candidate_holes, new_holes, min_distinguishable_distance) and
                        _are_answer_sets_distinguishable(all_answers, min_distinguishable_distance)):
                        temp_wrong_holes.append(candidate_holes)
                        break
                else:
                    chosen = random.randrange(len(new_holes))
                    candidate = _generate_point(shapes[1], size, points=new_holes)
                    temp_wrong_holes.append([new_holes[i] for i in range(len(new_holes)) if i != chosen] + [candidate])  # fallback

                # Wrong answer 4: missing different hole + different extra hole
                for _ in range(max_retries):
                    chosen = random.randrange(len(new_holes))
                    candidate = _generate_point(shapes[1], size, points=new_holes)
                    candidate_holes = [new_holes[i] for i in range(len(new_holes)) if i != chosen] + [candidate]
                    all_answers = [new_holes] + temp_wrong_holes + [candidate_holes]
                    if (_is_sufficiently_different(candidate_holes, new_holes, min_distinguishable_distance) and
                        _are_answer_sets_distinguishable(all_answers, min_distinguishable_distance)):
                        temp_wrong_holes.append(candidate_holes)
                        break
                else:
                    chosen = random.randrange(len(new_holes))
                    candidate = _generate_point(shapes[1], size, points=new_holes)
                    temp_wrong_holes.append([new_holes[i] for i in range(len(new_holes)) if i != chosen] + [candidate])  # fallback
                
                # Final validation: check if all answers are mutually distinguishable
                all_final_answers = [new_holes] + temp_wrong_holes
                if _are_answer_sets_distinguishable(all_final_answers, min_distinguishable_distance):
                    wrong_holes = temp_wrong_holes
                    break
            else:
                # If we couldn't generate a good set, use the last attempt
                wrong_holes = temp_wrong_holes

        if idx == num_folds:
            # Generate wrong answer choices
            for wrong_idx, wrong_hole in enumerate(wrong_holes):
                new_holes: List[Point] = []
                seen: set[Tuple[float, float]] = set()
                for h in wrong_hole:
                    if shape_to_plot.contains(h):
                        key = (round(h.x, 6), round(h.y, 6))
                        if key not in seen:
                            seen.add(key)
                            new_holes.append(h)
                    h_ref = Point(*_reflect_point((h.x, h.y), axis))
                    if shape_to_plot.contains(h_ref):
                        key = (round(h_ref.x, 6), round(h_ref.y, 6))
                        if key not in seen:
                            seen.add(key)
                            new_holes.append(h_ref)
                _plot_state(square, shape_to_plot, edges_to_plot, new_holes, save_path / f"wrong_{wrong_idx}.png",)
    
    # ── create combined images ───────────────────────────────────────────────
    # Question image: all folds + hole punch
    fold_images = sorted(glob.glob(str(temp_dir / "step_*_fold.png")))
    hole_image = glob.glob(str(temp_dir / "step_*_hole.png"))
    if hole_image:
        images_for_question = fold_images + [hole_image[0]]
        question_image = _concatenate_images_horizontally(images_for_question)
        question_image.save(save_path / f"question.png")
    
    # Silhouette: final unfolded state
    final_unfold = max(glob.glob(str(temp_dir / "step_*_unfold.png")), 
                       key=lambda x: int(os.path.basename(x).split('_')[1]))
    Image.open(final_unfold).save(save_path / f"silhouette.png")
    
    # Combined view: question in top row, answer choices in bottom row
    # Collect all answer choices (4 wrong + 1 correct)
    answer_choices = []
    for i in range(len(wrong_holes)):
        answer_choices.append(Image.open(save_path / f"wrong_{i}.png"))
    
    # Insert correct answer at a random position
    correct_answer_idx = random.randint(0, len(answer_choices))
    answer_choices.insert(correct_answer_idx, Image.open(save_path / f"silhouette.png"))
    
    # Save combined view (question + answers)
    combined = _create_question_answer_grid(
        Image.open(save_path / f"question.png"),
        answer_choices,
        correct_answer_idx
    )
    combined.save(save_path / f"combined.png")
    
    # Save answer grid only (just the 5 labeled choices)
    answer_grid = _create_answer_grid_only(answer_choices, correct_answer_idx)
    answer_grid.save(save_path / f"answers_grid.png")
    
    # Update metadata with correct answer index
    correct_choice_label = chr(65 + correct_answer_idx)  # A, B, C, D, E
    
    # Calculate distinguishability metrics
    # 1. Distance from each wrong answer to correct answer
    wrong_answer_distances = []
    for wrong_hole_list in wrong_holes:
        # Calculate the maximum of: 
        # 1) minimum distance from each wrong hole to any correct hole
        # 2) minimum distance from each correct hole to any wrong hole
        max_min_dist = 0.0
        
        # Check each wrong hole's distance to nearest correct hole
        if wrong_hole_list:
            for wrong_hole in wrong_hole_list:
                min_dist_to_correct = min(wrong_hole.distance(correct_hole) for correct_hole in holes)
                max_min_dist = max(max_min_dist, min_dist_to_correct)
        
        # Check each correct hole's distance to nearest wrong hole
        if holes and wrong_hole_list:
            for correct_hole in holes:
                min_dist_to_wrong = min(correct_hole.distance(wrong_hole) for wrong_hole in wrong_hole_list)
                max_min_dist = max(max_min_dist, min_dist_to_wrong)
        
        wrong_answer_distances.append(round(max_min_dist, 3))
    
    # 2. Pairwise distances between all answer choices (for mutual distinguishability)
    all_answer_sets = [holes] + wrong_holes
    pairwise_distances = []
    for i in range(len(all_answer_sets)):
        for j in range(i + 1, len(all_answer_sets)):
            # Calculate max min distance between two answer sets
            max_min_dist = 0.0
            
            if all_answer_sets[i] and all_answer_sets[j]:
                for hole_i in all_answer_sets[i]:
                    min_dist = min(hole_i.distance(hole_j) for hole_j in all_answer_sets[j])
                    max_min_dist = max(max_min_dist, min_dist)
                
                for hole_j in all_answer_sets[j]:
                    min_dist = min(hole_j.distance(hole_i) for hole_i in all_answer_sets[i])
                    max_min_dist = max(max_min_dist, min_dist)
            
            pairwise_distances.append({
                "answer_pair": [i, j],
                "distance": round(max_min_dist, 3)
            })
    
    # Find minimum pairwise distance
    min_pairwise_distance = min(d["distance"] for d in pairwise_distances) if pairwise_distances else 0.0
    
    # ── create metadata ──────────────────────────────────────────────────────
    metadata = {
        "puzzle_id": puzzle_id,
        "grid_size": n,
        "num_folds": num_folds,
        "fold_types": [axis["type"] for axis in axes],
        "question_image": "question.png",
        "silhouette_image": "silhouette.png",
        "combined_image": "combined.png",
        "answers_grid_image": "answers_grid.png",
        "cot_images": cot_images,
        "wrong_choices": [f"wrong_{i}.png" for i in range(len(wrong_holes))],
        "correct_choice": correct_choice_label,
        "correct_choice_index": correct_answer_idx,
        "choices": [chr(65 + i) for i in range(5)],  # A, B, C, D, E
        "question": "If you fold the paper as shown, punch a hole, and unfold it, where will all the holes be?",
        "distinguishability_metrics": {
            "min_required_distance": min_distinguishable_distance,
            "wrong_to_correct_distances": wrong_answer_distances,
            "min_pairwise_distance": min_pairwise_distance,
            "all_pairwise_distances": pairwise_distances,
            "note": "Answer 0 is correct, answers 1-4 are wrong"
        },
    }
    
    return metadata


def _concatenate_images_horizontally(image_paths):
    """Concatenate multiple images horizontally."""
    images = [Image.open(p) if isinstance(p, (str, Path)) else p for p in image_paths]
    heights = [img.height for img in images]
    max_height = max(heights)
    total_width = sum(img.width for img in images)
    
    new_image = Image.new('RGB', (total_width, max_height), color=(255, 255, 255))
    
    x_offset = 0
    for img in images:
        new_image.paste(img, (x_offset, 0))
        x_offset += img.width
    
    return new_image


def _create_answer_grid_only(answer_choices: list, correct_idx: int) -> Image.Image:
    """Create a grid of just the answer choices with labels.
    
    Args:
        answer_choices: List of 5 answer choice images
        correct_idx: Index of the correct answer
        
    Returns:
        Combined image with labeled choices A-E
    """
    from PIL import ImageDraw, ImageFont
    
    # Calculate dimensions
    margin = 20
    label_height = 70
    
    # Answer choices in one row
    choice_heights = [img.height for img in answer_choices]
    max_choice_height = max(choice_heights)
    total_choice_width = sum(img.width for img in answer_choices) + margin * (len(answer_choices) - 1)
    
    # Total dimensions
    total_width = total_choice_width + 2 * margin
    total_height = max_choice_height + label_height + 2 * margin
    
    # Create canvas
    canvas = Image.new('RGB', (total_width, total_height), color=(255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    
    # Try to load a font, fall back to default
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    except:
        font = ImageFont.load_default()
    
    # Paste answer choices with labels
    y_offset = margin + label_height
    x_offset = margin
    
    for idx, img in enumerate(answer_choices):
        # Draw label above choice
        label = chr(65 + idx)  # A, B, C, D, E
        label_x = x_offset + img.width // 2
        label_y = margin + label_height // 2
        
        # Draw label with box
        bbox = draw.textbbox((label_x, label_y), label, font=font, anchor="mm")
        box_padding = 8
        draw.rectangle([bbox[0] - box_padding, bbox[1] - box_padding, 
                       bbox[2] + box_padding, bbox[3] + box_padding], 
                      outline="black", width=2)
        draw.text((label_x, label_y), label, fill="black", font=font, anchor="mm")
        
        # Paste image
        canvas.paste(img, (x_offset, y_offset))
        x_offset += img.width + margin
    
    return canvas


def _create_question_answer_grid(question_img: Image.Image, answer_choices: list, correct_idx: int) -> Image.Image:
    """Create a combined view with question on top and answer choices below.
    
    Args:
        question_img: The question image (folding sequence)
        answer_choices: List of 5 answer choice images (correct + 4 wrong, shuffled)
        correct_idx: Index of the correct answer in answer_choices
    
    Returns:
        Combined image with question on top, labeled choices below
    """
    from PIL import ImageDraw, ImageFont
    
    # Calculate dimensions
    margin = 20
    label_height = 70
    fontsize = 48
    
    # Answer choices row
    choice_heights = [img.height for img in answer_choices]
    max_choice_height = max(choice_heights)
    total_choice_width = sum(img.width for img in answer_choices) + margin * (len(answer_choices) - 1)
    
    # Total dimensions
    total_width = max(question_img.width, total_choice_width) + 2 * margin
    total_height = question_img.height + max_choice_height + label_height + 3 * margin
    
    # Create canvas
    canvas = Image.new('RGB', (total_width, total_height), color=(255, 255, 255))
    draw = ImageDraw.Draw(canvas)
    
    # Try to load a font, fall back to default
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", fontsize)
    except:
        font = ImageFont.load_default(fontsize)
    
    # Paste question image centered at top
    question_x = (total_width - question_img.width) // 2
    canvas.paste(question_img, (question_x, margin))
    
    # Paste answer choices with labels
    y_offset = question_img.height + 2 * margin + label_height
    x_offset = (total_width - total_choice_width) // 2
    
    for idx, img in enumerate(answer_choices):
        # Draw label above choice
        label = chr(65 + idx)  # A, B, C, D, E
        label_x = x_offset + img.width // 2
        label_y = y_offset - label_height + 5
        
        # Draw label with box
        bbox = draw.textbbox((label_x, label_y), label, font=font, anchor="mm")
        box_padding = 8
        draw.rectangle([bbox[0] - box_padding, bbox[1] - box_padding, 
                       bbox[2] + box_padding, bbox[3] + box_padding], 
                      outline="black", width=2)
        draw.text((label_x, label_y), label, fill="black", font=font, anchor="mm")
        
        # Paste image
        canvas.paste(img, (x_offset, y_offset))
        x_offset += img.width + margin
    
    return canvas


def main():
    """Main entry point for generating a dataset of paper folding puzzles."""
    parser = argparse.ArgumentParser(description="Generate paper folding puzzle dataset")
    parser.add_argument("--instances", type=int, default=20, help="Number of puzzle instances to generate")
    parser.add_argument("--grid-size", type=int, default=3, help="Size of the grid (n×n)")
    parser.add_argument("--min-folds", type=int, default=3, help="Minimum number of folds")
    parser.add_argument("--max-folds", type=int, default=5, help="Maximum number of folds")
    parser.add_argument("--output-dir", type=str, default="output", help="Output directory")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    parser.add_argument("--min-distinguishable-distance", type=float, default=0.3, 
                       help="Minimum distance between correct and wrong answer holes (default: 0.3)")
    
    args = parser.parse_args()
    
    # Set global seed if provided
    if args.seed is not None:
        random.seed(args.seed)
    
    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    print(f"\nGenerating {args.instances} paper folding puzzles...")
    print(f"Grid size: {args.grid_size}×{args.grid_size}")
    print(f"Folds per puzzle: {args.min_folds}-{args.max_folds}\n")
    
    all_metadata = []
    
    for i in range(1, args.instances + 1):
        puzzle_dir = output_path / f"puzzle_{i:04d}"
        puzzle_dir.mkdir(exist_ok=True)
        
        try:
            # Generate individual puzzle with its own seed
            puzzle_seed = random.randint(0, 1000000) if args.seed is not None else None
            metadata = generate_sequence(
                n=args.grid_size,
                min_steps=args.min_folds,
                max_steps=args.max_folds,
                seed=puzzle_seed,
                save_dir=puzzle_dir,
                puzzle_id=i,
                min_distinguishable_distance=args.min_distinguishable_distance
            )
            
            # Save puzzle metadata
            with open(puzzle_dir / "metadata.json", "w") as f:
                json.dump(metadata, f, indent=2)
            
            all_metadata.append(metadata)
            
            # Clean up temp directory
            temp_dir = puzzle_dir / "temp"
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            
            # Check distinguishability and warn if below threshold
            min_dist = metadata["distinguishability_metrics"]["min_pairwise_distance"]
            required_dist = metadata["distinguishability_metrics"]["min_required_distance"]
            
            if min_dist < required_dist:
                print(f"  ⚠ Generated puzzle {i} ({metadata['num_folds']} folds) - min distance: {min_dist:.3f} (< {required_dist:.3f})")
            else:
                print(f"  ✓ Generated puzzle {i} ({metadata['num_folds']} folds) - min distance: {min_dist:.3f}")
            
        except Exception as e:
            print(f"  ✗ Failed to generate puzzle {i}: {e}")
            continue
    
    # Calculate distinguishability statistics
    puzzles_meeting_threshold = sum(
        1 for m in all_metadata 
        if m["distinguishability_metrics"]["min_pairwise_distance"] >= args.min_distinguishable_distance
    )
    
    avg_min_distance = (
        sum(m["distinguishability_metrics"]["min_pairwise_distance"] for m in all_metadata) / len(all_metadata)
        if all_metadata else 0.0
    )
    
    # Save dataset metadata
    dataset_metadata = {
        "description": "Paper folding puzzle dataset",
        "total_instances": len(all_metadata),
        "grid_size": args.grid_size,
        "min_folds": args.min_folds,
        "max_folds": args.max_folds,
        "min_distinguishable_distance": args.min_distinguishable_distance,
        "distinguishability_stats": {
            "puzzles_meeting_threshold": puzzles_meeting_threshold,
            "puzzles_below_threshold": len(all_metadata) - puzzles_meeting_threshold,
            "average_min_pairwise_distance": round(avg_min_distance, 3)
        },
        "puzzles": all_metadata
    }
    
    with open(output_path / "dataset_metadata.json", "w") as f:
        json.dump(dataset_metadata, f, indent=2)
    
    print(f"\n{'='*60}")
    print(f"Dataset generation complete!")
    print(f"Total puzzles: {len(all_metadata)}")
    print(f"Puzzles meeting threshold: {puzzles_meeting_threshold}/{len(all_metadata)} ({puzzles_meeting_threshold/len(all_metadata)*100:.1f}%)")
    print(f"Average min pairwise distance: {avg_min_distance:.3f}")
    print(f"Output directory: {output_path.absolute()}")
    print(f"{'='*60}\n")


# ──────────────────────────────────────────────────────────────────────────────
# Plotting utility
# ──────────────────────────────────────────────────────────────────────────────

def _plot_state(
    full_square: Polygon,
    poly: Polygon,
    edges: List[LineString],
    holes: List[Point],
    filename: Path,
    *,
    fold_axis: Dict | None = None,
) -> None:
    """Render one state with internal edges using style guide formatting.
    - Aquamarine background
    - Midnight outlines
    - Dashed fold axis with arrowheads (if provided)
    - Subtle frame border
    """
    fig, ax = plt.subplots(figsize=CANVAS_SIZE)
    ax.set_aspect("equal")
    ax.set_xlim(-0.1, full_square.bounds[2] + 0.1)
    ax.set_ylim(-0.1, full_square.bounds[3] + 0.1)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_frame_on(True)
    ax.set_facecolor("#abe7e1")  # Aquamarine with ~0.4 alpha (hex with alpha: 80 = 128/255 ≈ 0.5 opacity)
    for spine in ax.spines.values():
        spine.set_edgecolor(MIDNIGHT)
        spine.set_linewidth(1.0)

    # Original reference square (subtle outline)
    xs, ys = full_square.exterior.xy
    ax.plot(xs, ys, linestyle="-", linewidth=1.0, color=MIDNIGHT, alpha=0.3)

    # Current outer outline (bold)
    xs, ys = poly.exterior.xy
    ax.fill(xs, ys, facecolor="white", edgecolor=MIDNIGHT, linewidth=2.5)

    # Internal edges & creases (thin)
    for e in edges:
        xs, ys = e.xy
        ax.plot(xs, ys, linewidth=1.0, color=MIDNIGHT, alpha=0.9)

    # Optional: fold axis overlay
    # Fold axis overlay removed per style update

    # Holes
    for h in holes:
        hole_radius = 0.08  # in data units (relative to grid unit)
        circ = plt.Circle((h.x, h.y), hole_radius, facecolor=AQUAMARINE, edgecolor=MIDNIGHT, linewidth=1.2, alpha=0.4)
        ax.add_patch(circ)

    fig.tight_layout()
    fig.savefig(filename, dpi=180, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    main()