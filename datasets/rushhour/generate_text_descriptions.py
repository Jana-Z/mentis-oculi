#!/usr/bin/env python3
"""
Generate text descriptions of Rush Hour puzzles from metadata.json files.

This script reads the metadata.json for each generated level and converts
the puzzle information into a human-readable text format that can be used
as input for language models.

The text description is saved as 'text_description.txt' in each instance directory.

Usage:
    uv run generate_text_descriptions.py --input-dir output
    uv run generate_text_descriptions.py --input-dir output/level_03
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Dict, Any, List, Tuple

from shapely.affinity import rotate, translate
from shapely.geometry import box


def _rectangle_polygon(length: float, width: float):
    """Create a rectangle polygon centered at origin."""
    half_l = length / 2.0
    half_w = width / 2.0
    return box(-half_l, -half_w, half_l, half_w)


def _place_shape_on_board(local_poly, pose: Dict[str, float]):
    """Transform local polygon to world coordinates."""
    theta_deg = pose["theta"] * 180.0 / math.pi
    world = rotate(local_poly, theta_deg, origin=(0.0, 0.0), use_radians=False)
    world = translate(world, pose["x"], pose["y"])
    return world


def get_bounding_box(obj: Dict[str, Any]) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """
    Compute the axis-aligned bounding box of an object in world coordinates.
    Returns ((min_x, min_y), (max_x, max_y)).
    """
    if obj["shape"] == "rectangle" and obj.get("size"):
        local_poly = _rectangle_polygon(obj["size"][0], obj["size"][1])
    else:
        # Fallback for unknown shapes
        local_poly = _rectangle_polygon(1.0, 1.0)
    
    world_poly = _place_shape_on_board(local_poly, obj["pose"])
    bounds = world_poly.bounds  # (minx, miny, maxx, maxy)
    return ((bounds[0], bounds[1]), (bounds[2], bounds[3]))


def get_car_properties(obj: Dict[str, Any]) -> Tuple[Tuple[float, float], float, float]:
    """
    Get the center point, length (along movement axis), and width of a car.
    Returns (center, length, width).
    
    Note: length is the dimension along the car's movement axis (size[0]),
    width is perpendicular to it (size[1]).
    """
    # Center is directly from the pose
    center = (obj["pose"]["x"], obj["pose"]["y"])
    
    # Size: [length, width] where length is along movement axis
    if obj.get("size"):
        length = obj["size"][0]
        width = obj["size"][1]
    else:
        length = 1.0
        width = 1.0
    
    return center, length, width


def format_coord(value: float, decimals: int = 2) -> str:
    """Format a coordinate value with specified decimal places."""
    return f"{value:.{decimals}f}"


def format_bbox(bbox: Tuple[Tuple[float, float], Tuple[float, float]], decimals: int = 2) -> str:
    """Format bounding box as ((x1, y1), (x2, y2))."""
    (x1, y1), (x2, y2) = bbox
    return f"(({format_coord(x1, decimals)}, {format_coord(y1, decimals)}), ({format_coord(x2, decimals)}, {format_coord(y2, decimals)}))"


def format_point(point: Tuple[float, float], decimals: int = 2) -> str:
    """Format a point as (x, y)."""
    return f"({format_coord(point[0], decimals)}, {format_coord(point[1], decimals)})"


def format_axis(axis: List[float], decimals: int = 2) -> str:
    """Format axis vector."""
    return f"({format_coord(axis[0], decimals)}, {format_coord(axis[1], decimals)})"


def theta_to_degrees(theta_rad: float) -> float:
    """Convert radians to degrees."""
    return theta_rad * 180.0 / math.pi


def generate_description(metadata: Dict[str, Any]) -> str:
    """
    Generate a text description of a Rush Hour puzzle from its metadata.
    """
    lines = []
    
    # Board description
    board = metadata["board"]
    lines.append(f"The parking lot has a size of {int(board['width'])} by {int(board['height'])}.")
    lines.append("")
    
    # Exit description
    for exit_info in board["exits"]:
        exit_x = exit_info["x"]
        exit_y = exit_info["y"]
        exit_w = exit_info["w"]
        exit_h = exit_info["h"]
        
        # Determine which edge the exit is on
        if exit_x == 0 and exit_w == 0:
            edge = "left (x=0)"
            span = f"from y={format_coord(exit_y)} to y={format_coord(exit_y + exit_h)}"
        elif exit_x == board["width"] or (exit_x + exit_w == board["width"] and exit_w == 0):
            edge = "right (x=10)"
            span = f"from y={format_coord(exit_y)} to y={format_coord(exit_y + exit_h)}"
        elif exit_y == 0 and exit_h == 0:
            edge = "bottom (y=0)"
            span = f"from x={format_coord(exit_x)} to x={format_coord(exit_x + exit_w)}"
        elif exit_y == board["height"] or (exit_y + exit_h == board["height"] and exit_h == 0):
            edge = "top (y=10)"
            span = f"from x={format_coord(exit_x)} to x={format_coord(exit_x + exit_w)}"
        else:
            print(f"Unknown exit: {exit_info}")
            edge = "unknown"
            span = f"at ({format_coord(exit_x)}, {format_coord(exit_y)})"
        
        lines.append(f"There is an exit on the {edge} edge, {span}.")
    lines.append("")
    
    # Sort objects: red_car first, then movable objects by label, then static objects
    objects = metadata["objects"]
    red_car = None
    movable_objects = []
    static_objects = []
    
    for obj in objects:
        if obj["id"] == "red_car":
            red_car = obj
        elif obj.get("movable", True):
            movable_objects.append(obj)
        else:
            static_objects.append(obj)
    
    # Sort movable objects by label
    movable_objects.sort(key=lambda o: o.get("label", "Z"))
    
    # Red car description
    if red_car:
        center, length, width = get_car_properties(red_car)
        theta_deg = theta_to_degrees(red_car["pose"]["theta"])
        axis = red_car["local_axis"]
        neg_axis = [-axis[0], -axis[1]]
        
        lines.append(
            f"There is a red car (R) at center {format_point(center)} "
            f"with length {format_coord(length)} and width {format_coord(width)}, "
            f"rotated by {format_coord(theta_deg, 1)} degrees, "
            f"i.e. the car can move forwards along the {format_axis(axis)} axis "
            f"and backwards along {format_axis(neg_axis)}."
        )
    
    # Other movable objects
    for obj in movable_objects:
        center, length, width = get_car_properties(obj)
        theta_deg = theta_to_degrees(obj["pose"]["theta"])
        axis = obj["local_axis"]
        neg_axis = [-axis[0], -axis[1]]
        label = obj.get("label", obj["id"])
        
        lines.append(
            f"There is a car ({label}) at center {format_point(center)} "
            f"with length {format_coord(length)} and width {format_coord(width)}, "
            f"rotated by {format_coord(theta_deg, 1)} degrees, "
            f"i.e. the car can move forwards along the {format_axis(axis)} axis "
            f"and backwards along {format_axis(neg_axis)}."
        )
    
    # Static objects
    for obj in static_objects:
        bbox = get_bounding_box(obj)
        lines.append(f"There is a static, immovable object at {format_bbox(bbox)}.")
    
    return "\n".join(lines)


def process_puzzle(puzzle_dir: Path) -> bool:
    """
    Process a single puzzle directory and generate its text description.
    Saves the description as 'text_description.txt' in the same directory.
    Returns True if successful, False otherwise.
    """
    metadata_path = puzzle_dir / "metadata.json"
    if not metadata_path.exists():
        print(f"  [SKIP] No metadata.json in {puzzle_dir}")
        return False
    
    try:
        with open(metadata_path, "r") as f:
            metadata = json.load(f)
    except json.JSONDecodeError as e:
        print(f"  [ERROR] Failed to parse {metadata_path}: {e}")
        return False
    
    # Generate description
    description = generate_description(metadata)
    
    # Save in the same directory as metadata.json
    output_path = puzzle_dir / "text_description.txt"
    
    with open(output_path, "w") as f:
        f.write(description)
    
    return True


def process_level(level_dir: Path) -> int:
    """
    Process all instances in a level directory.
    Returns the number of successfully processed instances.
    """
    puzzle_dirs = sorted([d for d in level_dir.iterdir() if d.is_dir() and d.name.startswith("puzzle_")])
    
    if not puzzle_dirs:
        print(f"  [SKIP] No puzzle directories found in {level_dir}")
        return 0
    
    success_count = 0
    for puzzle_dir in puzzle_dirs:
        if process_puzzle(puzzle_dir):
            success_count += 1
    
    return success_count


def main():
    parser = argparse.ArgumentParser(
        description="Generate text descriptions of Rush Hour puzzles from metadata.json files."
    )
    parser.add_argument(
        "--input-dir",
        type=str,
        default="output",
        help="Input directory containing level_XX folders or puzzle_XXXX folders (default: output)"
    )
    
    args = parser.parse_args()
    
    input_dir = Path(args.input_dir)
    
    if not input_dir.exists():
        print(f"Error: Input directory '{input_dir}' does not exist.")
        return 1
    
    print(f"Input directory: {input_dir}")
    print()
    
    total_success = 0
    
    # Check if input_dir contains level_XX directories
    level_dirs = sorted([d for d in input_dir.iterdir() if d.is_dir() and d.name.startswith("level_")])
    
    if level_dirs:
        # Process each level directory
        for level_dir in level_dirs:
            print(f"Processing {level_dir.name}...")
            count = process_level(level_dir)
            print(f"  ✓ Generated {count} descriptions")
            total_success += count
    else:
        # Check if input_dir contains puzzle_XXXX directories directly
        puzzle_dirs = sorted([d for d in input_dir.iterdir() if d.is_dir() and d.name.startswith("puzzle_")])
        
        if puzzle_dirs:
            print(f"Processing puzzles in {input_dir}...")
            count = process_level(input_dir)
            print(f"  ✓ Generated {count} descriptions")
            total_success += count
        else:
            print(f"Error: No level_XX or puzzle_XXXX directories found in '{input_dir}'")
            return 1
    
    print()
    print(f"Total: {total_success} text descriptions generated (saved as text_description.txt in each instance folder)")
    
    return 0


if __name__ == "__main__":
    exit(main())
