# Form Board Test Puzzle Generator

Generate dissect-and-assemble geometry puzzles similar to the VZ1 Form Board Test.

## Overview

This generator creates visual reasoning puzzles where:
- A **target shape** is shown (outline only)
- **5 pieces** are presented (some necessary, some distractors)
- The task is to identify which pieces are needed to form the target

### Example Puzzle

![Form Board Example](output/level_03/puzzle_0001/combined.png)

*Example puzzle showing target shape (left) and five candidate pieces A-E (right). The task is to identify which pieces are needed to assemble the target.*

## Quick Start

Generate a dataset with default settings (60 total instances):

```bash
uv run main.py
```

This will create an `output/` directory with puzzles organized as:

```
output/
├── dataset_metadata.json          # Overall dataset info
├── puzzle_0001/
│   ├── silhouette.png             # Target shape (outline only)
│   ├── bordered.png               # Target with internal structure
│   ├── combined.png               # Target + all pieces labeled
│   ├── cot_00.png                 # Chain-of-thought step 1
│   ├── cot_01.png                 # Chain-of-thought step 2
│   ├── cot_XX.png                 # ... (one per solution piece)
│   ├── piece_1.png through piece_5.png  # Individual pieces
│   ├── choices.png                # All 5 pieces combined
│   └── metadata.json              # Puzzle-specific metadata
├── puzzle_0002/
│   └── ...
...
```

## Usage

### Basic Generation

```bash
# Generate per-level datasets (50 samples each)
uv run main.py --instances 50 --min-pieces 2 --max-pieces 2 --output-dir output/level_02 --seed 42
uv run main.py --instances 50 --min-pieces 3 --max-pieces 3 --output-dir output/level_03 --seed 142
uv run main.py --instances 50 --min-pieces 4 --max-pieces 4 --output-dir output/level_04 --seed 242
uv run main.py --instances 50 --min-pieces 5 --max-pieces 5 --output-dir output/level_05 --seed 342

# Or use the repository-wide generation script:
cd .. && ./generate_all_datasets.sh --task form-board
```

### Visualize Puzzles

To inspect a generated puzzle:

```bash
# View a specific puzzle
uv run visualize_puzzle.py output/puzzle_0001
```

This will display the target shape and all pieces with solution information.

### Available Shapes

The generator includes 12 different target shapes:
- **rectangle** - Simple rectangular shape (like VZ1 example)
- **square** - Basic square
- **L_shape** - L-shaped polygon
- **T_shape** - T-shaped polygon
- **cross** - Plus/cross shape
- **U_shape** - U-shaped polygon
- **trapezoid** - Four-sided trapezoid
- **pentagon** - Five-sided shape
- **stairs** - Stair-step pattern
- **arrow** - Arrow pointing right
- **diamond** - Diamond/rhombus shape
- **hexagon** - Six-sided polygon

## Difficulty Levels

The complexity of form-board puzzles is controlled by the **number of solution pieces** needed to assemble the target shape. Each level corresponds to an exact number of CoT steps:

| Level | Solution Pieces | CoT Steps | Output Directory |
|-------|----------------|-----------|------------------|
| **1** | 1 | 1 | `output/level_01` |
| **2** | 2 | 2 | `output/level_02` |
| **3** | 3 | 3 | `output/level_03` |
| **4** | 4 | 4 | `output/level_04` |
| **5** | 5 | 5 | `output/level_05` |

**Note**: Level 1 (1 piece) is trivial since the single piece is identical to the target shape.

Each solution piece requires identifying:
1. Which piece fills a specific region
2. How it fits with previously placed pieces
3. What portion of the target remains unfilled

More pieces = more sequential reasoning steps = higher difficulty.

### Generating Per-Level Datasets

```bash
# Generate 50 samples for each level
for level in 1 2 3 4 5; do
    uv run main.py --instances 50 --min-pieces $level --max-pieces $level \
        --output-dir output/level_0${level} --seed $((42 + (level-1)*100))
done
```

## How It Works

### 1. Target Shape Definition
Each target shape is defined by edges on a 5×5 integer grid using the format:
```
"row,col-row,col; row,col-row,col; ..."
```

### 2. Solution Piece Generation
- Randomly selects k ∈ {2, 3, 4, 5} solution pieces
- Cuts the target shape using straight lines through grid points
- Allowed slopes: ∞, 0, ±1, ±2, ±3

### 3. Distractor Generation
- Creates (5 - k) distractor pieces
- Distractors are sub-divisions of solution pieces
- Ensures no combination of distractors matches any solution piece area

### 4. Rendering

Multiple visualizations are generated for each puzzle:

- **Silhouette** (`_silhouette.png`): Target shape outline only
- **Bordered** (`_bordered.png`): Target with solution pieces showing internal structure
- **Combined** (`_combined.png`): Target (1) + all choice pieces (2) labeled A-E in one frame
- **Chain-of-Thought** (`_cot_XX.png`): Progressive assembly showing how solution pieces fill the target
- **Individual pieces**: Each piece rendered separately with dotted hatch pattern
- All visualizations maintain consistent scale

## Output Format

### Dataset Metadata (`dataset_metadata.json`)
```json
{
  "description": "Form Board Test puzzles",
  "num_shapes": 12,
  "instances_per_shape": 5,
  "total_instances": 60,
  "puzzles": [...]
}
```

### Puzzle Metadata (`puzzle_XXXX/metadata.json`)
```json
{
  "puzzle_id": 1,
  "shape_name": "rectangle",
  "instance_idx": 0,
  "silhouette_image": "silhouette.png",
  "bordered_image": "bordered.png",
  "combined_image": "combined.png",
  "cot_images": ["cot_00.png", "cot_01.png"],
  "choices_image": "choices.png",
  "pieces": [
    {
      "piece_id": 1,
      "image": "piece_1.png",
      "is_solution": true,
      "label": "A"
    },
    ...
  ],
  "question": "Which pieces in (2) are necessary to form the figure of (1)?",
  "solution_pieces": ["A", "C", "E"],
  "num_solution_pieces": 3
}
```

## Example Question Format

Like the VZ1 example:

```
Form Board Test

(1) [Target shape image]

(2) [Five pieces: A B C D E]

Question: Which pieces in (2) are necessary to form the figure of (1)?
Answer: [List of necessary pieces]
```

### Visual Chain-of-Thought

Each puzzle includes a visual chain-of-thought showing how the solution pieces progressively fill the target shape:

1. **Step 0** (`cot_00.png`): First solution piece
2. **Step 1** (`cot_01.png`): First + second solution piece
3. **Step N** (`cot_N.png`): All solution pieces assembled

This helps understand which pieces are actually needed vs. which are distractors.

## Dependencies

- `shapely` - Geometry operations
- `matplotlib` - Rendering
- `numpy` - Numerical operations
- `pillow` - Image processing

All dependencies are managed via `uv` and specified in `pyproject.toml`.

## Development

### Adding New Shapes

Edit `main.py` and add to the `TARGET_SHAPES` dictionary:

```python
TARGET_SHAPES = {
    ...
    "my_shape": "0,0-0,3; 0,3-3,3; 3,3-3,0; 3,0-0,0",
}
```

### Adjusting Parameters

Key parameters in `generate.py`:
- `ALLOWED_SLOPES` - Permitted cut line slopes
- `DEFAULT_PPU` - Pixels per grid unit (default: 100)
- `DPI` - Render resolution (default: 300)
