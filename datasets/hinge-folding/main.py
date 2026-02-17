"""
Hinge Folding Puzzle Generator

Generate hinge folding puzzles where a chain of connected shapes must be
folded at numbered hinges to form a target shape.
"""

import argparse
from generator import generate_hinge_folding_dataset


def main():
    parser = argparse.ArgumentParser(description="Generate hinge folding puzzle dataset")
    parser.add_argument("--instances", type=int, default=7000,
                       help="Number of puzzle instances to generate")
    parser.add_argument("--min-pieces", type=int, default=2,
                       help="Minimum number of pieces per puzzle")
    parser.add_argument("--max-pieces", type=int, default=5,
                       help="Maximum number of pieces per puzzle")
    parser.add_argument("--output-dir", type=str, default="output/",
                       help="Output directory for generated puzzles")
    parser.add_argument("--seed", type=int, default=42,
                       help="Random seed for reproducibility")
    
    args = parser.parse_args()
    
    print("="*50)
    print("Hinge Folding Puzzle Generator")
    print("="*50)
    print(f"Generating {args.instances} puzzles...")
    print(f"Pieces per puzzle: {args.min_pieces}-{args.max_pieces}")
    print(f"Output directory: {args.output_dir}")
    print(f"Random seed: {args.seed}")
    print("="*50)
    
    generate_hinge_folding_dataset(
        output_dir=args.output_dir,
        num_samples=args.instances,
        min_pieces=args.min_pieces,
        max_pieces=args.max_pieces,
        seed=args.seed
    )
    
    print("\n✅ Dataset generation complete!")


if __name__ == "__main__":
    main()