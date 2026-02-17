"""
Sliding Puzzle Generator - Main Entry Point

Generate sliding tile puzzles where scrambled images must be reconstructed
through sequential tile movements.
"""

import argparse
from generate_puzzles import generate_dataset


def main():
    parser = argparse.ArgumentParser(
        description="Generate sliding tile puzzle dataset"
    )
    parser.add_argument(
        "--source-images",
        type=str,
        required=True,
        help="Directory containing source images"
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
        default=50,
        help="Number of puzzle instances to generate (default: 50)"
    )
    parser.add_argument(
        "--grid-size",
        type=int,
        default=3,
        help="Size of the grid (n×n) (default: 3)"
    )
    parser.add_argument(
        "--min-moves",
        type=int,
        default=5,
        help="Minimum scrambling moves (default: 5)"
    )
    parser.add_argument(
        "--max-moves",
        type=int,
        default=15,
        help="Maximum scrambling moves (default: 15)"
    )
    parser.add_argument(
        "--tile-size",
        type=int,
        default=128,
        help="Size of each tile in pixels (default: 128)"
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducibility (default: 42)"
    )
    parser.add_argument(
        "--image-seed",
        type=int,
        default=None,
        help="Seed for image selection (default: same as --seed). "
             "Use a fixed value to get the same images across different runs."
    )
    
    args = parser.parse_args()
    
    print("="*60)
    print("Sliding Puzzle Generator")
    print("="*60)
    print(f"Source images: {args.source_images}")
    print(f"Output directory: {args.output_dir}")
    print(f"Instances: {args.instances}")
    print(f"Grid size: {args.grid_size}×{args.grid_size}")
    print(f"Scramble moves: {args.min_moves}-{args.max_moves}")
    print(f"Tile size: {args.tile_size}px")
    print(f"Random seed: {args.seed}")
    print(f"Image seed: {args.image_seed if args.image_seed is not None else '(same as random seed)'}")
    print("="*60)
    
    generate_dataset(
        source_images_dir=args.source_images,
        output_dir=args.output_dir,
        num_instances=args.instances,
        grid_size=args.grid_size,
        min_moves=args.min_moves,
        max_moves=args.max_moves,
        tile_size=args.tile_size,
        seed=args.seed,
        image_seed=args.image_seed
    )


if __name__ == "__main__":
    main()
