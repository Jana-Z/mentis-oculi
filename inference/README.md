# MentisOculi Inference

Scripts for querying models against the benchmark. The main entry point is `query_model.py`, which routes to the appropriate provider based on the model name.

## Setup

```bash
uv sync
```

API keys are passed as command-line arguments (see below).

## Usage

```bash
python inference/query_model.py \
  --task <task> \
  --dataset datasets/<task>/output \
  --model <model> \
  --prompt-file <prompt> \
  --output results/responses/<model>/<strategy>/<task> \
  [--openai-api-key KEY | --gemini-api-key KEY]
```

The model name prefix determines the provider:
- `gpt-*` → OpenAI API (`query_openai_model.py`)
- `gemini-*` / `veo-*` → Google Gemini API (`query_google_model.py`)
- Everything else → OpenRouter (`query_openrouter.py`)

## Key arguments

| Argument | Description |
|---|---|
| `--task` | Task name, e.g. `rushhour`, `form-board` |
| `--dataset` | Path to the task's `output/` directory (contains `level_01/` … `level_05/`) |
| `--model` | Model identifier, e.g. `gpt-5.1`, `gemini-3-pro-preview` |
| `--prompt-file` | Prompt template filename from the task's `prompts/` folder (default: `simple.txt`) |
| `--output` | Output directory; responses saved as `responses_0.json` per level |
| `--samples-per-level` | Number of instances to query per level (default: all) |
| `--levels` | Levels to query, e.g. `1-5` or `1,3,5` (default: all) |
| `--reasoning-effort` | `low` / `medium` / `high` for reasoning models (default: `high`) |
| `--tool-use` | Enable tool use (OpenAI models only) |
| `--max-no-image-attempts` | Retries when no images are generated (generate_images prompts, default: 3) |
| `--openai-api-key` | OpenAI API key |
| `--gemini-api-key` | Google Gemini API key |
| `--api-key` | Generic fallback key for OpenRouter |

## Reproducing paper baselines

Each strategy corresponds to a prompt file in `datasets/<task>/prompts/`. The table below maps the strategy names in `results/results_table.csv` to the prompt files and flags used.

| Strategy | `--prompt-file` | Additional flags |
|---|---|---|
| `simple` | `simple.txt` | — |
| `simple_text` | `simple_text.txt` | — |
| `generate_images` | `generate_images.txt` | — |
| `tool_use` | `simple.txt` | `--tool-use true` |
| `icl` | `icl.txt` | — |
| `icl_intermediate_images` | `icl_intermediate_images.txt` | — |
| `evolved` | `evolved.txt` | — |

### Example: replicate GPT-5.1 simple on rushhour

```bash
python inference/query_model.py \
  --task rushhour \
  --dataset datasets/rushhour/output \
  --model gpt-5.1 \
  --prompt-file simple.txt \
  --output my_responses/gpt-5.1/simple/rushhour \
  --samples-per-level 30 \
  --openai-api-key $OPENAI_API_KEY
```

## Evaluating responses

Each task has an `evaluate_responses.py` script that scores a `responses_0.json` file:

```bash
cd datasets/<task>
uv run evaluate_responses.py \
  --responses ../../my_responses/<model>/<strategy>/<task>/<level>/responses_0.json
```
