import argparse
import copy
import json
import math
import time
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional

import matplotlib.pyplot as plt
from shapely.geometry import Polygon, box
from shapely.affinity import rotate, translate

from generator import (
    generate_initial_state, 
    render_instance, 
    compute_greedy_solution, 
    apply_action
)
from evaluate_responses import CHANCE_PERFORMANCE


# ============================================================================
# Pixel conversion constants
# Board: 10x10 units = 1200x1200 pixels (6 inch figure at 200 DPI)
# ============================================================================
PIXELS_PER_UNIT = 120.0


def pixels_to_units(pixels: float) -> float:
    """Convert distance in pixels to units."""
    return pixels / PIXELS_PER_UNIT


# ============================================================================
# Polygon utilities for collision checking
# ============================================================================

@dataclass
class Pose:
    x: float
    y: float
    theta: float


def _rectangle_polygon(length: float, width: float) -> Polygon:
    """Create a rectangle polygon centered at origin."""
    half_l = length / 2.0
    half_w = width / 2.0
    return box(-half_l, -half_w, half_l, half_w)


def _place_shape_on_board(local_poly: Polygon, pose: Pose) -> Polygon:
    """Transform a local polygon to world coordinates given a pose."""
    world = rotate(local_poly, pose.theta * 180.0 / math.pi, origin=(0.0, 0.0), use_radians=False)
    world = translate(world, pose.x, pose.y)
    return world


def get_object_polygon(obj: Dict[str, Any]) -> Polygon:
    """Get the world polygon for an object."""
    if obj["shape"] == "rectangle" and obj.get("size"):
        local = _rectangle_polygon(obj["size"][0], obj["size"][1])
    else:
        local = _rectangle_polygon(1.0, 1.0)
    pose = Pose(**obj["pose"])
    return _place_shape_on_board(local, pose)


# ============================================================================
# Simple obviousness validation via car resizing
# ============================================================================

def resize_instance(instance: Dict[str, Any], delta_px: float) -> Dict[str, Any]:
    """
    Create a copy of the instance with all car dimensions adjusted.
    
    Args:
        instance: The puzzle instance
        delta_px: Amount to add to each side in pixels (positive = larger, negative = smaller)
        
    Returns:
        New instance with resized cars
    """
    delta_units = pixels_to_units(delta_px)
    new_instance = copy.deepcopy(instance)
    
    for obj in new_instance["objects"]:
        if obj.get("size"):
            # Add delta to both length and width (delta on each side = 2*delta total)
            obj["size"][0] = max(0.1, obj["size"][0] + 2 * delta_units)
            obj["size"][1] = max(0.1, obj["size"][1] + 2 * delta_units)
    
    return new_instance


def _compute_max_move_distance(
    state: Dict[str, Any],
    obj_id: str,
    direction: int,
) -> float:
    """
    Calculate how far a car can move in the given direction.
    
    Uses binary search to find the maximum distance before collision.
    
    Args:
        state: Current puzzle state
        obj_id: ID of object to move
        direction: +1 or -1
        
    Returns:
        Maximum distance the car can move
    """
    board_w = state["board"]["width"]
    board_h = state["board"]["height"]
    
    obj = next(o for o in state["objects"] if o["id"] == obj_id)
    axis = obj["local_axis"]
    
    # Get all world polygons
    world_polys = []
    obj_idx = -1
    for i, o in enumerate(state["objects"]):
        if o["shape"] == "rectangle" and o.get("size"):
            local = _rectangle_polygon(o["size"][0], o["size"][1])
        else:
            local = _rectangle_polygon(1.0, 1.0)
        pose = Pose(**o["pose"])
        world_polys.append(_place_shape_on_board(local, pose))
        if o["id"] == obj_id:
            obj_idx = i
    
    start_poly = world_polys[obj_idx]
    board = box(0.0, 0.0, board_w, board_h)
    
    def is_valid_position(t: float) -> bool:
        """Check if moving by t in the direction is valid."""
        dx = axis[0] * direction * t
        dy = axis[1] * direction * t
        moved = translate(start_poly, dx, dy)
        
        # Check board bounds
        if not board.contains(moved):
            return False
        
        # Check collision with other objects
        for j, other_poly in enumerate(world_polys):
            if j == obj_idx:
                continue
            if not moved.disjoint(other_poly):
                return False
        
        return True
    
    # Binary search for max distance
    step = 0.25
    epsilon = 1e-3
    t_max = 0.0
    
    while step > epsilon:
        while is_valid_position(t_max + step):
            t_max += step
        step *= 0.5
    
    return t_max


def _red_car_at_exit(state: Dict[str, Any]) -> bool:
    """Check if the red car has reached the board edge at the exit."""
    exit_info = state["board"]["exits"][0]
    exit_side = exit_info["side"]
    board_w = state["board"]["width"]
    board_h = state["board"]["height"]
    
    red_car = next(o for o in state["objects"] if o["id"] == "red_car")
    red_poly = get_object_polygon(red_car)
    bounds = red_poly.bounds  # (minx, miny, maxx, maxy)
    
    tolerance = 0.1  # Small tolerance for floating point comparison
    
    if exit_side == "right":
        return bounds[2] >= board_w - tolerance  # maxx at right edge
    elif exit_side == "left":
        return bounds[0] <= tolerance  # minx at left edge
    elif exit_side == "top":
        return bounds[3] >= board_h - tolerance  # maxy at top edge
    elif exit_side == "bottom":
        return bounds[1] <= tolerance  # miny at bottom edge
    return False


def execute_abstract_sequence(instance: Dict[str, Any], actions: List[Dict[str, Any]]) -> bool:
    """
    Execute an abstract action sequence and check if red car reaches exit.
    
    Actions are treated as (object_id, direction) only - distances are recalculated
    based on how far each car CAN move in the current state with the (possibly resized) cars.
    
    Args:
        instance: The puzzle instance (possibly with resized cars)
        actions: List of actions with object_id and direction
        
    Returns:
        True if red car reaches exit after executing the sequence
    """
    current_state = copy.deepcopy(instance)
    
    for action in actions:
        obj_id = action["object_id"]
        direction = action["direction"]
        
        # Calculate how far this car can move in this direction
        distance = _compute_max_move_distance(current_state, obj_id, direction)
        
        # Apply move with recalculated distance
        current_state = apply_action(current_state, {
            "object_id": obj_id,
            "direction": direction,
            "distance": distance,
        })
    
    # Check if red car intersects exit
    return _red_car_at_exit(current_state)


def validate_puzzle_obviousness(
    instance: Dict[str, Any],
    actions: List[Dict[str, Any]],
    margin_px: float = 2.0,
) -> Tuple[bool, str]:
    """
    Validate that a puzzle has sufficient margin/clearance.
    
    Tests if the abstract action sequence (object + direction only) still solves
    the puzzle when cars are resized:
    
    1. Inflate cars by margin_px → must still reach exit → sufficient clearance
    2. Deflate cars by margin_px → must still reach exit → sufficient margin
    
    Args:
        instance: The puzzle instance
        actions: The solution actions
        margin_px: Amount to inflate/deflate each side in pixels (default: 2)
        
    Returns:
        (is_valid, reason): Whether puzzle passes both checks
    """
    # Test 1: Inflated cars (clearance check)
    inflated = resize_instance(instance, +margin_px)
    if not execute_abstract_sequence(inflated, actions):
        return False, "Clearance check failed (inflated cars can't reach exit)"
    
    # Test 2: Deflated cars (margin check)
    deflated = resize_instance(instance, -margin_px)
    if not execute_abstract_sequence(deflated, actions):
        return False, "Margin check failed (deflated cars can't reach exit)"
    
    return True, "OK"


def calculate_obviousness_metrics(
    instance: Dict[str, Any],
    actions: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Calculate the maximum margin where both checks still pass.
    
    Uses binary search to find the maximum margin_px value where:
    - Inflated cars can still reach exit
    - Deflated cars can still reach exit
    
    Returns:
        Dict with max_margin_px
    """
    # Binary search for max working margin
    lo = 0.0
    hi = 50.0  # 50px is a reasonable upper bound
    epsilon = 0.5  # 0.5px precision
    
    while hi - lo > epsilon:
        mid = (lo + hi) / 2.0
        is_valid, _ = validate_puzzle_obviousness(instance, actions, margin_px=mid)
        if is_valid:
            lo = mid
        else:
            hi = mid
    
    return {
        "max_margin_px": lo,
    }


def scan_existing_instances(output_dir: Path, min_level: int, max_level: int) -> Tuple[Dict[int, int], int]:
    """
    Scan an existing output directory to find:
    - How many instances exist per level
    - The maximum seed used across all instances
    
    Args:
        output_dir: Path to the output directory
        min_level: Minimum level to scan
        max_level: Maximum level to scan
        
    Returns:
        Tuple of (instance counts per level, max seed found)
    """
    produced: Dict[int, int] = {level: 0 for level in range(min_level, max_level + 1)}
    max_seed = 0
    
    for level in range(min_level, max_level + 1):
        level_dir = output_dir / f"level_{level:02d}"
        if not level_dir.exists():
            continue
            
        # Count puzzles by finding puzzle directories
        puzzle_dirs = sorted(level_dir.glob("puzzle_*"))
        produced[level] = len(puzzle_dirs)
        
        # Find max seed from metadata files
        for puzzle_dir in puzzle_dirs:
            metadata_file = puzzle_dir / "metadata.json"
            if metadata_file.exists():
                try:
                    with open(metadata_file) as f:
                        metadata = json.load(f)
                        seed = metadata.get("seed", 0)
                        max_seed = max(max_seed, seed)
                except (json.JSONDecodeError, IOError):
                    continue
    
    return produced, max_seed


def save_puzzle(
    instance: Dict[str, Any],
    actions: List[Dict[str, Any]],
    level: int,
    puzzle_id: int,
    seed: int,
    output_dir: Path,
) -> None:
    """Save a single puzzle to disk."""
    level_dir = output_dir / f"level_{level:02d}"
    level_dir.mkdir(parents=True, exist_ok=True)
    
    puzzle_dir = level_dir / f"puzzle_{puzzle_id:04d}"
    puzzle_dir.mkdir(parents=True, exist_ok=True)
    
    # Render initial state
    fig = render_instance(instance)
    fig.savefig(puzzle_dir / "initial.png", dpi=200)
    plt.close(fig)
    
    # Generate CoT steps
    cot_files = []
    current_state = instance
    
    for step_idx, action in enumerate(actions):
        current_state = apply_action(current_state, action)
        fig = render_instance(current_state)
        cot_filename = f"cot_{step_idx:02d}.png"
        fig.savefig(puzzle_dir / cot_filename, dpi=200)
        plt.close(fig)
        cot_files.append(cot_filename)
    
    # Calculate obviousness metrics
    obviousness_metrics = calculate_obviousness_metrics(instance, actions)
    
    # Save metadata
    metadata = {
        "puzzle_id": puzzle_id,
        "level": level,
        "num_cot_images": len(cot_files),
        "num_actions": len(actions),
        "seed": seed,
        "initial_state_image": "initial.png",
        "cot_images": cot_files,
        "actions": actions,
        "solution_length": len(actions),
        "board": instance["board"],
        "objects": instance["objects"],
        "obviousness_metrics": obviousness_metrics,
    }
    
    with open(puzzle_dir / "metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)


def generate_all_levels(
    min_level: int,
    max_level: int,
    instances_per_level: int,
    output_dir: Path,
    seed: int,
    max_attempts: int = 700000,
    initial_counts: Dict[int, int] = None,
    margin_px: Optional[float] = None,
) -> Dict[int, int]:
    """
    Generate puzzles for all levels efficiently by reusing "mismatched" puzzles.
    
    When generating for a target level, if we get a puzzle with a different
    action count that fits another level we need, we save it there instead
    of discarding it.
    
    Puzzle IDs are assigned sequentially (1, 2, 3, ...) within each level.
    
    Args:
        min_level: Minimum level (actions) to generate
        max_level: Maximum level (actions) to generate  
        instances_per_level: Number of instances per level
        output_dir: Base output directory
        seed: Starting random seed
        max_attempts: Maximum total attempts
        initial_counts: Optional dict with existing puzzle counts per level (for resuming)
        margin_px: Margin in pixels for obviousness check (None to disable filtering)
        
    Returns:
        Dict mapping level -> number of instances generated
    """
    # Track how many puzzles we have per level
    if initial_counts is not None:
        produced: Dict[int, int] = initial_counts.copy()
    else:
        produced: Dict[int, int] = {level: 0 for level in range(min_level, max_level + 1)}
    
    # Track rejected puzzles for obviousness
    obviousness_rejections = 0
    
    current_seed = seed
    attempts = 0
    
    # Determine if obviousness filtering is enabled
    filter_enabled = margin_px is not None
    
    print(f"\n  Generating levels {min_level}-{max_level} ({instances_per_level} instances each)")
    print(f"  Strategy: reuse puzzles that don't match target level")
    if filter_enabled:
        print(f"  Obviousness filter enabled: margin={margin_px:.1f} px")
    else:
        print(f"  Obviousness filter: disabled")
    
    def all_levels_complete() -> bool:
        return all(produced[level] >= instances_per_level for level in produced)
    
    def levels_still_needed() -> List[int]:
        return [level for level in produced if produced[level] < instances_per_level]
    
    while not all_levels_complete() and attempts < max_attempts:
        # Pick a difficulty stage that's likely to produce levels we still need
        needed = levels_still_needed()
        
        # Map needed levels to appropriate stages
        # Level 1 -> stage 1
        # Level 2 -> stage 2, 3
        # Level 3+ -> stage 4, 5
        if 1 in needed:
            stage = 1
        elif 2 in needed:
            stage = 2 if attempts % 2 == 0 else 3
        else:
            # For levels 3+, use higher stages
            stage = 4 if attempts % 2 == 0 else 5
        
        try:
            instance = generate_initial_state(
                seed=current_seed,
                difficulty_stage=stage,
            )
        except RuntimeError:
            attempts += 1
            current_seed += 1
            continue
        
        try:
            # Allow solutions up to max_level actions
            actions = compute_greedy_solution(instance, max_actions=max_level)
        except RuntimeError:
            attempts += 1
            current_seed += 1
            continue
        
        num_actions = len(actions)
        
        # Check if this puzzle fits any level we still need
        if min_level <= num_actions <= max_level and produced[num_actions] < instances_per_level:
            
            # Validate obviousness if filtering is enabled
            if filter_enabled:
                is_valid, reason = validate_puzzle_obviousness(
                    instance, actions, margin_px=margin_px
                )
                if not is_valid:
                    obviousness_rejections += 1
                    attempts += 1
                    current_seed += 1
                    continue
            
            # Puzzle ID is 1-indexed: 1, 2, 3, ...
            puzzle_id = produced[num_actions] + 1
            save_puzzle(instance, actions, num_actions, puzzle_id, current_seed, output_dir)
            
            produced[num_actions] += 1
            
            print(f"    ✓ Level {num_actions} puzzle {puzzle_id:04d} (seed={current_seed}, stage={stage})")
        
        attempts += 1
        current_seed += 1
        
        # Progress update
        if attempts % 500 == 0:
            status = ", ".join(f"L{l}:{produced[l]}/{instances_per_level}" for l in sorted(produced.keys()))
            reject_info = f", obviousness_rejections={obviousness_rejections}" if filter_enabled else ""
            print(f"    Progress after {attempts} attempts: {status}{reject_info}")
    
    # Final summary
    print(f"\n  Generation complete after {attempts} attempts:")
    for level in sorted(produced.keys()):
        status = "✓" if produced[level] >= instances_per_level else "⚠"
        print(f"    Level {level}: {produced[level]}/{instances_per_level} {status}")
    if filter_enabled:
        print(f"  Obviousness rejections: {obviousness_rejections}")
    
    return produced

def main():
    parser = argparse.ArgumentParser(description="Rush Hour Variant dataset generator (per-level)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--instances", type=int, default=50, help="Instances per level")
    parser.add_argument("--min-level", type=int, default=1, help="Minimum level (actions)")
    parser.add_argument("--max-level", type=int, default=5, help="Maximum level (actions)")
    parser.add_argument("--level", type=int, default=None, help="Generate only this specific level")
    parser.add_argument("--max-attempts", type=int, default=7000000, help="Max total attempts")
    parser.add_argument("--output-dir", type=str, default="output", help="Base output directory")
    parser.add_argument("--resume-from", type=str, default=None, 
                        help="Resume from existing output directory (scans for existing instances and continues)")
    # Obviousness filtering - simple margin-based check
    parser.add_argument("--margin", type=float, default=2.0,
                        help="Margin in pixels for obviousness check. Solution must work with cars +/- this margin (default: 2)")
    parser.add_argument("--no-obviousness-filter", action="store_true",
                        help="Disable obviousness filtering entirely")
    args = parser.parse_args()

    base_outdir = Path(args.output_dir)
    
    # Determine level range
    if args.level is not None:
        min_level = args.level
        max_level = args.level
    else:
        min_level = args.min_level
        max_level = args.max_level
    
    # Check if resuming from existing run
    initial_counts = None
    start_seed = args.seed
    
    if args.resume_from:
        resume_dir = Path(args.resume_from)
        if not resume_dir.exists():
            print(f"Error: Resume directory '{resume_dir}' does not exist")
            return
        
        print("=" * 60)
        print("Scanning existing instances for resume...")
        print("=" * 60)
        
        initial_counts, max_seed = scan_existing_instances(resume_dir, min_level, max_level)
        start_seed = max_seed + 1  # Continue from next seed
        
        print(f"Found existing instances:")
        for level in sorted(initial_counts.keys()):
            print(f"  Level {level}: {initial_counts[level]} instances")
        print(f"Max seed found: {max_seed}")
        print(f"Will continue from seed: {start_seed}")
        print("=" * 60)
        
        # Use resume directory as output if output-dir wasn't explicitly set
        if args.output_dir == "output":
            base_outdir = resume_dir
            print(f"Output directory: {base_outdir}")
    
    # Determine obviousness filter settings
    margin_px = None if args.no_obviousness_filter else args.margin
    
    print("=" * 60)
    print("Rush Hour Variant - Per-Level Dataset Generator")
    print("=" * 60)
    print(f"Levels: {min_level}-{max_level}")
    print(f"Instances per level: {args.instances}")
    print(f"Starting seed: {start_seed}")
    if margin_px is not None:
        print(f"Obviousness filter: margin={margin_px:.1f} px")
    else:
        print(f"Obviousness filter: disabled")
    if initial_counts:
        remaining = {l: max(0, args.instances - initial_counts[l]) for l in initial_counts}
        print(f"Remaining to generate: {remaining}")
    print("=" * 60)
    
    # Use the efficient resampling approach for all cases
    level_stats = generate_all_levels(
        min_level=min_level,
        max_level=max_level,
        instances_per_level=args.instances,
        output_dir=base_outdir,
        seed=start_seed,
        max_attempts=args.max_attempts,
        initial_counts=initial_counts,
        margin_px=margin_px,
    )
    
    # Save level metadata for each level
    for level, count in level_stats.items():
        level_dir = base_outdir / f"level_{level:02d}"
        level_metadata = {
            "level": level,
            "num_cot_images": level,
            "num_actions": level,
            "instances_generated": count,
            "instances_requested": args.instances,
            "chance_performance": CHANCE_PERFORMANCE.get(f"level_{level:02d}", 0.5),
        }
        with open(level_dir / "level_metadata.json", "w") as f:
            json.dump(level_metadata, f, indent=2)
    
    total = sum(level_stats.values())
    print(f"\nTotal: {total} instances across {len(level_stats)} levels")
    print("=" * 60)


if __name__ == "__main__":
    main()
