#!/bin/bash
# ============================================================================
# Generate All Visual Thinking Datasets
# ============================================================================
# This script generates 50 samples per difficulty level (1-5 CoT steps) for
# each benchmark task. Each level corresponds to an exact number of reasoning
# steps required to solve the puzzle.
#
# Usage:
#   ./generate_all_datasets.sh [--clean] [--task TASK]
#
# Options:
#   --clean       Delete existing output folders before generating
#   --task TASK   Only generate for specific task (form-board, paper-fold, 
#                 sliding-puzzle, sliding-puzzle-same-images, hinge-folding, tangram)
#
# ============================================================================

set -e  # Exit on error

# Configuration
INSTANCES_PER_LEVEL=50
SEED=42
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGENET_1K_DIR="<insert path to imagenet-1k directory>"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Parse arguments
CLEAN=false
TASK_FILTER=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --clean)
            CLEAN=true
            shift
            ;;
        --task)
            TASK_FILTER="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Helper function to print section headers
print_header() {
    echo ""
    echo -e "${BLUE}============================================================================${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}============================================================================${NC}"
}

# Helper function to print task info
print_task() {
    echo -e "${GREEN}  → Level $1: $2${NC}"
}

# Helper function to clean output directory
clean_output() {
    local dir="$1"
    if [ -d "$dir" ]; then
        echo -e "${YELLOW}  Cleaning $dir${NC}"
        rm -rf "$dir"
    fi
}

# ============================================================================
# FORM-BOARD
# Difficulty = number of solution pieces (1-5)
# Each piece = 1 CoT step
# Note: Level 1 (1 piece) is trivial but included for completeness
# ============================================================================
generate_form_board() {
    print_header "FORM-BOARD"
    cd "$SCRIPT_DIR/form-board"
    
    if [ "$CLEAN" = true ]; then
        clean_output "output"
    fi
    
    # Level 1: 1 piece (1 CoT step) - trivial, single piece fills target
    print_task 1 "1 solution piece"
    uv run main.py --instances $INSTANCES_PER_LEVEL --min-pieces 1 --max-pieces 1 \
        --output-dir output/level_01 --seed $SEED
    
    # Level 2: 2 pieces (2 CoT steps)
    print_task 2 "2 solution pieces"
    uv run main.py --instances $INSTANCES_PER_LEVEL --min-pieces 2 --max-pieces 2 \
        --output-dir output/level_02 --seed $((SEED + 100))
    
    # Level 3: 3 pieces (3 CoT steps)
    print_task 3 "3 solution pieces"
    uv run main.py --instances $INSTANCES_PER_LEVEL --min-pieces 3 --max-pieces 3 \
        --output-dir output/level_03 --seed $((SEED + 200))
    
    # Level 4: 4 pieces (4 CoT steps)
    print_task 4 "4 solution pieces"
    uv run main.py --instances $INSTANCES_PER_LEVEL --min-pieces 4 --max-pieces 4 \
        --output-dir output/level_04 --seed $((SEED + 300))
    
    # Level 5: 5 pieces (5 CoT steps)
    print_task 5 "5 solution pieces"
    uv run main.py --instances $INSTANCES_PER_LEVEL --min-pieces 5 --max-pieces 5 \
        --output-dir output/level_05 --seed $((SEED + 400))
    
    echo -e "${GREEN}  ✓ Form-board complete${NC}"
}

# ============================================================================
# PAPER-FOLD
# Difficulty = number of folds (1-5)
# Each fold = 1 CoT step (unfolding)
# ============================================================================
generate_paper_fold() {
    print_header "PAPER-FOLD"
    cd "$SCRIPT_DIR/paper-fold"
    
    if [ "$CLEAN" = true ]; then
        clean_output "output"
    fi
    
    # Level 1: 1 fold (1 CoT step)
    print_task 1 "1 fold"
    uv run main.py --instances $INSTANCES_PER_LEVEL --min-folds 1 --max-folds 1 \
        --grid-size 2 --output-dir output/level_01 --seed $SEED
    
    # Level 2: 2 folds (2 CoT steps)
    print_task 2 "2 folds"
    uv run main.py --instances $INSTANCES_PER_LEVEL --min-folds 2 --max-folds 2 \
        --grid-size 2 --output-dir output/level_02 --seed $((SEED + 100))
    
    # Level 3: 3 folds (3 CoT steps)
    print_task 3 "3 folds"
    uv run main.py --instances $INSTANCES_PER_LEVEL --min-folds 3 --max-folds 3 \
        --grid-size 2 --output-dir output/level_03 --seed $((SEED + 200))
    
    # Level 4: 4 folds (4 CoT steps)
    print_task 4 "4 folds"
    uv run main.py --instances $INSTANCES_PER_LEVEL --min-folds 4 --max-folds 4 \
        --grid-size 3 --output-dir output/level_04 --seed $((SEED + 300))
    
    # Level 5: 5 folds (5 CoT steps)
    print_task 5 "5 folds"
    uv run main.py --instances $INSTANCES_PER_LEVEL --min-folds 5 --max-folds 5 \
        --grid-size 3 --output-dir output/level_05 --seed $((SEED + 400))
    
    echo -e "${GREEN}  ✓ Paper-fold complete${NC}"
}

# ============================================================================
# SLIDING-PUZZLE
# Difficulty = number of moves to solve (1-5)
# Each move = 1 CoT step
# Note: Requires source images directory
# ============================================================================
generate_sliding_puzzle() {
    print_header "SLIDING-PUZZLE"
    cd "$SCRIPT_DIR/sliding-puzzle"

    IMAGE_SEED=342
    
    if [ ! -d "$IMAGENET_1K_DIR" ]; then
        echo -e "${RED}  ✗ Source images not found at: $IMAGENET_1K_DIR${NC}"
        echo -e "${YELLOW}    Set IMAGENET_1K_DIR environment variable or update the script${NC}"
        return 1
    fi

    if [ "$CLEAN" = true ]; then
        clean_output "output"
    fi
    
    # Level 1: 1 move (1 CoT step)
    print_task 1 "1 move"
    uv run main.py --instances $INSTANCES_PER_LEVEL --min-moves 1 --max-moves 1 \
        --grid-size 2 --output-dir output/level_01 --source-images "$IMAGENET_1K_DIR" --seed $SEED --image-seed $IMAGE_SEED
    
    # Level 2: 2 moves (2 CoT steps)
    print_task 2 "2 moves"
    uv run main.py --instances $INSTANCES_PER_LEVEL --min-moves 2 --max-moves 2 \
        --grid-size 2 --output-dir output/level_02 --source-images "$IMAGENET_1K_DIR" --seed $((SEED + 100)) --image-seed $IMAGE_SEED
    
    # Level 3: 3 moves (3 CoT steps)
    print_task 3 "3 moves"
    uv run main.py --instances $INSTANCES_PER_LEVEL --min-moves 3 --max-moves 3 \
        --grid-size 2 --output-dir output/level_03 --source-images "$IMAGENET_1K_DIR" --seed $((SEED + 200)) --image-seed $IMAGE_SEED
    
    # Level 4: 4 moves (4 CoT steps)
    print_task 4 "4 moves"
    uv run main.py --instances $INSTANCES_PER_LEVEL --min-moves 4 --max-moves 4 \
        --grid-size 2 --output-dir output/level_04 --source-images "$IMAGENET_1K_DIR" --seed $((SEED + 300)) --image-seed $IMAGE_SEED
    
    # Level 5: 5 moves (5 CoT steps)
    print_task 5 "5 moves"
    uv run main.py --instances $INSTANCES_PER_LEVEL --min-moves 5 --max-moves 5 \
        --grid-size 2 --output-dir output/level_05 --source-images "$IMAGENET_1K_DIR" --seed $((SEED + 400)) --image-seed $IMAGE_SEED
    
    echo -e "${GREEN}  ✓ Sliding-puzzle complete${NC}"
}

# ============================================================================
# HINGE-FOLDING
# Difficulty = number of hinges (1-5, since hinges = pieces - 1)
# Each hinge rotation = 1 CoT step
# ============================================================================
generate_hinge_folding() {
    print_header "HINGE-FOLDING"
    cd "$SCRIPT_DIR/hinge-folding"
    
    if [ "$CLEAN" = true ]; then
        clean_output "output"
    fi
    
    # Level 1: 2 pieces = 1 hinge (1 CoT step)
    print_task 1 "2 pieces (1 hinge)"
    uv run main.py --instances $INSTANCES_PER_LEVEL --min-pieces 2 --max-pieces 2 \
        --output-dir output/level_01 --seed $SEED
    
    # Level 2: 3 pieces = 2 hinges (2 CoT steps)
    print_task 2 "3 pieces (2 hinges)"
    uv run main.py --instances $INSTANCES_PER_LEVEL --min-pieces 3 --max-pieces 3 \
        --output-dir output/level_02 --seed $((SEED + 100))
    
    # Level 3: 4 pieces = 3 hinges (3 CoT steps)
    print_task 3 "4 pieces (3 hinges)"
    uv run main.py --instances $INSTANCES_PER_LEVEL --min-pieces 4 --max-pieces 4 \
        --output-dir output/level_03 --seed $((SEED + 200))
    
    # Level 4: 5 pieces = 4 hinges (4 CoT steps)
    print_task 4 "5 pieces (4 hinges)"
    uv run main.py --instances $INSTANCES_PER_LEVEL --min-pieces 5 --max-pieces 5 \
        --output-dir output/level_04 --seed $((SEED + 300))
    
    # Level 5: 6 pieces = 5 hinges (5 CoT steps)
    print_task 5 "6 pieces (5 hinges)"
    uv run main.py --instances $INSTANCES_PER_LEVEL --min-pieces 6 --max-pieces 6 \
        --output-dir output/level_05 --seed $((SEED + 400))
    
    echo -e "${GREEN}  ✓ Hinge-folding complete${NC}"
}

# ============================================================================
# RUSHHOUR
# Difficulty = number of CoT images (= number of actions)
# Level N = N CoT images = N actions
# ============================================================================
generate_rushhour() {
    print_header "RUSHHOUR"
    cd "$SCRIPT_DIR/rushhour"
    
    if [ "$CLEAN" = true ]; then
        clean_output "output"
    fi
    
    # Generate levels 1-5 (1-5 CoT images = 1-5 actions)
    # Level 1: 1 action (1 CoT image) - just move red car
    # Level 2: 2 actions (2 CoT images) - move 1 blocker + red car
    # Level 3: 3 actions (3 CoT images) - move 2 blockers + red car
    # Level 4: 4 actions (4 CoT images) - complex multi-blocker
    # Level 5: 5 actions (5 CoT images) - extended planning
    echo -e "${GREEN}  Generating levels 1-5 (50 instances each)${NC}"
    uv run main.py --instances $INSTANCES_PER_LEVEL --min-level 1 --max-level 5 \
        --output-dir output --seed $SEED --max-attempts 5000
    
    echo -e "${GREEN}  ✓ Rushhour complete${NC}"
}

# ============================================================================
# TANGRAM (currently not part of the benchmark - skipped)
# Difficulty = number of shapes (2-5)
# Each shape placement = 1 CoT step
# ============================================================================
# generate_tangram() {
#     print_header "TANGRAM"
#     cd "$SCRIPT_DIR/tangram"
#     
#     if [ "$CLEAN" = true ]; then
#         clean_output "output"
#     fi
#     
#     # Level 2: 2 shapes (2 CoT steps)
#     print_task 2 "2 shapes"
#     python generate_dataset.py --num-datapoints $INSTANCES_PER_LEVEL --min-shapes 2 --max-shapes 2 \
#         --output-dir output/level_02 --seed $SEED
#     
#     # Level 3: 3 shapes (3 CoT steps)
#     print_task 3 "3 shapes"
#     python generate_dataset.py --num-datapoints $INSTANCES_PER_LEVEL --min-shapes 3 --max-shapes 3 \
#         --output-dir output/level_03 --seed $((SEED + 100))
#     
#     # Level 4: 4 shapes (4 CoT steps)
#     print_task 4 "4 shapes"
#     python generate_dataset.py --num-datapoints $INSTANCES_PER_LEVEL --min-shapes 4 --max-shapes 4 \
#         --output-dir output/level_04 --seed $((SEED + 200))
#     
#     # Level 5: 5 shapes (5 CoT steps)
#     print_task 5 "5 shapes"
#     python generate_dataset.py --num-datapoints $INSTANCES_PER_LEVEL --min-shapes 5 --max-shapes 5 \
#         --output-dir output/level_05 --seed $((SEED + 300))
#     
#     echo -e "${GREEN}  ✓ Tangram complete${NC}"
# }

# ============================================================================
# MAIN
# ============================================================================
echo ""
echo -e "${BLUE}╔════════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║         Visual Thinking Dataset Generator                              ║${NC}"
echo -e "${BLUE}║         Generating $INSTANCES_PER_LEVEL samples per difficulty level                       ║${NC}"
echo -e "${BLUE}╚════════════════════════════════════════════════════════════════════════╝${NC}"

if [ -n "$TASK_FILTER" ]; then
    echo -e "${YELLOW}Generating only: $TASK_FILTER${NC}"
    case $TASK_FILTER in
        form-board)
            generate_form_board
            ;;
        paper-fold)
            generate_paper_fold
            ;;
        sliding-puzzle)
            generate_sliding_puzzle
            ;;
        hinge-folding)
            generate_hinge_folding
            ;;
        rushhour)
            generate_rushhour
            ;;
        # tangram)
        #     generate_tangram
        #     ;;
        *)
            echo -e "${RED}Unknown task: $TASK_FILTER${NC}"
            exit 1
            ;;
    esac
else
    # Generate all datasets
    generate_form_board
    generate_paper_fold
    generate_hinge_folding
    generate_sliding_puzzle
    generate_rushhour
fi

echo ""
echo -e "${GREEN}╔════════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         All datasets generated successfully!                           ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════════════════════════════════╝${NC}"
echo ""

