import random
import os
import json
from tqdm import tqdm
from PIL import Image
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from pathlib import Path
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.affinity import rotate as shapely_rotate, translate as shapely_translate
from shapely.ops import unary_union

# Official color palette (datasets/README.md)
CERULEAN = "#0090C1"      # Primary brand
RASPBERRY = "#E85D75"     # Highlight / goal
AQUAMARINE = "#2EC4B6"    # Movable secondary
SUNSHINE = "#FFD670"      # Helper / reference
MIDNIGHT = "#1B263B"      # Outlines / text
CANVAS_BG = "#FDFDFD"     # Light background per style guide
CANVAS_SIZE = (6, 6)

PALETTE = [CERULEAN, RASPBERRY, AQUAMARINE, SUNSHINE]  # exclude MIDNIGHT for fills

# Rejection sampling: max fraction of a piece's area that may be covered by other pieces (final config)
MAX_OVERLAP_RATIO = 0.7


def assign_piece_colors(num_pieces, rng):
    """Assign stable, per-piece colors from the palette (excluding MIDNIGHT)."""
    # Cycle if there are more pieces than colors
    colors = [PALETTE[i % len(PALETTE)] for i in range(num_pieces)]
    # Optional: shuffle deterministically for variety
    rng.shuffle(colors)
    return colors


def generate_hinge_folding_dataset(output_dir,
    num_samples=7000,
    min_pieces=2,
    max_pieces=5,
    seed=42,
):
    """
    Generate synthetic hinge folding dataset.
    
    Each sample includes:
    - Initial configuration: chain of shapes connected by hinges
    - Target: final folded configuration
    - Solution: sequence of hinge rotations (hinge_id, angle)
    - Chain of thought: intermediate images showing progressive folding
    """
    
    random.seed(seed)
    np.random.seed(seed)
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    dataset_samples = []
    
    # Define possible base shapes
    base_shapes = {
        "square": {"type": "square", "size": 1.0},
        "diamond": {"type": "diamond", "size": 1.0},
        "triangle": {"type": "triangle", "size": 1.0},
        "rectangle": {"type": "rectangle", "width": 1.0, "height": 0.5}
    }
    
    # Define rotation patterns (90-degree intervals: 90, 180, 270)
    # Available angles in 90-degree steps
    angle_options = [90, 180, 270]
    
    print(f"Generating {num_samples} hinge folding samples...")
    
    for sample_idx in tqdm(range(num_samples)):
        # Make a per-sample RNG so color assignment is stable but varied across samples
        rng = random.Random((seed + 137) * (sample_idx + 1))

        # Random configuration
        num_pieces = random.randint(min_pieces, max_pieces)
        num_hinges = num_pieces - 1
        
        # Sample shape for each piece independently (one at a time)
        shape_chain = []
        shape_names = []
        for _ in range(num_pieces):
            shape_name = random.choice(list(base_shapes.keys()))
            shape_chain.append(base_shapes[shape_name])
            shape_names.append(shape_name)
        
        # Assign per-piece colors (consistent across initial/CoT/metadata)
        piece_colors = assign_piece_colors(num_pieces, rng)

        # Rejection sampling: choose rotation pattern so final config has no piece >80% overlapped
        MAX_VISIBILITY_RETRIES = 100
        rotation_angles = None
        for _ in range(MAX_VISIBILITY_RETRIES):
            candidate_angles = [random.choice(angle_options) for _ in range(num_hinges)]
            initial_positions_raw = _calculate_initial_positions(shape_chain, scale=1.0, center_offset=(0, 0))
            final_positions = calculate_folded_positions(shape_chain, initial_positions_raw, candidate_angles, scale=1.0)
            if _visibility_ok(shape_chain, final_positions, scale=1.0):
                rotation_angles = candidate_angles
                break
        if rotation_angles is None:
            continue  # skip this sample after exhausting retries

        # Generate puzzle directory (1-indexed)
        puzzle_id = f"puzzle_{sample_idx + 1:04d}"
        puzzle_dir = output_path / puzzle_id
        puzzle_dir.mkdir(exist_ok=True)
        
        # Generate images
        initial_image_path = puzzle_dir / "initial.png"
        target_image_path = puzzle_dir / "target.png"
        combined_image_path = puzzle_dir / "combined.png"
        cot_image_paths = []
        
        # Calculate unified bounds for consistent aspect ratio across all images
        # Step 1: Calculate initial positions without centering to get the raw chain size
        raw_initial_positions = _calculate_initial_positions(shape_chain, scale=1.0, center_offset=(0, 0))
        
        # Calculate bounding box of initial chain
        initial_bounds_x = []
        initial_bounds_y = []
        for i, (x, y) in enumerate(raw_initial_positions):
            size = shape_chain[i].get("size", 1.0)
            initial_bounds_x.extend([x - size, x + size])
            initial_bounds_y.extend([y - size, y + size])
        
        # Calculate center offset to center the initial chain at origin
        initial_center_x = (min(initial_bounds_x) + max(initial_bounds_x)) / 2
        initial_center_y = (min(initial_bounds_y) + max(initial_bounds_y)) / 2
        center_offset = (-initial_center_x, -initial_center_y)
        
        # Step 2: Recalculate with centered positions
        initial_positions = _calculate_initial_positions(shape_chain, scale=1.0, center_offset=center_offset)
        
        # Calculate bounds across all states (initial + all CoT steps + target)
        all_bounds_x = []
        all_bounds_y = []
        
        # Initial state bounds
        for i, (x, y) in enumerate(initial_positions):
            size = shape_chain[i].get("size", 1.0)
            all_bounds_x.extend([x - size, x + size])
            all_bounds_y.extend([y - size, y + size])
        
        # CoT and target state bounds
        for step in range(len(rotation_angles) + 1):
            rotations = rotation_angles[:step] if step > 0 else []
            positions = calculate_folded_positions(shape_chain, initial_positions, rotations)
            for i, (x, y, angle) in enumerate(positions):
                size = shape_chain[i].get("size", 1.0)
                all_bounds_x.extend([x - size, x + size])
                all_bounds_y.extend([y - size, y + size])
        
        # Calculate bounds with margin and apply scaling to maximize canvas usage
        margin = 0.5
        raw_width = max(all_bounds_x) - min(all_bounds_x)
        raw_height = max(all_bounds_y) - min(all_bounds_y)
        
        # Scale to fill ~70% of the 6x6 canvas (leaving room for margins and folding)
        target_size = 4.0
        scale_factor = min(target_size / max(raw_width, raw_height), 2.0)  # Cap at 2x to avoid too large
        
        # Apply scaling to bounds
        bounds = {
            'xmin': min(all_bounds_x) * scale_factor - margin,
            'xmax': max(all_bounds_x) * scale_factor + margin,
            'ymin': min(all_bounds_y) * scale_factor - margin,
            'ymax': max(all_bounds_y) * scale_factor + margin
        }
        
        # Scale the positions
        initial_positions = [(x * scale_factor, y * scale_factor) for x, y in initial_positions]
        
        # Create initial image with unified bounds
        create_initial_image(initial_image_path, shape_chain, num_hinges, piece_colors, bounds, scale_factor, initial_positions)
        
        # Create target image with unified bounds
        create_target_image(target_image_path, shape_chain, initial_positions, rotation_angles, bounds, scale_factor)
        
        # Create combined image (initial on left, target on right)
        create_combined_image(combined_image_path, initial_image_path, target_image_path)
        
        # Create chain of thought images with unified bounds
        rotation_steps = []
        for i, angle in enumerate(rotation_angles):
            cot_image_path = puzzle_dir / f"cot_{i:02d}.png"
            cot_image_paths.append(str(cot_image_path))
            create_cot_image(cot_image_path, shape_chain, initial_positions, rotation_angles[:i+1], piece_colors, bounds, scale_factor)
            
            rotation_steps.append({
                "hinge_id": chr(ord('A') + i),
                "angle": angle
            })
        
        # Format rotation sequence
        rotation_sequence = ", ".join([f"{chr(ord('A') + i)} {angle}" for i, angle in enumerate(rotation_angles)])
        
        # Create metadata
        metadata = {
            "puzzle_id": puzzle_id,
            "num_pieces": num_pieces,
            "num_hinges": num_hinges,
            "shape_chain": shape_names,  # List of shape names for each piece
            "rotation_angles": rotation_angles,
            "rotation_steps": rotation_steps,
            "rotation_sequence": rotation_sequence,
            "piece_colors": piece_colors,  # ensure colors are discoverable later
            "initial_image": str(initial_image_path.relative_to(output_path)),
            "target_image": str(target_image_path.relative_to(output_path)),
            "combined_image": str(combined_image_path.relative_to(output_path)),
            "cot_images": [str(Path(p).relative_to(output_path)) for p in cot_image_paths]
        }
        
        # Save metadata
        with open(puzzle_dir / "metadata.json", 'w') as f:
            json.dump(metadata, f, indent=2)
        
        dataset_samples.append({
            "puzzle_id": puzzle_id,
            "puzzle_path": str(puzzle_dir.relative_to(output_path))
        })
    
    # Save dataset index
    with open(output_path / "dataset_index.json", 'w') as f:
        json.dump({
            "total_samples": num_samples,
            "min_pieces": min_pieces,
            "max_pieces": max_pieces,
            "samples": dataset_samples
        }, f, indent=2)
    
    print(f"✅ Generated {num_samples} hinge folding samples in {output_dir}")
    return output_path


def _calculate_initial_positions(shape_chain, scale=1.0, center_offset=(0, 0)):
    """Calculate initial positions for shape chain without drawing.
    
    Args:
        shape_chain: List of shape configs
        scale: Scaling factor for the shapes (default 1.0)
        center_offset: (x, y) offset to center the chain (default (0, 0))
    """
    positions = []
    for i, shape in enumerate(shape_chain):
        if i == 0:
            positions.append((0, 0))
        else:
            prev_x, prev_y = positions[i-1]
            right_conn_x, right_conn_y = get_shape_right_connection_point(shape_chain[i-1], prev_x, prev_y)
            temp_left_x, temp_left_y = get_shape_left_connection_point(shape, 0, 0)
            curr_x = right_conn_x - temp_left_x
            curr_y = right_conn_y - temp_left_y
            positions.append((curr_x, curr_y))
    
    # Apply centering offset
    positions = [(x + center_offset[0], y + center_offset[1]) for x, y in positions]
    
    return positions


def _shape_to_polygon(shape_config, x, y, rotation_degrees=0, scale=1.0):
    """Return a Shapely Polygon for one piece at (x, y) with rotation and scale (mirrors draw_shape geometry)."""
    shape_type = shape_config["type"]
    size = shape_config.get("size", 1.0) * scale

    if shape_type in ("diamond", "square"):
        angle_offset = 45 if shape_type == "diamond" else 0
        corners = []
        for i in range(4):
            angle_deg = angle_offset + i * 90
            angle_rad = np.radians(angle_deg)
            corners.append((size * np.cos(angle_rad) * 0.5, size * np.sin(angle_rad) * 0.5))
        poly = ShapelyPolygon(corners)
    elif shape_type == "triangle":
        corners = []
        for i in range(3):
            angle_deg = i * 120
            angle_rad = np.radians(angle_deg)
            corners.append((size * np.cos(angle_rad) * 0.5, size * np.sin(angle_rad) * 0.5))
        poly = ShapelyPolygon(corners)
    elif shape_type == "rectangle":
        width = shape_config.get("width", 1.0) * scale
        height = shape_config.get("height", 0.5) * scale
        corners = [
            (-width / 2, -height / 2),
            (width / 2, -height / 2),
            (width / 2, height / 2),
            (-width / 2, height / 2),
        ]
        poly = ShapelyPolygon(corners)
    else:
        # fallback square
        corners = [(size * 0.5, size * 0.5), (-size * 0.5, size * 0.5), (-size * 0.5, -size * 0.5), (size * 0.5, -size * 0.5)]
        poly = ShapelyPolygon(corners)

    poly = shapely_rotate(poly, rotation_degrees, origin=(0, 0), use_radians=False)
    poly = shapely_translate(poly, xoff=x, yoff=y)
    return poly


def _visibility_ok(shape_chain, positions, scale=1.0, max_overlap_ratio=MAX_OVERLAP_RATIO):
    """Return True iff in this configuration no piece has more than max_overlap_ratio of its area covered by others."""
    n = len(shape_chain)
    polygons = []
    for i in range(n):
        x, y, angle = positions[i]
        poly = _shape_to_polygon(shape_chain[i], x, y, rotation_degrees=angle, scale=scale)
        polygons.append(poly)

    for i in range(n):
        area_i = polygons[i].area
        if area_i <= 0:
            continue
        others = [polygons[j] for j in range(n) if j != i]
        if not others:
            continue
        union_others = unary_union(others)
        intersection = polygons[i].intersection(union_others)
        overlap_area = intersection.area if not intersection.is_empty else 0.0
        ratio = overlap_area / area_i
        if ratio > max_overlap_ratio:
            return False
    return True


def get_shape_right_edge(shape_config, x, y):
    """Get the rightmost edge/corner point of a shape for hinge placement
    Returns (x, y) coordinates of the connection point"""
    shape_type = shape_config["type"]
    size = shape_config.get("size", 1.0)
    
    if shape_type == "square":
        return x + size * 0.5, y
    elif shape_type == "diamond":
        angle = np.radians(315)
        return x + size * np.cos(angle) * 0.5, y + size * np.sin(angle) * 0.5
    elif shape_type == "triangle":
        return x + size * 0.5, y
    elif shape_type == "rectangle":
        width = shape_config.get("width", 1.0)
        return x + width / 2, y
    else:
        return x + size * 0.5, y


def get_shape_left_edge(shape_config, x, y):
    """Get the leftmost edge/corner point of a shape for hinge placement
    Returns (x, y) coordinates of the connection point"""
    shape_type = shape_config["type"]
    size = shape_config.get("size", 1.0)
    
    if shape_type == "square":
        return x - size * 0.5, y
    elif shape_type == "diamond":
        angle = np.radians(225)
        return x + size * np.cos(angle) * 0.5, y + size * np.sin(angle) * 0.5
    elif shape_type == "triangle":
        angle = np.radians(180)
        return x + size * np.cos(angle) * 0.5, y
    elif shape_type == "rectangle":
        width = shape_config.get("width", 1.0)
        return x - width / 2, y
    else:
        return x - size * 0.5, y


def get_shape_width(shape_config):
    """Get the full width of a shape (distance from leftmost to rightmost point)"""
    shape_type = shape_config["type"]
    size = shape_config.get("size", 1.0)
    
    if shape_type == "square":
        return size
    elif shape_type == "diamond":
        return size * np.sqrt(2) / 2
    elif shape_type == "triangle":
        return size * 0.75
    elif shape_type == "rectangle":
        return shape_config.get("width", 1.0)
    else:
        return size


def get_shape_right_connection_point(shape_config, center_x, center_y, scale=1.0, rotation=0):
    """Get the (x, y) coordinates of the right connection point, accounting for rotation"""
    shape_type = shape_config["type"]
    size = shape_config.get("size", 1.0) * scale
    
    # Calculate offset from center in unrotated coordinates
    if shape_type == "square":
        offset_x, offset_y = size * 0.5, 0
    elif shape_type == "diamond":
        # Diamond: midpoint between 45° and 315° corners (right edge midpoint on horizontal)
        offset_x, offset_y = size * np.cos(np.radians(45)) * 0.5, 0
    elif shape_type == "triangle":
        # Triangle: right apex at 0°
        offset_x, offset_y = size * 0.5, 0
    elif shape_type == "rectangle":
        width = shape_config.get("width", 1.0) * scale
        offset_x, offset_y = width / 2, 0
    else:
        offset_x, offset_y = size * 0.5, 0
    
    # Rotate the offset by the shape's rotation
    rot_rad = np.radians(rotation)
    rotated_offset_x = offset_x * np.cos(rot_rad) - offset_y * np.sin(rot_rad)
    rotated_offset_y = offset_x * np.sin(rot_rad) + offset_y * np.cos(rot_rad)
    
    return center_x + rotated_offset_x, center_y + rotated_offset_y


def get_shape_left_connection_point(shape_config, center_x, center_y, scale=1.0, rotation=0):
    """Get the (x, y) coordinates of the left connection point, accounting for rotation"""
    shape_type = shape_config["type"]
    size = shape_config.get("size", 1.0) * scale
    
    # Calculate offset from center in unrotated coordinates
    if shape_type == "square":
        offset_x, offset_y = -size * 0.5, 0
    elif shape_type == "diamond":
        # Diamond: midpoint between 135° and 225° corners (left edge midpoint on horizontal)
        offset_x, offset_y = -size * np.cos(np.radians(45)) * 0.5, 0
    elif shape_type == "triangle":
        # Triangle: left edge midpoint at x = center_x - size/4 (between 120° and 240° corners)
        offset_x, offset_y = -size * 0.25, 0
    elif shape_type == "rectangle":
        width = shape_config.get("width", 1.0) * scale
        offset_x, offset_y = -width / 2, 0
    else:
        offset_x, offset_y = -size * 0.5, 0
    
    # Rotate the offset by the shape's rotation
    rot_rad = np.radians(rotation)
    rotated_offset_x = offset_x * np.cos(rot_rad) - offset_y * np.sin(rot_rad)
    rotated_offset_y = offset_x * np.sin(rot_rad) + offset_y * np.cos(rot_rad)
    
    return center_x + rotated_offset_x, center_y + rotated_offset_y


def create_initial_image(output_path, shape_chain, num_hinges, piece_colors, bounds, scale=1.0, positions=None):
    """Create initial configuration image with letter-labeled hinges"""
    fig, ax = plt.subplots(figsize=CANVAS_SIZE)
    ax.set_aspect('equal')
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_frame_on(True)
    # Add subtle frame border like rush_hour
    for spine in ax.spines.values():
        spine.set_edgecolor(MIDNIGHT)
        spine.set_linewidth(1.0)
    
    # Set unified bounds for consistent aspect ratio
    ax.set_xlim(bounds['xmin'], bounds['xmax'])
    ax.set_ylim(bounds['ymin'], bounds['ymax'])
    
    # Use provided positions or calculate them
    if positions is None:
        positions = _calculate_initial_positions(shape_chain)
    
    # Draw pieces with stable per-piece colors
    for i, (pos, shape) in enumerate(zip(positions, shape_chain)):
        x, y = pos
        draw_shape(ax, x, y, shape, facecolor=piece_colors[i], alpha=0.75, scale=scale)
        
        # Draw hinge marker BETWEEN shapes (at connection point)
        if i < num_hinges:
            # Calculate connection points with proper scaling
            right_x, right_y = get_shape_right_connection_point(shape, x, y, scale)
            next_x, next_y = positions[i+1]
            left_x, left_y = get_shape_left_connection_point(shape_chain[i+1], next_x, next_y, scale)
            hinge_x = (right_x + left_x) / 2
            hinge_y = (right_y + left_y) / 2
            
            # Hinge circle and label (using letters like rush_hour)
            hinge_label = chr(ord('A') + i)
            ax.text(hinge_x, hinge_y, hinge_label, color='white', fontsize=10, ha='center', va='center', weight='bold', bbox=dict(boxstyle="circle,pad=0.15", fc="#00000080", ec="none"), zorder=3)
    
    fig.tight_layout()
    plt.savefig(output_path, bbox_inches='tight', facecolor=CANVAS_BG, dpi=200)
    plt.close()


def create_target_image(output_path, shape_chain, initial_positions, all_rotations, bounds, scale=1.0):
    """Create target image showing final folded state after all rotations.
    Target should be a solid MIDNIGHT silhouette."""
    fig, ax = plt.subplots(figsize=CANVAS_SIZE)
    ax.set_aspect('equal')
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_frame_on(True)
    # Add subtle frame border like rush_hour
    for spine in ax.spines.values():
        spine.set_edgecolor(MIDNIGHT)
        spine.set_linewidth(1.0)
    
    # Set unified bounds for consistent aspect ratio
    ax.set_xlim(bounds['xmin'], bounds['xmax'])
    ax.set_ylim(bounds['ymin'], bounds['ymax'])
    
    final_positions = calculate_folded_positions(shape_chain, initial_positions, all_rotations, scale=scale)
    
    for i, (x, y, angle) in enumerate(final_positions):
        draw_shape(ax, x, y, shape_chain[i], rotation=angle, alpha=1.0, draw_edges=False, facecolor=MIDNIGHT, scale=scale)
    
    fig.tight_layout()
    plt.savefig(output_path, bbox_inches='tight', facecolor=CANVAS_BG, dpi=200)
    plt.close()


def create_cot_image(output_path, shape_chain, initial_positions, rotations_so_far, piece_colors, bounds, scale=1.0):
    """Create chain-of-thought image showing progressive folding with consistent colors."""
    fig, ax = plt.subplots(figsize=CANVAS_SIZE)
    ax.set_aspect('equal')
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_frame_on(True)
    # Add subtle frame border like rush_hour
    for spine in ax.spines.values():
        spine.set_edgecolor(MIDNIGHT)
        spine.set_linewidth(1.0)
    
    # Set unified bounds for consistent aspect ratio
    ax.set_xlim(bounds['xmin'], bounds['xmax'])
    ax.set_ylim(bounds['ymin'], bounds['ymax'])
    
    positions = calculate_folded_positions(shape_chain, initial_positions, rotations_so_far, scale=scale)
    
    for i, (x, y, angle) in enumerate(positions):
        draw_shape(ax, x, y, shape_chain[i], rotation=angle, alpha=0.75, facecolor=piece_colors[i], scale=scale)
    
    fig.tight_layout()
    plt.savefig(output_path, bbox_inches='tight', facecolor=CANVAS_BG, dpi=200)
    plt.close()


def rotate_shape_around_hinge(shape_center, hinge_point, rotation_angle):
    """
    Rotate a shape around a hinge point by rotation_angle degrees.

    NOTE: This function is left unchanged (geometry-only). """
    hx, hy = hinge_point
    cx, cy = shape_center
    
    dx = cx - hx
    dy = cy - hy
    
    angle_rad = np.radians(rotation_angle)
    cos_a, sin_a = np.cos(angle_rad), np.sin(angle_rad)
    
    new_dx = dx * cos_a - dy * sin_a
    new_dy = dx * sin_a + dy * cos_a
    
    new_x = hx + new_dx
    new_y = hy + new_dy
    
    return new_x, new_y


def get_rotated_hinge_position(initial_shape_center, current_shape_center, current_rotation, initial_hinge_point):
    """
    Calculate where a hinge point has moved to after the shape it's attached to has rotated.

    NOTE: This function is left unchanged (geometry-only). """
    init_cx, init_cy = initial_shape_center
    curr_cx, curr_cy = current_shape_center
    hinge_x, hinge_y = initial_hinge_point
    
    dx = hinge_x - init_cx
    dy = hinge_y - init_cy
    
    angle_rad = np.radians(current_rotation)
    cos_a, sin_a = np.cos(angle_rad), np.sin(angle_rad)
    
    rotated_dx = dx * cos_a - dy * sin_a
    rotated_dy = dx * sin_a + dy * cos_a
    
    current_hinge_x = curr_cx + rotated_dx
    current_hinge_y = curr_cy + rotated_dy
    
    return current_hinge_x, current_hinge_y


def calculate_folded_positions(shape_chain, initial_positions, rotations, scale=1.0):
    """
    Calculate positions and rotations of all pieces after applying hinge rotations.
    
    Args:
        shape_chain: List of shape configs
        initial_positions: List of (x, y) positions for each shape
        rotations: List of rotation angles to apply at each hinge
        scale: Scaling factor (must match the scale used for initial_positions)
    """
    num_pieces = len(shape_chain)
    current_positions = [(x, y, 0) for x, y in initial_positions]
    
    for hinge_idx in range(len(rotations)):
        rotation_angle = rotations[hinge_idx]
        
        # Get current position and rotation of the left piece (the one being rotated around)
        piece_x, piece_y, piece_rot = current_positions[hinge_idx]
        
        # Calculate the current hinge position by finding the right connection of the left piece
        # with its current rotation
        current_hinge_x, current_hinge_y = get_shape_right_connection_point(
            shape_chain[hinge_idx],
            piece_x,
            piece_y,
            scale=scale,
            rotation=piece_rot
        )
        
        new_positions = list(current_positions)
        
        for affected_piece_idx in range(hinge_idx + 1, num_pieces):
            curr_x, curr_y, curr_rot = current_positions[affected_piece_idx]
            new_x, new_y = rotate_shape_around_hinge(
                (curr_x, curr_y),
                (current_hinge_x, current_hinge_y),
                rotation_angle
            )
            new_rot = curr_rot + rotation_angle
            new_positions[affected_piece_idx] = (new_x, new_y, new_rot)
        
        current_positions = new_positions
    
    return current_positions


def create_combined_image(output_path, initial_image_path, target_image_path):
    """Create a combined image with initial state on left and target on right."""
    from PIL import ImageDraw, ImageFont
    
    # Load images
    initial_img = Image.open(initial_image_path)
    target_img = Image.open(target_image_path)
    
    # Calculate dimensions
    margin = 40
    label_height = 60
    gap = 60  # Gap between the two images
    fontsize = 36
    
    # Total dimensions
    total_width = initial_img.width + target_img.width + gap + 2 * margin
    total_height = max(initial_img.height, target_img.height) + label_height + 2 * margin
    
    # Create canvas
    canvas = Image.new('RGB', (total_width, total_height), color=(253, 253, 253))  # CANVAS_BG
    draw = ImageDraw.Draw(canvas)
    
    # Try to load a font, fall back to default
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", fontsize)
    except:
        font = ImageFont.load_default(fontsize)
    
    # Paste initial image on left
    initial_x = margin
    initial_y = margin + label_height
    canvas.paste(initial_img, (initial_x, initial_y))
    
    # Draw "Initial" label
    label_x = initial_x + initial_img.width // 2
    label_y = margin + label_height // 2
    draw.text((label_x, label_y), "Initial", fill="#1B263B", font=font, anchor="mm")
    
    # Paste target image on right
    target_x = margin + initial_img.width + gap
    target_y = margin + label_height
    canvas.paste(target_img, (target_x, target_y))
    
    # Draw "Target" label
    label_x = target_x + target_img.width // 2
    label_y = margin + label_height // 2
    draw.text((label_x, label_y), "Target", fill="#1B263B", font=font, anchor="mm")
    
    # Save combined image
    canvas.save(output_path)


def draw_shape(ax, x, y, shape_config, rotation=0, alpha=1.0, scale=1.0, draw_edges=True, facecolor=None):
    """Draw a shape at given position with rotation and palette-constrained facecolor."""
    shape_type = shape_config["type"]
    size = shape_config.get("size", 1.0) * scale
    
    edge_color = MIDNIGHT
    edge_width = 2.0 if draw_edges else 0  # 2.0 pt per style guide
    # Default fallback if facecolor is not provided (still from palette)
    if facecolor is None:
        facecolor = PALETTE[0]
    
    if shape_type == "diamond" or shape_type == "square":
        angle_offset = 45 if shape_type == "diamond" else 0
        corners = []
        for i in range(4):
            angle = np.radians(rotation + angle_offset + i * 90)
            corners.append((x + size * np.cos(angle) * 0.5, 
                            y + size * np.sin(angle) * 0.5))
        poly = patches.Polygon(corners, closed=True, facecolor=facecolor, 
                               edgecolor=edge_color, linewidth=edge_width, alpha=alpha)
        ax.add_patch(poly)
    
    elif shape_type == "triangle":
        corners = []
        for i in range(3):
            angle = np.radians(rotation + i * 120)
            corners.append((x + size * np.cos(angle) * 0.5,
                            y + size * np.sin(angle) * 0.5))
        poly = patches.Polygon(corners, closed=True, facecolor=facecolor,
                               edgecolor=edge_color, linewidth=edge_width, alpha=alpha)
        ax.add_patch(poly)
    
    elif shape_type == "rectangle":
        width = shape_config.get("width", 1.0) * scale
        height = shape_config.get("height", 0.5) * scale
        
        corners = [
            (-width/2, -height/2),
            ( width/2, -height/2),
            ( width/2,  height/2),
            (-width/2,  height/2)
        ]
        
        rad = np.radians(rotation)
        cos_r, sin_r = np.cos(rad), np.sin(rad)
        rotated_corners = []
        for cx, cy in corners:
            rx = cx * cos_r - cy * sin_r + x
            ry = cx * sin_r + cy * cos_r + y
            rotated_corners.append((rx, ry))
        
        poly = patches.Polygon(rotated_corners, closed=True, facecolor=facecolor,
                               edgecolor=edge_color, linewidth=edge_width, alpha=alpha)
        ax.add_patch(poly)


if __name__ == "__main__":
    # Generate dataset
    dataset_path = Path("./output/dataset")
    
    print("="*50)
    print("Generating hinge folding dataset")
    print("="*50)
    
    generate_hinge_folding_dataset(
        output_dir=str(dataset_path),
        num_samples=7000,  # 6000 train + 400 val + 400 test + buffer
        min_pieces=2,
        max_pieces=5,
        seed=42
    )
    
    print("\n✅ Hinge folding dataset generation complete!")