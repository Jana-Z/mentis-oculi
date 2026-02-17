# MentisOculi: Benchmark Datasets for Visual Reasoning

This repository contains the datasets for **MentisOculi**, a benchmark suite designed to evaluate visual reasoning capabilities in large language models, multimodal models, and unified multimodal models.

## Overview

MentisOculi comprises five visual reasoning tasks designed to be best solved with mental imagery. Each task requires models to solve multi-step reasoning problems with geometric constraints, testing the ability to form, maintain, and manipulate visual representations.

## Datasets

| Dataset | Description | Reasoning Type |
|---------|-------------|----------------|
| **Form Board** | Match pieces to silhouettes | Spatial matching |
| **Hinge Folding** | Fold connected shapes via hinges | Sequential transformations |
| **Paper Fold** | Predict fold patterns | Spatial prediction |
| **Rush Hour** | Slide cars to free the red car | Sequential planning |
| **Sliding Puzzle** | Rearrange tiles to form image | Sequential moves |

## Structure

Each dataset follows a consistent structure:

```
datasets/
├── form-board/
│   ├── main.py                 # Generation script
│   ├── evaluate_responses.py   # Evaluation script
│   ├── prompts/                # Prompt templates
│   ├── pyproject.toml          # Dependencies
│   └── output/
│       └── level_XX/
│           └── puzzle_XXXX/
│               ├── metadata.json
│               ├── initial.png / question.png
│               ├── target.png (if applicable)
│               └── cot_XX.png (chain-of-thought steps)
├── hinge-folding/
├── paper-fold/
├── rushhour/
└── sliding-puzzle/
```

## Naming Conventions

- **Puzzle folders**: `puzzle_XXXX` (1-indexed, zero-padded to 4 digits)
- **Levels**: `level_XX` (zero-padded to 2 digits)
- **Images**:
  - `initial.png` or `question.png` - Input state
  - `target.png` - Target state (where applicable)
  - `cot_XX.png` - Chain-of-thought intermediate steps
- **Metadata**: `metadata.json` - Puzzle configuration and solution

## Difficulty Levels

Each dataset contains 5 difficulty levels with 50 puzzles each:

| Level | Description |
|-------|-------------|
| Level 1 | 1 reasoning step |
| Level 2 | 2 reasoning steps |
| Level 3 | 3 reasoning steps |
| Level 4 | 4 reasoning steps |
| Level 5 | 5 reasoning steps |

## Usage

### Running Generation Scripts

Each dataset can be regenerated using its `main.py` script:

```bash
cd <dataset-name>
uv sync
uv run main.py --help
```

### Evaluating Responses

Each dataset includes an evaluation script:

```bash
uv run evaluate_responses.py --responses responses.json
```

#### Input Format

The evaluation scripts expect a JSON file with the following structure:

```json
{
  "responses": [
    {
      "puzzle_id": 1,
      "puzzle_dir": "output/level_01/puzzle_0001",
      "output_parsed": {
        "answer": "..."
      },
      "metadata": {
        // Original puzzle metadata (optional, used for validation)
      }
    },
    ...
  ],
  "dataset_path": "output/level_01"  // Optional fallback for puzzle_dir
}
```

**Required fields per response:**
- `output_parsed.answer`: The model's answer in the expected format (see below)
- `puzzle_dir` OR (`puzzle_id` + `dataset_path`): Path to locate the puzzle metadata

**Answer formats by dataset:**

| Dataset | Answer Format | Example |
|---------|---------------|---------|
| Form Board | Space-separated piece labels | `"A C E"` |
| Hinge Folding | Comma-separated hinge rotations | `"A 90, B 180"` |
| Paper Fold | Single letter (A-E) | `"C"` |
| Rush Hour | Comma-separated vehicle moves | `"A forward, B backward, R forward"` |
| Sliding Puzzle | Space-separated directions | `"up right down left"` |

#### Output

The evaluation script outputs:
- Accuracy metrics with 95% confidence intervals
- Comparison against random baseline performance
- Per-level breakdown (if applicable)
- Visualization plots saved alongside the responses file

## Citation

If you use this benchmark in your research, please cite:

```bibtex
@article{zeller2026mentisoculis,
  title={MentisOculi: Revealing the Limits of Reasoning with Mental Imagery},
  author={Zeller, Jana and Wiedemer, Thadd{\"a}us and Li, Fanfei and Klein, Thomas and Bethge, Matthias and Wichmann, Felix and Cotterell, Ryan and Brendel, Wieland},
  journal={arXiv preprint arXiv:2602.02465},
  year={2026}
}
```
