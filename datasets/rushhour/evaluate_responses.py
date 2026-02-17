import json
import argparse
from pathlib import Path
from typing import List, Dict, Any, Tuple

import matplotlib.pyplot as plt
import numpy as np

# Import generator functions directly
from generator import (
    apply_action,
    _max_translation_along_axis,
    _rectangle_polygon,
    _convex_polygon,
    _place_shape_on_board,
    Pose
)

# Chance performance per level (from random sampling with 5 non-red moves + 1 red move)
CHANCE_PERFORMANCE = {
    'level_01': 1.000000,
    'level_02': 0.583800,
    'level_03': 0.028667,
    'level_04': 0.005333,
    'level_05': 0.000400
}


def compute_confidence_interval(accuracy: float, n: int, confidence: float = 0.95) -> tuple:
    """Compute Wilson score confidence interval for a binomial proportion."""
    from scipy import stats

    if n <= 0:
        return (0.0, 0.0)

    z = stats.norm.ppf((1 + confidence) / 2)
    denominator = 1 + z**2 / n
    center = (accuracy + z**2 / (2 * n)) / denominator
    margin = z * np.sqrt((accuracy * (1 - accuracy) / n + z**2 / (4 * n**2))) / denominator
    return (center - margin, center + margin)


def _is_solved(instance: Dict[str, Any]) -> bool:
    """Check if the red car has reached the exit.
    
    The exit is defined by its side (left/right/top/bottom) and opening_start/opening_end.
    The red car is solved when its front edge reaches the board boundary at the exit opening.
    """
    from generator import _rectangle_polygon, _place_shape_on_board, Pose
    
    # Find red car
    red_car = next(o for o in instance["objects"] if o["id"] == "red_car")
    
    # Build red car polygon
    if red_car["shape"] == "rectangle" and red_car.get("size"):
        local = _rectangle_polygon(red_car["size"][0], red_car["size"][1])
    else:
        local = _rectangle_polygon(1.8, 0.9)  # default red car size
    
    red_poly = _place_shape_on_board(local, Pose(**red_car["pose"]))
    red_bounds = red_poly.bounds  # (minx, miny, maxx, maxy)
    
    # Get exit info
    exit_info = instance["board"]["exits"][0]
    side = exit_info["side"]
    opening_start = exit_info["opening_start"]
    opening_end = exit_info["opening_end"]
    board_w = instance["board"]["width"]
    board_h = instance["board"]["height"]
    
    eps = 1e-3
    
    # Check if red car has reached the board edge at the exit opening
    if side == "left":
        # Red car's left edge (minx) should reach x=0
        # And red car should be within the opening (y range)
        red_center_y = (red_bounds[1] + red_bounds[3]) / 2
        at_edge = red_bounds[0] <= eps
        in_opening = opening_start - eps <= red_center_y <= opening_end + eps
        return at_edge and in_opening
    elif side == "right":
        # Red car's right edge (maxx) should reach x=board_w
        red_center_y = (red_bounds[1] + red_bounds[3]) / 2
        at_edge = red_bounds[2] >= board_w - eps
        in_opening = opening_start - eps <= red_center_y <= opening_end + eps
        return at_edge and in_opening
    elif side == "bottom":
        # Red car's bottom edge (miny) should reach y=0
        red_center_x = (red_bounds[0] + red_bounds[2]) / 2
        at_edge = red_bounds[1] <= eps
        in_opening = opening_start - eps <= red_center_x <= opening_end + eps
        return at_edge and in_opening
    elif side == "top":
        # Red car's top edge (maxy) should reach y=board_h
        red_center_x = (red_bounds[0] + red_bounds[2]) / 2
        at_edge = red_bounds[3] >= board_h - eps
        in_opening = opening_start - eps <= red_center_x <= opening_end + eps
        return at_edge and in_opening
    
    return False


def _parse_move_sequence(seq: str) -> List[Tuple[str, str]]:
    """Parse a sequence like "A forward, C backward, Red forward" into [(label, direction), ...]."""
    if not seq or not isinstance(seq, str):
        return []
    parts = [p.strip() for p in seq.split(',') if p.strip()]
    moves: List[Tuple[str, str]] = []
    for p in parts:
        tokens = p.split()
        if len(tokens) >= 2:
            label = tokens[0].strip()
            direction = tokens[1].strip().lower()
            moves.append((label, direction))
    return moves


def _build_label_to_id_map(objects: List[Dict[str, Any]]) -> Dict[str, str]:
    """Build mapping from labels to object IDs."""
    label_to_id = {}
    
    for o in objects:
        if not o.get("movable", True):
            continue
        
        obj_id = o["id"]
        
        # Red car special cases
        if obj_id == "red_car":
            label_to_id["red"] = obj_id
            label_to_id["r"] = obj_id
            label_to_id["red_car"] = obj_id
        else:
            # Use label field if present
            lbl = o.get("label")
            if lbl:
                label_to_id[lbl.lower()] = obj_id
                label_to_id[lbl.upper()] = obj_id
            
            # Also allow direct ID access
            label_to_id[obj_id.lower()] = obj_id
            label_to_id[obj_id] = obj_id
    
    return label_to_id


def _get_valid_object_ids(objects: List[Dict[str, Any]]) -> set:
    """Get set of valid movable object IDs."""
    return {o["id"] for o in objects if o.get("movable", True)}


def _world_polys_for_state(instance: Dict[str, Any]) -> List[Any]:
    """Build world polygons for all objects in the current instance state."""
    from shapely.geometry import Polygon
    
    world_polys = []
    for obj in instance["objects"]:
        if obj["shape"] == "rectangle" and obj.get("size"):
            local = _rectangle_polygon(obj["size"][0], obj["size"][1])
        elif obj["shape"] == "polygon" and obj.get("vertices"):
            local = _convex_polygon([(float(x), float(y)) for x, y in obj["vertices"]])
        else:
            local = _rectangle_polygon(1.0, 1.0)
        pose = Pose(**obj["pose"])
        world_polys.append(_place_shape_on_board(local, pose))
    return world_polys


def _recompute_extrema_for_object(
    obj_id: str, 
    instance: Dict[str, Any], 
    world_polys: List
) -> Tuple[float, float]:
    """Recompute extrema (t_min, t_max) for an object in the current state."""
    obj = next(o for o in instance["objects"] if o["id"] == obj_id)
    obj_idx = instance["objects"].index(obj)
    
    axis = tuple(obj["local_axis"])
    board_w = instance["board"]["width"]
    board_h = instance["board"]["height"]
    
    t_neg, t_pos = _max_translation_along_axis(
        obj_idx, world_polys[obj_idx], axis, world_polys, board_w, board_h,
        step_initial=0.25, epsilon=1e-3
    )
    return t_neg, t_pos


def _convert_move_to_action(label: str, direction: str, instance: Dict[str, Any]) -> Tuple[Dict[str, Any], bool, bool]:
    """
    Convert a parsed move (label, direction) into an action dict.
    Recomputes extrema based on current state to ensure cars move until they hit obstacles.
    Returns (action_dict, parse_ok, ids_valid).
    """
    label_to_id = _build_label_to_id_map(instance["objects"])
    valid_ids = _get_valid_object_ids(instance["objects"])
    
    # Map label to object ID
    obj_id = label_to_id.get(label.lower())
    if obj_id is None or obj_id not in valid_ids:
        return {}, True, False  # parse_ok=True, but invalid ID
    
    # Map direction word to +1/-1
    if direction in ("forward", "fwd", "+1", "+"):
        dir_val = 1
    elif direction in ("backward", "back", "-1", "-"):
        dir_val = -1
    else:
        return {}, False, True  # parse failed for direction
    
    # Recompute extrema for current state (not using initial drive_segment)
    world_polys = _world_polys_for_state(instance)
    t_min, t_max = _recompute_extrema_for_object(obj_id, instance, world_polys)
    
    # Distance is the extremum in the requested direction
    distance = abs(t_min) if dir_val < 0 else t_max
    
    action = {
        "object_id": obj_id,
        "direction": dir_val,
        "distance": float(distance)
    }
    
    return action, True, True


def _compute_chance_performance_for_instance(instance: Dict[str, Any]) -> float:
    """
    Compute chance performance for a single instance.
    Assumes strategy: first move A (no obstacles), then move red.
    Tests all 4 sequences: A forward→R forward, A forward→R backward, 
    A backward→R forward, A backward→R backward.
    Returns fraction of sequences that solve the puzzle.
    """
    import copy
    
    # Find car A (first movable car that's not red)
    car_a = None
    car_a_id = None
    for obj in instance["objects"]:
        if obj.get("movable", True) and obj["id"] != "red_car":
            label = obj.get("label", "")
            if label.upper() == "A":
                car_a = obj
                car_a_id = obj["id"]
                break
    
    # If no car A found, use first non-red movable car
    if car_a is None:
        for obj in instance["objects"]:
            if obj.get("movable", True) and obj["id"] != "red_car":
                car_a = obj
                car_a_id = obj["id"]
                break
    
    if car_a is None:
        # No movable cars except red, check if red can solve directly
        test_instance = copy.deepcopy(instance)
        return 1.0 if _is_solved(test_instance) else 0.0
    
    # Get A's drive segment (assuming no obstacles, so use initial drive_segment)
    ds = car_a.get("drive_segment", {})
    t_min = ds.get("t_min", 0.0)
    t_max = ds.get("t_max", 0.0)
    
    epsilon = 1e-3
    can_move_neg = t_min < -epsilon
    can_move_pos = t_max > epsilon
    
    if not can_move_neg and not can_move_pos:
        # A cannot move, check if red can solve directly
        test_instance = copy.deepcopy(instance)
        return 1.0 if _is_solved(test_instance) else 0.0
    
    # Test all 4 sequences
    sequences_work = 0
    total_sequences = 0
    
    # Sequence 1: A forward, then R forward
    if can_move_pos:
        total_sequences += 1
        test_instance = copy.deepcopy(instance)
        # Move A forward (to maximum)
        action_a_forward = {
            "object_id": car_a_id,
            "direction": 1,
            "distance": float(t_max)
        }
        test_instance = apply_action(test_instance, action_a_forward)
        # Check if R can move forward to solve
        world_polys = _world_polys_for_state(test_instance)
        red_car = next(o for o in test_instance["objects"] if o["id"] == "red_car")
        red_idx = test_instance["objects"].index(red_car)
        axis = tuple(red_car["local_axis"])
        board_w = test_instance["board"]["width"]
        board_h = test_instance["board"]["height"]
        t_neg, t_pos = _max_translation_along_axis(red_idx, world_polys[red_idx], axis, world_polys, board_w, board_h)
        if t_pos > epsilon:
            # Try moving R forward and check if solved
            action_r_forward = {
                "object_id": "red_car",
                "direction": 1,
                "distance": float(t_pos)
            }
            test_instance_r = apply_action(test_instance, action_r_forward)
            if _is_solved(test_instance_r):
                sequences_work += 1
    
    # Sequence 2: A forward, then R backward
    if can_move_pos:
        total_sequences += 1
        test_instance = copy.deepcopy(instance)
        # Move A forward (to maximum)
        action_a_forward = {
            "object_id": car_a_id,
            "direction": 1,
            "distance": float(t_max)
        }
        test_instance = apply_action(test_instance, action_a_forward)
        # Check if R can move backward to solve
        world_polys = _world_polys_for_state(test_instance)
        red_car = next(o for o in test_instance["objects"] if o["id"] == "red_car")
        red_idx = test_instance["objects"].index(red_car)
        axis = tuple(red_car["local_axis"])
        board_w = test_instance["board"]["width"]
        board_h = test_instance["board"]["height"]
        t_neg, t_pos = _max_translation_along_axis(red_idx, world_polys[red_idx], axis, world_polys, board_w, board_h)
        if abs(t_neg) > epsilon:
            # Try moving R backward and check if solved
            action_r_backward = {
                "object_id": "red_car",
                "direction": -1,
                "distance": float(abs(t_neg))
            }
            test_instance_r = apply_action(test_instance, action_r_backward)
            if _is_solved(test_instance_r):
                sequences_work += 1
    
    # Sequence 3: A backward, then R forward
    if can_move_neg:
        total_sequences += 1
        test_instance = copy.deepcopy(instance)
        # Move A backward (to maximum)
        action_a_backward = {
            "object_id": car_a_id,
            "direction": -1,
            "distance": float(abs(t_min))
        }
        test_instance = apply_action(test_instance, action_a_backward)
        # Check if R can move forward to solve
        world_polys = _world_polys_for_state(test_instance)
        red_car = next(o for o in test_instance["objects"] if o["id"] == "red_car")
        red_idx = test_instance["objects"].index(red_car)
        axis = tuple(red_car["local_axis"])
        board_w = test_instance["board"]["width"]
        board_h = test_instance["board"]["height"]
        t_neg, t_pos = _max_translation_along_axis(red_idx, world_polys[red_idx], axis, world_polys, board_w, board_h)
        if t_pos > epsilon:
            # Try moving R forward and check if solved
            action_r_forward = {
                "object_id": "red_car",
                "direction": 1,
                "distance": float(t_pos)
            }
            test_instance_r = apply_action(test_instance, action_r_forward)
            if _is_solved(test_instance_r):
                sequences_work += 1
    
    # Sequence 4: A backward, then R backward
    if can_move_neg:
        total_sequences += 1
        test_instance = copy.deepcopy(instance)
        # Move A backward (to maximum)
        action_a_backward = {
            "object_id": car_a_id,
            "direction": -1,
            "distance": float(abs(t_min))
        }
        test_instance = apply_action(test_instance, action_a_backward)
        # Check if R can move backward to solve
        world_polys = _world_polys_for_state(test_instance)
        red_car = next(o for o in test_instance["objects"] if o["id"] == "red_car")
        red_idx = test_instance["objects"].index(red_car)
        axis = tuple(red_car["local_axis"])
        board_w = test_instance["board"]["width"]
        board_h = test_instance["board"]["height"]
        t_neg, t_pos = _max_translation_along_axis(red_idx, world_polys[red_idx], axis, world_polys, board_w, board_h)
        if abs(t_neg) > epsilon:
            # Try moving R backward and check if solved
            action_r_backward = {
                "object_id": "red_car",
                "direction": -1,
                "distance": float(abs(t_neg))
            }
            test_instance_r = apply_action(test_instance, action_r_backward)
            if _is_solved(test_instance_r):
                sequences_work += 1
    
    # Return fraction of sequences that work
    if total_sequences == 0:
        return 0.0
    return sequences_work / total_sequences


def evaluate_responses(responses_path: str):
    """Evaluate model responses for Rush Hour.

    For each response:
    1. Regenerate the instance using the seed from metadata
    2. Verify it matches the original
    3. Apply the model's proposed actions
    4. Check if solved

    Computes strict accuracy (valid responses only) and lenient accuracy (all responses).
    """
    with open(responses_path, 'r') as f:
        data = json.load(f)

    responses = data["responses"]
    n = len(responses)

    print(f"\n{'='*60}")
    print(f"Evaluating {n} responses from: {Path(responses_path).name}")
    print(f"{'='*60}\n")

    # Aggregates
    solved_flags_lenient: List[bool] = []  # Lenient: skip invalid moves, continue evaluating
    solved_flags_strict: List[bool] = []    # Strict: invalid moves mark response as wrong
    valid_mask: List[bool] = []
    parse_failed = 0
    invalid_ids = 0
    generation_mismatch = 0

    pred_num_actions_all: List[int] = []
    gt_num_actions_all: List[int] = [] 
    chance_performances: List[float] = []  # Track chance performance per instance

    model_name = Path(responses_path).parts[-3]

    for idx, r in enumerate(responses):
        # Locate instance metadata
        puzzle_dir = r.get("puzzle_dir")
        if puzzle_dir is None:
            # Try dataset_path + puzzle_id fallback
            dataset_path = r.get("dataset_path") or data.get("dataset_path")
            pid = r.get("puzzle_id")
            if dataset_path is not None and pid is not None:
                puzzle_dir = str(Path(dataset_path) / f"puzzle_{pid:04d}")
        
        if puzzle_dir is None:
            print(f"Warning: Could not determine puzzle_dir for response {idx}")
            parse_failed += 1
            solved_flags_lenient.append(False)
            solved_flags_strict.append(False)
            valid_mask.append(False)
            pred_num_actions_all.append(0)
            gt_num_actions_all.append(0)
            chance_performances.append(0.5)  # Default if we can't compute
            continue

        puzzle_dir = Path(puzzle_dir)
        has_invalid_id = False

        try:
            # Load metadata
            meta_path = puzzle_dir / "metadata.json"
            with open(meta_path, 'r') as mf:
                meta = json.load(mf)

            # Use the instance data directly from metadata (no regeneration needed)
            # The metadata contains full board and objects info
            generated_instance = {
                "board": meta["board"],
                "objects": meta["objects"]
            }

            # Compute chance performance for this instance
            chance_perf = _compute_chance_performance_for_instance(generated_instance)
            chance_performances.append(chance_perf)

            gt_len = meta.get("solution_length", len(meta.get("actions", [])))

            # Parse model's move sequence
            pred_raw = r.get("output_parsed", {}).get("answer") if r.get("output_parsed") else None
            if not pred_raw:
                parse_failed += 1
                solved_flags_lenient.append(False)
                solved_flags_strict.append(False)
                valid_mask.append(False)
                pred_num_actions_all.append(0)
                gt_num_actions_all.append(gt_len)
                # chance_performance already computed above
                print(f'Error in instance {idx}: No move sequence found in response')
                continue

            moves = _parse_move_sequence(pred_raw)
            if not moves:
                parse_failed += 1
                solved_flags_lenient.append(False)
                solved_flags_strict.append(False)
                valid_mask.append(False)
                pred_num_actions_all.append(0)
                gt_num_actions_all.append(gt_len)
                # chance_performance already computed above
                print(f'Error in instance {idx}: No moves found in move sequence')
                continue

            # Apply each move using apply_action from generator
            # For lenient: skip invalid moves and continue
            # For strict: invalid moves mark response as wrong
            current_instance_lenient = generated_instance
            current_instance_strict = generated_instance
            all_valid_strict = True
            
            for label, direction in moves:
                # Try to convert move to action
                action, parse_ok, ids_ok = _convert_move_to_action(label, direction, current_instance_lenient)
                
                if not parse_ok:
                    # Parse failure: both lenient and strict mark as invalid
                    parse_failed += 1
                    all_valid_strict = False
                    break
                
                if not ids_ok:
                    # Invalid ID: lenient skips, strict marks as invalid
                    has_invalid_id = True
                    all_valid_strict = False
                    # For lenient, skip this move and continue
                    continue
                
                # Valid move: apply to both instances
                current_instance_lenient = apply_action(current_instance_lenient, action)
                if all_valid_strict:
                    current_instance_strict = apply_action(current_instance_strict, action)
            
            # Check if solved for lenient (even if there were invalid IDs)
            solved_lenient = _is_solved(current_instance_lenient)
            
            # For strict: if there were invalid IDs or parse failures, mark as wrong
            if not all_valid_strict:
                solved_strict = False
                valid_mask.append(False)
            else:
                solved_strict = _is_solved(current_instance_strict)
                valid_mask.append(True)
            
            
            solved_flags_lenient.append(solved_lenient)
            solved_flags_strict.append(solved_strict)
            pred_num_actions_all.append(len(moves))
            gt_num_actions_all.append(gt_len)

        except Exception as e:
            print(f"Error processing response {idx}: {e}")
            import traceback
            traceback.print_exc()
            parse_failed += 1
            solved_flags_lenient.append(False)
            solved_flags_strict.append(False)
            valid_mask.append(False)
            pred_num_actions_all.append(0)
            gt_num_actions_all.append(0)
            # Only append if we haven't already computed chance_performance for this instance
            if len(chance_performances) < len(solved_flags_lenient):
                chance_performances.append(0.5)  # Default if we can't compute

        if has_invalid_id:
            invalid_ids += 1

    # Compute metrics
    n_all = len(solved_flags_lenient)
    n_valid = sum(valid_mask)

    # Both lenient and strict use correct / total
    correct_lenient = sum(solved_flags_lenient)
    accuracy_lenient = correct_lenient / n_all if n_all > 0 else 0.0
    ci_lenient_lower, ci_lenient_upper = compute_confidence_interval(accuracy_lenient, n_all)

    correct_strict = sum(solved_flags_strict)
    accuracy_strict = correct_strict / n_all if n_all > 0 else 0.0

    # Use actual counts
    ci_strict_lower, ci_strict_upper = compute_confidence_interval(accuracy_strict, n_all)
    correct_strict_display = correct_strict
    n_strict_display = n_all

    # Save metrics JSON
    output_dir = Path(responses_path).parent
    base_name = Path(responses_path).stem

    # if len(chance_performances) > 0:
    #     random_accuracy = sum(chance_performances) / len(chance_performances)
    # else:
    #     random_accuracy = 0.5  # Fallback
    # random_ci_lower, random_ci_upper = compute_confidence_interval(random_accuracy, n_all)


    # Build per-response correctness map for pass@k evaluation
    per_response_correct = {}
    for i, r in enumerate(responses):
        puzzle_id = r.get("puzzle_id", r.get("metadata", {}).get("puzzle_id", i))
        # Use strict correctness (more conservative)
        per_response_correct[puzzle_id] = solved_flags_strict[i] if i < len(solved_flags_strict) else False

    # Save metrics JSON
    output_dir = Path(responses_path).parent
    base_name = Path(responses_path).stem
    
    # Extract level key from parent folder: .../level_03/responses.json -> "level_03"
    difficulty_key = output_dir.name
    
    # Get chance performance for this level
    random_accuracy = CHANCE_PERFORMANCE.get(difficulty_key)
    random_ci_lower = random_ci_upper = None
    if random_accuracy is not None:
        random_ci_lower, random_ci_upper = compute_confidence_interval(random_accuracy, n_all)
        random_baseline_entry = {
            "description": "Chance performance (5 random non-red moves + 1 red move)",
            "accuracy": random_accuracy,
            "confidence_interval_95": {
                "lower": random_ci_lower,
                "upper": random_ci_upper,
            },
        }
    else:
        random_baseline_entry = None

    metrics = {
        "total_responses": n_all,
        "validity_breakdown": {
            "parse_failed": parse_failed,
            "invalid_car_ids": invalid_ids,
            "generation_mismatch": generation_mismatch,
            "completely_valid": n_valid,
        },
        "accuracy_lenient": {
            "description": "Accuracy where invalid moves are skipped and evaluation continues",
            "accuracy": accuracy_lenient,
            "correct_count": correct_lenient,
            "total_count": n_all,
            "confidence_interval_95": {
                "lower": ci_lenient_lower,
                "upper": ci_lenient_upper,
            },
        },
        "accuracy_strict": {
            "description": "Accuracy where invalid moves mark response as wrong, always calculated with 50 samples if available",
            "accuracy": accuracy_strict,
            "correct_count": correct_strict_display,
            "total_count": n_strict_display,
            "actual_correct_count": correct_strict,
            "actual_total_count": n_all,
            "confidence_interval_95": {
                "lower": ci_strict_lower,
                "upper": ci_strict_upper,
            },
        },
        "predicted_actions": pred_num_actions_all,
        "required_actions": gt_num_actions_all,
        # Per-response correctness for pass@k evaluation
        "per_response_correct": per_response_correct,
    }

    if random_baseline_entry is not None:
        metrics["random_baseline"] = random_baseline_entry.copy()
        metrics["accuracy_lenient"]["random_baseline"] = random_baseline_entry.copy()
        metrics["accuracy_strict"]["random_baseline"] = random_baseline_entry.copy()

    metrics_path = output_dir / f"{base_name}_metrics.json"
    with open(metrics_path, 'w') as f:
        json.dump(metrics, f, indent=2)

    print(f"📋 Response Validity:")
    print(f"   Total responses: {n_all}")
    print(f"   Parse failed: {parse_failed}")
    print(f"   Invalid car IDs: {invalid_ids}")
    print(f"   Generation mismatch: {generation_mismatch}")
    print(f"   Completely valid: {n_valid}")
    
    # Print chance performance
    if random_accuracy is not None:
        print(f"\n🎲 Chance Performance ({difficulty_key}): {random_accuracy:.4f}")
    
    print(f"\n📊 Lenient Accuracy (invalid moves skipped): {accuracy_lenient:.3f} ({correct_lenient}/{n_all})")
    print(f"   95% CI: [{ci_lenient_lower:.3f}, {ci_lenient_upper:.3f}]")
    print(f"📊 Strict Accuracy (invalid moves mark as wrong): {accuracy_strict:.3f} ({correct_strict_display}/{n_strict_display})")
    if n_all >= 50:
        print(f"   (Scaled from {correct_strict}/{n_all} to n=50)")
    print(f"   95% CI: [{ci_strict_lower:.3f}, {ci_strict_upper:.3f}]")
    print(f"\n💾 Saved metrics to: {metrics_path}")

    # Plot: Confusion matrix for Proposed vs Required number of actions
    # Build confusion matrix
    max_actions = max(max(pred_num_actions_all, default=0), max(gt_num_actions_all, default=0))
    if max_actions == 0:
        max_actions = 1
    
    # Create matrix: rows = predicted, cols = required
    confusion_matrix = np.zeros((max_actions + 1, max_actions + 1), dtype=int)
    for pred, gt in zip(pred_num_actions_all, gt_num_actions_all):
        pred = int(pred)
        gt = int(gt)
        if 0 <= pred <= max_actions and 0 <= gt <= max_actions:
            confusion_matrix[pred, gt] += 1
    
    # Create the plot
    fig, ax = plt.subplots(figsize=(10, 10))
    im = ax.imshow(confusion_matrix, cmap='Blues', aspect='auto', origin='lower')
    
    # Add colorbar
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label('Number of Samples', fontsize=12, fontweight='bold')
    
    # Set labels and ticks
    action_range = list(range(max_actions + 1))
    ax.set_xticks(action_range)
    ax.set_yticks(action_range)
    ax.set_xticklabels(action_range)
    ax.set_yticklabels(action_range)
    
    ax.set_xlabel('Required Actions (Ground Truth)', fontsize=13, fontweight='bold')
    ax.set_ylabel('Proposed Actions (Model)', fontsize=13, fontweight='bold')
    ax.set_title('Rushhour: Action Count Confusion Matrix', fontsize=15, fontweight='bold')
    
    # Add text annotations in each cell
    for i in range(max_actions + 1):
        for j in range(max_actions + 1):
            count = confusion_matrix[i, j]
            if count > 0:
                # Use white text for dark cells, black for light cells
                text_color = 'white' if count > confusion_matrix.max() / 2 else 'black'
                ax.text(j, i, str(count), ha='center', va='center',
                       color=text_color, fontsize=10, fontweight='bold')
    
    # Add grid
    ax.set_xticks(np.arange(max_actions + 1) - 0.5, minor=True)
    ax.set_yticks(np.arange(max_actions + 1) - 0.5, minor=True)
    ax.grid(which='minor', color='gray', linestyle='-', linewidth=0.5, alpha=0.3)
    
    plt.tight_layout()
    actions_plot_path = output_dir / f"{base_name}_actions_comparison.png"
    plt.savefig(actions_plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"📈 Saved actions confusion matrix to: {actions_plot_path}")

    # Validity breakdown bar plot
    fig, ax = plt.subplots(figsize=(10, 5))
    categories = ["Parse Failed", "Invalid IDs", "Gen Mismatch", "Valid"]
    counts = [parse_failed, invalid_ids, generation_mismatch, n_valid]
    colors = ['#e74c3c', '#f39c12', '#9b59b6', '#2ecc71']
    bars = ax.bar(categories, counts, color=colors, alpha=0.85)
    ax.set_ylabel('Number of Responses', fontsize=12, fontweight='bold')
    ax.set_title('Rushhour: Response Validity Breakdown', fontsize=14, fontweight='bold')
    ax.grid(axis='y', alpha=0.3)
    for bar, count in zip(bars, counts):
        height = bar.get_height()
        pct = count / n_all * 100 if n_all > 0 else 0.0
        ax.text(bar.get_x() + bar.get_width()/2., height + max(counts) * 0.03,
                f'{count}\n({pct:.1f}%)', ha='center', va='bottom', fontsize=11, fontweight='bold')
    plt.tight_layout()
    validity_plot_path = output_dir / f"{base_name}_validity.png"
    plt.savefig(validity_plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"📊 Saved validity breakdown plot to: {validity_plot_path}")

    # Accuracy plot with confidence intervals
    fig, ax = plt.subplots(figsize=(10, 6))
    categories = [f'Lenient Accuracy\n(Invalid Moves Skipped; n={n_all})', f'Strict Accuracy\n(Invalid Moves = Wrong; n={n_strict_display})']
    accuracies = [accuracy_lenient, accuracy_strict]
    ci_lowers = [ci_lenient_lower, ci_strict_lower]
    ci_uppers = [ci_lenient_upper, ci_strict_upper]
    
    # Calculate error bars (distance from center to bounds)
    errors_lower = [acc - lower for acc, lower in zip(accuracies, ci_lowers)]
    errors_upper = [upper - acc for acc, upper in zip(accuracies, ci_uppers)]
    
    # Random baseline: chance performance
    if random_accuracy is not None and random_ci_lower is not None and random_ci_upper is not None:
        # Plot random baseline in background (before bars so it appears behind)
        ax.axhspan(random_ci_lower, random_ci_upper, alpha=0.2, color='#e74c3c',
                   label='Chance Performance 95% CI\n(Random moves)')
        ax.axhline(y=random_accuracy, color='#e74c3c', linestyle='--', linewidth=2,
                   label=f'Chance Performance ({random_accuracy:.3f}). 5 random non-red moves + 1 red move.')
    
    # Create bars
    bars = ax.bar(categories, accuracies, color=['#3498db', '#2ecc71'], alpha=0.85, width=0.6)
    
    # Add error bars for confidence intervals (asymmetric)
    ax.errorbar(categories, accuracies, yerr=(errors_lower, errors_upper), 
                fmt='none', color='black', capsize=8, capthick=2, linewidth=2, elinewidth=2)
    
    ax.set_ylabel('Accuracy', fontsize=13, fontweight='bold')
    ax.set_title(f'Rushhour {model_name.capitalize()} Accuracy (n={n_all})', fontsize=15, fontweight='bold')
    ax.set_ylim([0, min(1.1, max(accuracies) + max(errors_upper) + 0.1)])
    ax.grid(axis='y', alpha=0.3)
    ax.axhline(y=1.0, color='gray', linestyle='--', alpha=0.5, linewidth=1)
    ax.legend(fontsize=10, loc='upper right')
    
    plt.tight_layout()
    accuracy_plot_path = output_dir / f"{base_name}_accuracy.png"
    plt.savefig(accuracy_plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"📊 Saved accuracy plot to: {accuracy_plot_path}")

    print(f"\n{'='*60}")
    print("✅ Evaluation complete!")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate model responses for rushhour benchmark"
    )
    parser.add_argument("--responses", type=str, required=True, help="Path to the responses JSON file")
    args = parser.parse_args()
    evaluate_responses(args.responses)


if __name__ == "__main__":
    main()
