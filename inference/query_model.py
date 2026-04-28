#!/usr/bin/env python3
"""
Wrapper CLI for querying OpenAI, Google Gemini/Veo, or OpenRouter models against the benchmark.

The model name prefix determines the provider:
- gpt-*      → query_openai_model.py
- gemini-* / veo-* → query_google_model.py
- everything else  → query_openrouter.py

Results are saved as responses_0.json in the output directory.
If the file already exists and contains errors, failed samples are re-queried automatically.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional, List, Tuple

from query_openai_model import run as run_openai
from query_openrouter import run as run_openrouter
from query_google_model import run as run_gemini
from utils import response_has_error, response_is_no_images_timeout


def _response_has_images(resp: dict) -> bool:
    """
    Check whether a serialized response dict contains any generated images.
    Mirrors the minimal logic used in utils.analyze_existing_responses and
    query_google_model.count_generated_images.
    """
    api_response = resp.get("api_response") or {}
    candidates = api_response.get("candidates", [])
    for candidate in candidates:
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        for part in parts:
            if part.get("saved_image_path"):
                return True
            inline_data = part.get("inline_data")
            if isinstance(inline_data, dict) and inline_data.get("data"):
                return True
    return False


def check_response_file_errors(
    response_file: Path,
    expected_num_samples: int = None,
    require_images: bool = False,
) -> Tuple[bool, int]:
    """
    Check if a response file exists and has errors that need requerying.
    Also checks if the file contains the expected number of responses.
    
    Args:
        response_file: Path to the responses JSON file
        expected_num_samples: Expected number of responses (optional). If provided,
                             will check if actual count matches expected.
        
    Returns:
        Tuple of (has_errors, num_errors)
        - has_errors: True if the file has errors OR has wrong number of responses
        - num_errors: Number of errors in the file (0 if file doesn't exist or no errors)
    """
    if not response_file.exists():
        return False, 0

    try:
        with open(response_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        responses = data.get("responses", [])

        # Count per-response issues (errors and, optionally, missing images).
        # When require_images is True, no-images/timeout responses are also
        # counted as issues so they get requeried with the current retry budget.
        issue_count = 0
        for resp in responses:
            if response_is_no_images_timeout(resp):
                if require_images:
                    issue_count += 1
                continue
            has_err = response_has_error(resp)
            has_image_issue = False
            if require_images and not has_err:
                has_image_issue = not _response_has_images(resp)
            if has_err or has_image_issue:
                issue_count += 1
        
        # Check if the file has the correct number of responses
        if expected_num_samples is not None:
            actual_count = len(responses)
            if actual_count < expected_num_samples:
                print(f"      ⚠️  Too few responses in {response_file.name}: "
                      f"expected {expected_num_samples}, found {actual_count} "
                      f"(missing {expected_num_samples - actual_count})")
                # Treat insufficient count as an error condition requiring requerying
                return True, issue_count
        
        return issue_count > 0, issue_count
    except (json.JSONDecodeError, IOError, KeyError):
        # If we can't read the file, assume it needs requerying
        return True, -1


def discover_levels(dataset_path: Path) -> List[Path]:
    """
    Discover level directories in a dataset.
    Returns sorted list of level_XX directories found under dataset_path.
    """
    level_dirs = sorted(dataset_path.glob("level_*"))
    return level_dirs



def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        description="Query benchmark datasets using OpenAI or Google models."
    )
    parser.add_argument(
        "--task",
        required=True,
        help="Task name (e.g., form-board).",
    )
    parser.add_argument(
        "--dataset",
        required=True,
        help="Path to the dataset directory (base output folder with level_XX subdirs).",
    )
    parser.add_argument(
        "--model",
        default="gpt-5-nano",
        help="Model name. Prefix determines provider (gpt*, gemini*, or veo*).",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output JSON file for responses.",
    )
    parser.add_argument(
        "--num-samples",
        type=int,
        default=None,
        help="Total number of samples to query across all levels (default: all).",
    )
    parser.add_argument(
        "--samples-per-level",
        type=int,
        default=None,
        help="Number of samples to query per level. Overrides --num-samples when using level-based datasets.",
    )
    parser.add_argument(
        "--levels",
        type=str,
        default=None,
        help="Comma-separated list of levels to query (e.g., '1,2,3' or '1-5'). Default: all levels.",
    )
    parser.add_argument(
        "--cache-interval",
        type=int,
        default=1,
        help="Save intermediate cache every N samples (default: 1).",
    )
    parser.add_argument(
        "--prompt-file",
        default="simple.txt",
        help="Prompt filename to load from the task's prompts folder.",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Generic API key fallback if provider-specific keys are not supplied.",
    )
    parser.add_argument(
        "--openai-api-key",
        default=None,
        help="Explicit OpenAI API key (overrides --api-key when querying GPT models).",
    )
    parser.add_argument(
        "--gemini-api-key",
        default=None,
        help="Explicit Gemini API key (overrides --api-key when querying Gemini models).",
    )
    parser.add_argument(
        "--reasoning-effort",
        type=str,
        default="high",
        choices=["low", "medium", "high"],
        help="Reasoning effort level for reasoning models (OpenAI GPT-5/o1, Google Gemini 2.5/3). Default: high.",
    )
    parser.add_argument(
        "--max-no-image-attempts",
        type=int,
        default=3,
        help=(
            "For Gemini generate_images prompts: maximum number of times to retry a sample "
            "when the model returns no images. Default: 3."
        ),
    )
    def str_to_bool(value):
        """Convert string to boolean for argparse."""
        if isinstance(value, bool):
            return value
        if value.lower() in ('true', '1', 'yes'):
            return True
        elif value.lower() in ('false', '0', 'no'):
            return False
        else:
            raise argparse.ArgumentTypeError(f"Boolean value expected, got '{value}'")
    
    parser.add_argument(
        "--tool-use",
        type=str_to_bool,
        default=False,
        help="Whether to use tools for the model. Default: False. Only supported for OpenAI models.",
    )

    args = parser.parse_args(argv)

    task = args.task
    dataset = Path(args.dataset)
    model = args.model
    output = Path(args.output)
    num_samples = args.num_samples
    samples_per_level = args.samples_per_level
    cache_interval = args.cache_interval
    prompt_file = args.prompt_file if args.prompt_file.endswith(".txt") else args.prompt_file + ".txt"

    reasoning_effort = args.reasoning_effort
    tool_use = args.tool_use
    max_no_image_attempts = args.max_no_image_attempts

    # Determine provider
    model_lower = model.lower()
    if model_lower.startswith("gemini") or model_lower.startswith("veo"):
        # Route Gemini and Veo models to Google API
        # Veo is Google's video generation model
        api_key = args.gemini_api_key or args.api_key
        run_fn = run_gemini
        if tool_use:
            print("Tool use is not supported for Gemini/Veo models. Setting tool_use to False.")
            tool_use = False
    elif model_lower.startswith("gpt"):
        api_key = args.openai_api_key or args.api_key
        run_fn = run_openai
    elif model_lower.startswith("qwen") and "/" not in model:
        # Route Qwen models through OpenRouter with qwen/ prefix
        model = f"qwen/{model}"
        api_key = args.api_key  # Uses OPENROUTER_API_KEY env var
        run_fn = run_openrouter
        if tool_use:
            print("Tool use is not supported for Qwen models. Setting tool_use to False.")
            tool_use = False
        if reasoning_effort != "high":
            print("Reasoning effort is not supported for Qwen models. Setting reasoning_effort to high.")
            reasoning_effort = "high"
    elif model_lower.startswith("claude") and "/" not in model:
        # Route Anthropic Claude models through OpenRouter with anthropic/ prefix
        model = f"anthropic/{model}"
        api_key = args.api_key  # Uses OPENROUTER_API_KEY env var
        run_fn = run_openrouter
    elif model_lower.startswith("llama") and "/" not in model:
        # Route Meta Llama models through OpenRouter with meta-llama/ prefix
        model = f"meta-llama/{model}"
        api_key = args.api_key  # Uses OPENROUTER_API_KEY env var
        run_fn = run_openrouter
    elif model_lower.startswith("mistral") and "/" not in model:
        # Route Mistral models through OpenRouter with mistralai/ prefix
        model = f"mistralai/{model}"
        api_key = args.api_key  # Uses OPENROUTER_API_KEY env var
        run_fn = run_openrouter
    elif "/" in model_lower:
        # OpenRouter models with explicit provider/model format
        api_key = args.api_key  # Uses OPENROUTER_API_KEY env var
        run_fn = run_openrouter
    else:
        parser.error(
            "Model name must start with 'gpt' (OpenAI), 'gemini' or 'veo' (Google), "
            "or use provider/model format for OpenRouter (e.g., 'qwen/qwen3-vl-235b-a22b-thinking')."
        )
    
    # Validate reasoning effort for OpenRouter models
    # OpenRouter doesn't support specifying reasoning effort - it always uses the model's default
    if run_fn == run_openrouter and reasoning_effort != "high":
        parser.error(
            f"ERROR: Cannot use reasoning effort '{reasoning_effort}' with OpenRouter models.\n"
            f"       OpenRouter does not support specifying reasoning effort levels.\n"
            f"       Model: {model}\n"
            f"       Please use --reasoning-effort high (default) or use native API for this model."
        )

    # Check for level-based structure
    level_dirs = discover_levels(dataset)
    
    # If we're using a Gemini generate_images prompt, inform user about no-image handling
    require_images = run_fn == run_gemini and "generate_images" in prompt_file
    if require_images:
        print(
            f"\n🖼️ Using generate_images prompt '{prompt_file}'. "
            f"Responses without images will be retried up to {max_no_image_attempts} times "
            f"and logged in 'responses_no_images.json' next to the main responses files."
        )
    
    if level_dirs:
        # Level-based dataset structure
        print(f"Detected level-based dataset with {len(level_dirs)} levels")
        
        # Parse --levels argument if provided
        levels_to_query = None
        if args.levels:
            levels_to_query = set()
            for part in args.levels.split(","):
                part = part.strip()
                if "-" in part:
                    start, end = part.split("-")
                    levels_to_query.update(range(int(start), int(end) + 1))
                else:
                    levels_to_query.add(int(part))
        
        # Filter level directories
        if levels_to_query:
            level_dirs = [
                d for d in level_dirs 
                if int(d.name.split("_")[1]) in levels_to_query
            ]
            print(f"Querying levels: {sorted(levels_to_query)}")
        
        # Query each level
        for level_dir in level_dirs:
            level_num = int(level_dir.name.split("_")[1])

            level_output_dir = output.parent / f"level_{level_num:02d}"
            level_output_dir.mkdir(parents=True, exist_ok=True)
            level_output = level_output_dir / "responses_0.json"

            effective_samples = samples_per_level if samples_per_level else num_samples

            has_errors, num_errors = check_response_file_errors(
                level_output,
                effective_samples,
                require_images=require_images,
            )

            if level_output.exists() and not has_errors:
                print(f"\n✅ Level {level_num}: Already complete with no errors. Skipping.")
                continue

            if has_errors:
                print(f"\n🔄 Level {level_num}: Found {num_errors} errors. Requerying failed samples...")
            else:
                print(f"\n{'='*60}")
                print(f"Querying Level {level_num}")

            print(f"Output: {level_output}")
            print(f"{'='*60}")

            run_fn(
                task=task,
                dataset=level_dir,
                model=model,
                output=level_output,
                api_key=api_key,
                num_samples=effective_samples,
                cache_interval=cache_interval,
                prompt_file=prompt_file,
                reasoning_effort=reasoning_effort,
                tool_use=tool_use,
                max_no_image_attempts=max_no_image_attempts,
            )
    else:
        # Flat dataset structure (no level subdirectories)
        print("Using flat dataset structure")

        run_output = output.parent / "responses_0.json"

        has_errors, num_errors = check_response_file_errors(
            run_output,
            num_samples,
            require_images=require_images,
        )

        if run_output.exists() and not has_errors:
            print(f"\n✅ Already complete with no errors. Skipping.")
        else:
            if has_errors:
                print(f"\n🔄 Found {num_errors} errors. Requerying failed samples...")
            else:
                print(f"\n{'='*60}")
                print("Querying dataset")

            print(f"Output: {run_output}")
            print(f"{'='*60}")

            run_fn(
                task=task,
                dataset=dataset,
                model=model,
                output=run_output,
                api_key=api_key,
                num_samples=num_samples,
                cache_interval=cache_interval,
                prompt_file=prompt_file,
                reasoning_effort=reasoning_effort,
                tool_use=tool_use,
                max_no_image_attempts=max_no_image_attempts,
            )


if __name__ == "__main__":
    main()

