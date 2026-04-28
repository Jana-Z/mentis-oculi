# MentisOculi Benchmark Results

`results_table.csv` contains per-model × strategy × task × level accuracies for all baselines reported in the paper.

## Columns

| Column | Description |
|---|---|
| `model` | Model name |
| `strategy` | Prompting strategy (see below) |
| `task` | Benchmark task (`form-board`, `hinge-folding`, `paper-fold`, `rushhour`, `sliding-puzzle`) |
| `level` | Difficulty level (1–5) |
| `n_samples` | Number of instances evaluated (see notes below) |
| `accuracy` | Accuracy on the task |
| `correct` | Number of correct responses |
| `ci95_lower` / `ci95_upper` | 95% Wilson confidence interval |

## Strategies

| Strategy | Description |
|---|---|
| `simple` | Standard visual prompting: model receives the puzzle image and returns an answer |
| `simple_text` | Text-only prompting: puzzle state is transcribed to text; no image is provided |
| `generate_images` | Model generates intermediate reasoning images before answering |
| `tool_use` | Model has access to a tool that executes moves and returns updated board images |
| `video_generation` | Puzzle presented as a video; model answers from the video |
| `icl` | In-context learning: few-shot examples included in the prompt |
| `icl_intermediate_images` | ICL with intermediate reasoning images in the few-shot examples |
| `evolved` | Evolved prompt variant (GPT-5.1 reasoning effort low only) |

## Notes on `n_samples`

`n_samples` is the number of instances the model was actually queried on. The target is 30 per task × level; values below 30 reflect runs that could not be completed due to factors outside our control:

- **`generate_images`:** Some runs did not receive a response from the image generation API (e.g. timeouts, quota limits), so `n_samples` may be below 30.
- **`simple_text`:** Some runs experienced API timeouts on `rushhour` levels 3–5 (`gpt-5.1 simple_text`), reducing `n_samples` to as low as 16.
- **`humans`** (`strategy = human_average`): Accuracies are averaged across all 5 participants (2 authors + 3 external). Human evaluation was conducted on `rushhour` only (levels 2–5); `n_samples = 30` per participant. Confidence intervals are not provided for the average.
