"""
Generate multiple form-board puzzle instances with various target shapes.
"""
import json
import random
from pathlib import Path
from generate import Puzzle


# Define various target shapes on a 5×5 grid
TARGET_SHAPES = {
    # Simple rectangle (like the VZ1 example)
    "rectangle": "0,1-0,4; 0,4-3,4; 3,4-3,1; 3,1-0,1",
    
    # Square
    "square": "1,1-1,4; 1,4-4,4; 4,4-4,1; 4,1-1,1",
    
    # L-shape
    "L_shape": "0,0-0,4; 0,4-2,4; 2,4-2,2; 2,2-4,2; 4,2-4,0; 4,0-0,0",
    
    # T-shape
    "T_shape": "0,3-0,5; 0,5-5,5; 5,5-5,3; 5,3-3,3; 3,3-3,0; 3,0-2,0; 2,0-2,3; 2,3-0,3",
    
    # Cross/Plus shape
    "cross": "1,0-1,2; 1,2-0,2; 0,2-0,3; 0,3-1,3; 1,3-1,5; 1,5-2,5; 2,5-2,3; 2,3-3,3; 3,3-3,2; 3,2-2,2; 2,2-2,0; 2,0-1,0",
    
    # U-shape
    "U_shape": "0,0-0,5; 0,5-1,5; 1,5-1,1; 1,1-4,1; 4,1-4,5; 4,5-5,5; 5,5-5,0; 5,0-0,0",
    
    # Trapezoid
    "trapezoid": "1,1-2,4; 2,4-4,4; 4,4-5,1; 5,1-1,1",
    
    # Pentagon
    "pentagon": "2,0-0,2; 0,2-1,4; 1,4-4,4; 4,4-5,2; 5,2-2,0",
    
    # Stairs/Steps
    "stairs": "0,0-0,2; 0,2-2,2; 2,2-2,4; 2,4-4,4; 4,4-4,5; 4,5-5,5; 5,5-5,0; 5,0-0,0",
    
    # Arrow pointing right (simplified to integer coordinates)
    "arrow": "0,1-0,4; 0,4-3,4; 3,4-3,5; 3,5-5,3; 5,3-5,2; 5,2-3,0; 3,0-3,1; 3,1-0,1",
    
    # Diamond/Rhombus
    "diamond": "2,0-0,2; 0,2-2,4; 2,4-4,2; 4,2-2,0",
    
    # Hexagon (regular-ish)
    "hexagon": "1,0-0,2; 0,2-1,4; 1,4-4,4; 4,4-5,2; 5,2-4,0; 4,0-1,0",
}


def generate_dataset(
    output_dir: str = "output",
    total_instances: int = 60,
    min_solution_pieces: int = 2,
    max_solution_pieces: int = 5,
    seed: int = 42,
):
    """
    Generate a dataset of form-board puzzles.
    
    Args:
        output_dir: Directory to save generated puzzles
        total_instances: Total number of puzzle instances to generate across all shapes
        min_solution_pieces: Minimum number of solution pieces (default: 2)
        max_solution_pieces: Maximum number of solution pieces (default: 5)
        seed: Random seed for reproducibility
    """
    random.seed(seed)
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    dataset_metadata = {
        "description": "Form Board Test puzzles",
        "num_shapes": len(TARGET_SHAPES),
        "total_instances": total_instances,
        "min_solution_pieces": min_solution_pieces,
        "max_solution_pieces": max_solution_pieces,
        "puzzles": []
    }
    
    puzzle_id = 0
    shape_list = list(TARGET_SHAPES.items())
    
    # Generate total_instances puzzles, cycling through shapes
    for instance_idx in range(total_instances):
        # Cycle through shapes
        shape_idx = instance_idx % len(shape_list)
        shape_name, edges = shape_list[shape_idx]
        
        puzzle_id += 1
        puzzle_dir = output_path / f"puzzle_{puzzle_id:04d}"
        puzzle_dir.mkdir(exist_ok=True)
        
        # Randomly choose number of solution pieces for this puzzle
        num_solution_pieces = random.randint(min_solution_pieces, max_solution_pieces)
        
        # Retry logic with different seeds if generation fails
        max_retries = 5
        success = False
        
        for retry in range(max_retries):
            try:
                # Create puzzle
                # Grid size is fixed at 5 (hardcoded in shape definitions)
                puzzle = Puzzle.from_edges(edges, grid_size=5)
                
                # Generate and export with specified number of solution pieces
                # Use different seed for each retry
                export_seed = seed + puzzle_id + retry * 10000
                out_dir = str(puzzle_dir)
                solution_mask = puzzle.export(out_dir, ppu=100, seed=export_seed, num_solution_pieces=num_solution_pieces)
                
                # Count number of CoT images generated (should match num_solution_pieces)
                actual_solution_pieces = solution_mask.count('T')
                cot_images = [f"{puzzle_id}_cot_{i:02d}.png" for i in range(actual_solution_pieces)]
                
                # Create metadata
                puzzle_metadata = {
                    "puzzle_id": puzzle_id,
                    "shape_name": shape_name,
                    "instance_idx": instance_idx,
                    "silhouette_image": "silhouette.png",
                    "bordered_image": "bordered.png",
                    "combined_image": "combined.png",
                    "cot_images": cot_images,
                    "choices_image": "choices.png",
                    "pieces": [
                        {
                            "piece_id": i + 1,
                            "image": f"piece_{i+1}.png",
                            "is_solution": solution_mask[i] == 'T',
                            "label": chr(65 + i)  # A, B, C, D, E
                        }
                        for i in range(5)
                    ],
                    "question": f"Which pieces in (2) are necessary to form the figure of (1)?",
                    "solution_pieces": [chr(65 + i) for i, mask in enumerate(solution_mask) if mask == 'T'],
                    "num_solution_pieces": actual_solution_pieces
                }
                
                # Save puzzle-specific metadata
                with open(puzzle_dir / "metadata.json", "w") as f:
                    json.dump(puzzle_metadata, f, indent=2)
                
                dataset_metadata["puzzles"].append(puzzle_metadata)
                
                print(f"  ✓ Generated puzzle {puzzle_id}: {shape_name} with {actual_solution_pieces} pieces (solution: {puzzle_metadata['solution_pieces']})")
                success = True
                break  # Successfully generated, exit retry loop
                
            except Exception as e:
                if retry < max_retries - 1:
                    print(f"  ⚠ Retry {retry + 1}/{max_retries} for puzzle {puzzle_id} ({shape_name}): {e}")
                else:
                    print(f"  ✗ Failed to generate puzzle {puzzle_id} after {max_retries} attempts: {e}")
        
        if not success:
            # Remove the puzzle directory if all retries failed
            import shutil
            if puzzle_dir.exists():
                shutil.rmtree(puzzle_dir)
            print(f"  ✗ Skipping puzzle {puzzle_id} ({shape_name})")
    
    # Save dataset-level metadata
    with open(output_path / "dataset_metadata.json", "w") as f:
        json.dump(dataset_metadata, f, indent=2)
    
    print(f"\n{'='*60}")
    print(f"Dataset generation complete!")
    print(f"Total puzzles: {len(dataset_metadata['puzzles'])}")
    print(f"Output directory: {output_path.absolute()}")
    print(f"{'='*60}")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Generate form-board puzzle dataset"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="output",
        help="Output directory for generated puzzles (default: output)"
    )
    parser.add_argument(
        "--instances",
        type=int,
        default=60,
        help="Total number of puzzle instances to generate (default: 60)"
    )
    parser.add_argument(
        "--min-pieces",
        type=int,
        default=2,
        help="Minimum number of solution pieces (default: 2)"
    )
    parser.add_argument(
        "--max-pieces",
        type=int,
        default=5,
        help="Maximum number of solution pieces (default: 5)"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)"
    )
    
    args = parser.parse_args()
    
    generate_dataset(
        output_dir=args.output_dir,
        total_instances=args.instances,
        min_solution_pieces=args.min_pieces,
        max_solution_pieces=args.max_pieces,
        seed=args.seed
    )


if __name__ == "__main__":
    main()
