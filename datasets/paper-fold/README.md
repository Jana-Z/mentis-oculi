# Paper Folding Puzzle Generator

Generate paper folding puzzles similar to those found in IQ tests and visual reasoning assessments.

## Overview

This generator creates visual reasoning puzzles where:
- A square paper is folded multiple times (3-5 folds)
- Folds can be horizontal, vertical, or diagonal (45°)
- A hole is punched through the folded layers
- The task is to determine where all holes appear when the paper is unfolded

### Example Puzzle

![Paper Fold Example](output/level_03/puzzle_0001/combined.png)

*Example puzzle showing the folding sequence with hole punch (top) and five answer choices A-E (bottom). The task is to identify which unfolded pattern shows the correct hole positions.*

## Quick Start

Generate per-level datasets (50 samples each):

```bash
# Level 2: 2 folds (2 CoT steps)
uv run main.py --instances 50 --min-folds 2 --max-folds 2 --grid-size 2 --output-dir output/level_02 --seed 42

# Level 3: 3 folds (3 CoT steps)
uv run main.py --instances 50 --min-folds 3 --max-folds 3 --grid-size 2 --output-dir output/level_03 --seed 142

# Level 4: 4 folds (4 CoT steps)
uv run main.py --instances 50 --min-folds 4 --max-folds 4 --grid-size 3 --output-dir output/level_04 --seed 242

# Level 5: 5 folds (5 CoT steps)
uv run main.py --instances 50 --min-folds 5 --max-folds 5 --grid-size 3 --output-dir output/level_05 --seed 342

# Or use the repository-wide generation script:
cd .. && ./generate_all_datasets.sh --task paper-fold
```

This will create an `output/` directory with puzzles organized as:

```
output/
├── dataset_metadata.json          # Overall dataset info
├── puzzle_0001/
│   ├── question.png             # All folds + hole punch
│   ├── silhouette.png           # Final unfolded result (correct answer)
│   ├── combined.png             # Question + 5 labeled choices (A-E)
│   ├── cot_00.png               # Chain-of-thought: first unfold
│   ├── cot_01.png               # Chain-of-thought: second unfold
│   ├── cot_XX.png               # ... (one per fold)
│   ├── wrong_0.png              # Wrong answer choice 1
│   ├── wrong_1.png              # Wrong answer choice 2
│   ├── wrong_2.png              # Wrong answer choice 3
│   ├── wrong_3.png              # Wrong answer choice 4
|   ├── answer_grid.png          # 5 labeled choices in one grid
│   └── metadata.json            # Puzzle-specific metadata
├── puzzle_0002/
│   └── ...
...
```

## Usage

### Basic Generation

```bash
# Generate with defaults (20 puzzles, 3×3 grid)
uv run main.py

# Generate more instances
uv run main.py --instances 50

# Use a larger grid
uv run main.py --grid-size 4

# Control fold complexity
uv run main.py --min-folds 2 --max-folds 4

# Specify output directory
uv run main.py --output-dir my_puzzles

# Set random seed for reproducibility
uv run main.py --seed 42
```

### Command-Line Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--instances` | int | 20 | Number of puzzles to generate |
| `--grid-size` | int | 3 | Size of the grid (n×n) |
| `--min-folds` | int | 3 | Minimum number of folds per puzzle |
| `--max-folds` | int | 5 | Maximum number of folds per puzzle |
| `--output-dir` | str | output | Output directory path |
| `--seed` | int | None | Random seed for reproducibility |

## Difficulty Levels

The complexity of paper folding puzzles is controlled by the **number of folds**. Each fold creates additional hole reflections when unfolded:

| Level | Folds | CoT Steps | Grid Size | Output Directory |
|-------|-------|-----------|-----------|------------------|
| **1** | 1 | 1 | 2×2 | `output/level_01` |
| **2** | 2 | 2 | 2×2 | `output/level_02` |
| **3** | 3 | 3 | 2×2 | `output/level_03` |
| **4** | 4 | 4 | 3×3 | `output/level_04` |
| **5** | 5 | 5 | 3×3 | `output/level_05` |

More folds = more hole reflections = more complex spatial reasoning required.

## How It Works

### 1. Paper Folding

The generator starts with a square paper on an n×n grid and applies random folds:
- **Horizontal folds**: Fold along a horizontal line
- **Vertical folds**: Fold along a vertical line
- **Diagonal folds**: Fold along 45° diagonals

Each fold reflects one half of the paper over the fold axis, with the half containing the center point remaining stationary.

### 2. Hole Punching

After all folds are complete, a single hole is punched at a random location within the folded shape, ensuring it's sufficiently far from edges.

### 3. Unfolding (Chain-of-Thought)

The paper is unfolded step-by-step in reverse order. Each unfold:
- Reveals new hole positions (reflections from previous folds)
- Generates a CoT image showing current state
- Tracks all visible holes

### 4. Visualization

Multiple visualizations are generated:

- **Question image** (`_question.png`): Horizontal sequence showing each fold step and the hole punch
- **Silhouette** (`_silhouette.png`): Final unfolded state with all holes (correct answer)
- **Combined** (`_combined.png`): Multiple-choice format with question on top, 5 labeled answer choices (A-E) below
- **Chain-of-Thought** (`_cot_XX.png`): Progressive unfolding sequence showing how holes propagate
- **Wrong choices** (`_wrong_X.png`): 4 plausible but incorrect answer choices

The combined image presents the puzzle in a standard multiple-choice format, with the folding sequence at the top and all 5 answer options labeled A through E in the bottom row. The correct answer is randomly positioned among the choices.

## Output Format

### Dataset Metadata (`dataset_metadata.json`)

```json
{
  "description": "Paper folding puzzle dataset",
  "total_instances": 20,
  "grid_size": 3,
  "min_folds": 3,
  "max_folds": 5,
  "puzzles": [...]
}
```

### Puzzle Metadata (`puzzle_XXXX/metadata.json`)

```json
{
  "puzzle_id": 1,
  "grid_size": 3,
  "num_folds": 4,
  "fold_types": ["horizontal", "vertical", "diag_pos", "horizontal"],
  "question_image": "1_question.png",
  "silhouette_image": "1_silhouette.png",
  "combined_image": "1_combined.png",
  "cot_images": [
    "1_cot_00.png",
    "1_cot_01.png",
    "1_cot_02.png",
    "1_cot_03.png"
  ],
  "wrong_choices": [
    "1_wrong_0.png",
    "1_wrong_1.png",
    "1_wrong_2.png",
    "1_wrong_3.png"
  ],
  "correct_choice": "C",
  "correct_choice_index": 2,
  "choices": ["A", "B", "C", "D", "E"],
  "question": "If you fold the paper as shown, punch a hole, and unfold it, where will all the holes be?"
}
```

