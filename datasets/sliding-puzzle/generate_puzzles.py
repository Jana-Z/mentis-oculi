"""
Generate sliding tile puzzle dataset.
Adapted from existing sliding puzzle implementation.
"""

import os
import random
import json
import numpy as np
from PIL import Image
from pathlib import Path
from tqdm import tqdm
from collections import deque


def create_goal_state(dimensions, blank_position=None):
    """Create the solved/goal state for the puzzle.
    
    Args:
        dimensions: Size of the grid (n×n)
        blank_position: Tuple (row, col) for blank position, or None for random
        
    Returns:
        2D list representing the goal state with -1 as the blank tile
    """
    if blank_position is None:
        # Randomly sample blank position
        blank_row = random.randint(0, dimensions - 1)
        blank_col = random.randint(0, dimensions - 1)
        blank_position = (blank_row, blank_col)
    
    blank_r, blank_c = blank_position
    
    goal = []
    num = 1
    for i in range(dimensions):
        row = []
        for j in range(dimensions):
            if i == blank_r and j == blank_c:
                row.append(-1)  # Blank tile
            else:
                row.append(num)
                num += 1
        goal.append(row)
    return goal


def find_blank(grid):
    """Find the position of the blank tile (-1)"""
    dimensions = len(grid)
    for r in range(dimensions):
        for c in range(dimensions):
            if grid[r][c] == -1:
                return (r, c)
    return None


def get_valid_moves(grid):
    """Get all valid moves from current state"""
    dimensions = len(grid)
    r, c = find_blank(grid)
    moves = []
    
    # up: swap with tile above (r-1, c)
    if r > 0:
        moves.append("up")
    # down: swap with tile below (r+1, c)
    if r < dimensions - 1:
        moves.append("down")
    # left: swap with tile to the left (r, c-1)
    if c > 0:
        moves.append("left")
    # right: swap with tile to the right (r, c+1)
    if c < dimensions - 1:
        moves.append("right")
    
    return moves


def apply_move(grid, move):
    """Apply a move and return the new grid state"""
    dimensions = len(grid)
    r, c = find_blank(grid)
    
    # Create a copy
    new_grid = [row[:] for row in grid]
    
    # Define move directions
    directions = {
        "up": (-1, 0),
        "down": (1, 0),
        "left": (0, -1),
        "right": (0, 1)
    }
    
    dr, dc = directions[move]
    nr, nc = r + dr, c + dc
    
    if 0 <= nr < dimensions and 0 <= nc < dimensions:
        # Swap blank with target tile
        new_grid[r][c], new_grid[nr][nc] = new_grid[nr][nc], new_grid[r][c]
    
    return new_grid


def grid_to_tuple(grid):
    """Convert grid to a hashable tuple for BFS visited set."""
    return tuple(tuple(row) for row in grid)


def tuple_to_grid(t):
    """Convert tuple back to grid."""
    return [list(row) for row in t]


def bfs_solve(initial_state, goal_state, max_depth=None):
    """
    Find the optimal (shortest) solution using BFS.
    
    Args:
        initial_state: Starting puzzle state
        goal_state: Target puzzle state
        max_depth: Maximum search depth (None for unlimited)
        
    Returns:
        List of moves representing the optimal solution, or None if unsolvable
    """
    initial_tuple = grid_to_tuple(initial_state)
    goal_tuple = grid_to_tuple(goal_state)
    
    if initial_tuple == goal_tuple:
        return []
    
    # BFS queue: (state_tuple, move_sequence)
    queue = deque([(initial_tuple, [])])
    visited = {initial_tuple}
    
    while queue:
        current_tuple, moves = queue.popleft()
        
        # Check depth limit
        if max_depth is not None and len(moves) >= max_depth:
            continue
        
        current_grid = tuple_to_grid(current_tuple)
        
        for move in get_valid_moves(current_grid):
            new_grid = apply_move(current_grid, move)
            new_tuple = grid_to_tuple(new_grid)
            
            if new_tuple == goal_tuple:
                return moves + [move]
            
            if new_tuple not in visited:
                visited.add(new_tuple)
                queue.append((new_tuple, moves + [move]))
    
    return None  # No solution found


def scramble_puzzle(goal_state, num_moves, seed=None):
    """
    Scramble the puzzle by applying random valid moves.
    Returns (initial_state, move_sequence)
    """
    if seed is not None:
        random.seed(seed)
    
    current_state = [row[:] for row in goal_state]
    moves = []
    
    for _ in range(num_moves):
        valid_moves = get_valid_moves(current_state)
        # Avoid immediate reversal of last move
        if len(moves) > 0:
            reverse_moves = {"up": "down", "down": "up", "left": "right", "right": "left"}
            last_reverse = reverse_moves.get(moves[-1])
            if last_reverse in valid_moves and len(valid_moves) > 1:
                valid_moves = [m for m in valid_moves if m != last_reverse]
        
        move = random.choice(valid_moves)
        current_state = apply_move(current_state, move)
        moves.append(move)
    
    return current_state, moves


def grid_to_image(grid, tile_images, tile_size=128):
    """Convert grid state to an image.
    
    Args:
        grid: 2D list representing puzzle state (tile numbers, -1 for blank)
        tile_images: Dictionary mapping tile numbers to PIL Images
        tile_size: Size of each tile in pixels
        
    Returns:
        PIL Image representing the puzzle state
    """
    dimensions = len(grid)
    img_size = dimensions * tile_size
    result = Image.new('RGB', (img_size, img_size), color='black')
    
    for r in range(dimensions):
        for c in range(dimensions):
            tile_num = grid[r][c]
            if tile_num != -1:  # Not blank
                tile_img = tile_images[tile_num]  # tile_images is a dict
                x = c * tile_size
                y = r * tile_size
                result.paste(tile_img, (x, y))
    
    return result


def create_tile_images(source_image, dimensions, tile_size=128, blank_position=None):
    """Split source image into tiles.
    
    The tiles are stored in a dictionary mapping tile number to tile image.
    Tile numbers correspond to positions in the goal state (1-indexed),
    where the blank position is skipped.
    
    Args:
        source_image: PIL Image to split
        dimensions: Grid size (n×n)
        tile_size: Size of each tile in pixels
        blank_position: Tuple (row, col) for the blank tile, or None for bottom-right
        
    Returns:
        Dictionary mapping tile number (1 to n²-1) to PIL Image
    """
    if blank_position is None:
        blank_position = (dimensions - 1, dimensions - 1)
    
    blank_r, blank_c = blank_position
    
    # Resize source image to fit grid
    img_size = dimensions * tile_size
    source_image = source_image.resize((img_size, img_size), Image.Resampling.LANCZOS)
    
    # Create a mapping from tile number to tile image
    # Tile numbers are assigned sequentially, skipping the blank position
    tile_images = {}
    tile_num = 1
    
    for r in range(dimensions):
        for c in range(dimensions):
            if r == blank_r and c == blank_c:
                # This is the blank position, skip it
                continue
            
            x = c * tile_size
            y = r * tile_size
            tile = source_image.crop((x, y, x + tile_size, y + tile_size))
            tile_images[tile_num] = tile
            tile_num += 1
    
    return tile_images


def generate_puzzle(
    source_image_path,
    output_dir,
    puzzle_id,
    dimensions=3,
    num_scramble_moves=10,
    tile_size=128,
    seed=None,
    max_retries=100
):
    """Generate a single sliding puzzle instance.
    
    Args:
        source_image_path: Path to source image
        output_dir: Output directory
        puzzle_id: Puzzle identifier
        dimensions: Grid size (n×n)
        num_scramble_moves: Target number of moves for optimal solution
        tile_size: Size of each tile in pixels
        seed: Random seed for reproducibility
        max_retries: Maximum attempts to find a puzzle with exact move count
        
    Returns:
        Puzzle metadata dictionary
    """
    if seed is not None:
        random.seed(seed)
    
    # Load source image
    source_img = Image.open(source_image_path).convert('RGB')
    
    # Randomly sample blank position
    blank_row = random.randint(0, dimensions - 1)
    blank_col = random.randint(0, dimensions - 1)
    blank_position = (blank_row, blank_col)
    
    # Create tiles with the randomly positioned blank
    tile_images = create_tile_images(source_img, dimensions, tile_size, blank_position)
    
    # Create goal state with the same blank position
    goal_state = create_goal_state(dimensions, blank_position)
    
    # Scramble and find optimal solution, retrying until we get exact move count
    initial_state = None
    scramble_moves = None
    solution_moves = None
    
    for attempt in range(max_retries):
        # Scramble with more moves than needed to ensure variety
        scramble_depth = num_scramble_moves + random.randint(0, num_scramble_moves)
        attempt_seed = seed + attempt if seed is not None else None
        initial_state, scramble_moves = scramble_puzzle(goal_state, scramble_depth, seed=attempt_seed)
        
        # Find optimal solution using BFS
        solution_moves = bfs_solve(initial_state, goal_state, max_depth=num_scramble_moves + 5)
        
        if solution_moves is not None and len(solution_moves) == num_scramble_moves:
            # Found a puzzle with exactly the target number of moves
            break
    else:
        # If we couldn't find exact match, use closest we have
        # Re-scramble with exact moves and use reversed scramble as solution
        initial_state, scramble_moves = scramble_puzzle(goal_state, num_scramble_moves, seed=seed)
        reverse_map = {"up": "down", "down": "up", "left": "right", "right": "left"}
        solution_moves = [reverse_map[m] for m in reversed(scramble_moves)]
    
    # Generate images
    puzzle_dir = Path(output_dir) / f"puzzle_{puzzle_id:04d}"
    puzzle_dir.mkdir(parents=True, exist_ok=True)
    
    # Save initial (scrambled) state
    initial_img = grid_to_image(initial_state, tile_images, tile_size)
    initial_path = puzzle_dir / "initial.png"
    initial_img.save(initial_path)
    
    # Save target (solved) state
    target_img = grid_to_image(goal_state, tile_images, tile_size)
    target_path = puzzle_dir / "target.png"
    target_img.save(target_path)
    
    # Generate CoT images showing the solution path
    cot_images = []
    current_state = [row[:] for row in initial_state]
    
    for i, move in enumerate(solution_moves):
        current_state = apply_move(current_state, move)
        cot_img = grid_to_image(current_state, tile_images, tile_size)
        cot_path = puzzle_dir / f"cot_{i:02d}.png"
        cot_img.save(cot_path)
        cot_images.append(f"cot_{i:02d}.png")
    
    # Create metadata
    metadata = {
        "puzzle_id": puzzle_id,
        "grid_size": dimensions,
        "blank_position": list(blank_position),  # [row, col] of blank in goal state
        "num_solution_moves": len(solution_moves),
        "solution_moves": solution_moves,
        "initial_state": initial_state,
        "target_state": goal_state,
        "initial_image": "initial.png",
        "target_image": "target.png",
        "cot_images": cot_images,
        "source_image": os.path.basename(source_image_path),
        "is_solvable": True,
        "parity_valid": True
    }
    
    # Save metadata
    with open(puzzle_dir / "metadata.json", 'w') as f:
        json.dump(metadata, f, indent=2)
    
    return metadata


def load_source_images(image_dir, num_images=None, seed=None):
    """Load source images from directory, optionally sampling randomly
    
    Args:
        image_dir: Directory containing images
        num_images: Number of images to load (randomly sampled if less than available)
        seed: Random seed for sampling
        
    Returns:
        List of image paths
    """
    if seed is not None:
        random.seed(seed)
    
    image_dir = Path(image_dir)
    
    # Find all image files
    image_extensions = {'.png', '.jpg', '.jpeg', '.JPG', '.PNG', '.JPEG'}
    image_files = []
    
    for ext in image_extensions:
        image_files.extend(list(image_dir.glob(f'*{ext}')))
    
    # Shuffle for random sampling
    random.shuffle(image_files)
    
    # Sample without replacement
    if num_images and num_images < len(image_files):
        image_files = image_files[:num_images]
    
    return [str(f) for f in image_files]


def generate_dataset(
    source_images_dir,
    output_dir="output/dataset",
    num_instances=50,
    grid_size=3,
    min_moves=5,
    max_moves=15,
    tile_size=128,
    seed=42,
    image_seed=None
):
    """
    Generate a dataset of sliding puzzles.
    
    Args:
        source_images_dir: Directory containing source images
        output_dir: Output directory for generated puzzles
        num_instances: Number of puzzle instances to generate
        grid_size: Size of the grid (n×n)
        min_moves: Minimum scrambling moves
        max_moves: Maximum scrambling moves
        tile_size: Size of each tile in pixels
        seed: Random seed for reproducibility (affects scrambling)
        image_seed: Seed for image selection (if None, uses main seed)
                    Use a fixed value to get the same images across different runs
    """
    random.seed(seed)
    np.random.seed(seed)
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Load source images with separate seed for reproducible image selection
    # If image_seed is provided, use it; otherwise fall back to main seed
    img_selection_seed = image_seed if image_seed is not None else seed
    print(f"Loading source images from {source_images_dir}...")
    print(f"  (image selection seed: {img_selection_seed})")
    source_images = load_source_images(source_images_dir, num_images=num_instances, seed=img_selection_seed)
    
    # Reset RNG to main seed after image loading
    random.seed(seed)
    np.random.seed(seed)
    
    if len(source_images) == 0:
        raise ValueError(f"No images found in {source_images_dir}")
    
    print(f"Loaded {len(source_images)} source images (randomly sampled)")
    
    # If we need more instances than available images, cycle with warning
    if num_instances > len(source_images):
        print(f"Warning: Only {len(source_images)} images available, but {num_instances} instances requested.")
        print(f"Images will be reused (with different scrambles).")
        # Cycle through images with different seeds for variety
        source_images = source_images * (num_instances // len(source_images) + 1)
    
    dataset_metadata = {
        "description": "Sliding tile puzzle dataset",
        "total_instances": num_instances,
        "grid_size": grid_size,
        "min_moves": min_moves,
        "max_moves": max_moves,
        "tile_size": tile_size,
        "puzzles": []
    }
    
    print(f"Generating {num_instances} sliding puzzles...")
    
    for i in tqdm(range(num_instances)):
        source_img = source_images[i]
        num_scramble_moves = random.randint(min_moves, max_moves)
        
        puzzle_metadata = generate_puzzle(
            source_image_path=source_img,
            output_dir=output_path,
            puzzle_id=i + 1,
            dimensions=grid_size,
            num_scramble_moves=num_scramble_moves,
            tile_size=tile_size,
            seed=seed + i
        )
        
        dataset_metadata["puzzles"].append(puzzle_metadata)
    
    # Save dataset metadata
    with open(output_path / "dataset_metadata.json", 'w') as f:
        json.dump(dataset_metadata, f, indent=2)
    
    print(f"\n{'='*60}")
    print(f"Dataset generation complete!")
    print(f"Total puzzles: {len(dataset_metadata['puzzles'])}")
    print(f"Grid size: {grid_size}×{grid_size}")
    print(f"Scramble range: {min_moves}-{max_moves} moves")
    print(f"Output directory: {output_path.absolute()}")
    print(f"{'='*60}")


if __name__ == "__main__":
    # Example usage
    generate_dataset(
        source_images_dir="../sample_images",  # You'll need to provide images
        output_dir="output/test",
        num_instances=5,
        grid_size=3,
        min_moves=5,
        max_moves=10,
        seed=42
    )

