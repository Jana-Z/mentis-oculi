"""
Utilities to query models via OpenRouter on benchmark datasets and save responses.
Uses the OpenAI-compatible API with OpenRouter's base URL.
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from tqdm import tqdm

from utils import (
    encode_image_base64,
    load_prompt,
    process_prompt_with_images,
    extract_json_from_text,
    save_responses,
    load_dataset_samples,
    get_puzzles_to_query,
    print_retry_stats,
    response_has_error,
)

# Cost per million output tokens for OpenRouter models
# https://openrouter.ai/models
COST_PER_OUTPUT_TOKEN = {
    'qwen/qwen3-vl-235b-a22b-thinking': 3.5 / 1_000_000,
    # Google Gemini models via OpenRouter
    'google/gemini-2.5-pro': 15 / 1_000_000,
    'google/gemini-2.5-flash-image': 2.5 / 1_000_000,
    'google/gemini-3-pro-preview': 12 / 1_000_000,
    'google/gemini-3-pro-image-preview': 12 / 1_000_000,
}


def build_prompt_content(prompt: str, images: List[Path]) -> List[dict]:
    """
    Build OpenRouter/OpenAI chat API content format with interleaved text and images.
    
    Returns:
        List of content dicts with type: text/image_url
    """
    content = []
    parts = prompt.split('[IMAGE_')
    
    # Add initial text
    if parts[0]:
        content.append({
            "type": "text",
            "text": parts[0]
        })
    
    # Add images and remaining text
    for i, part in enumerate(parts[1:]):
        if i < len(images):
            image_data = encode_image_base64(images[i])
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{image_data}"
                }
            })
        
        # Add text after placeholder
        remaining = part[part.find(']')+1:] if ']' in part else part
        if remaining:
            content.append({
                "type": "text",
                "text": remaining
            })
    
    return content


def query_openrouter(
    prompt_content: List[dict], 
    model: str, 
    client,
    config: dict = None
) -> tuple:
    """
    Query OpenRouter model with prompt content.
    
    Args:
        prompt_content: List of content dicts (text/image_url)
        model: Model name (e.g., 'qwen/qwen3-vl-235b-a22b-thinking')
        client: OpenAI client configured for OpenRouter
        config: Optional config (temperature, max_tokens, etc.)
        
    Returns:
        (response_text, full_api_response_dict)
    """
    if config is None:
        config = {}
    
    # Build API kwargs
    api_kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": prompt_content}],
    }
    
    # Add optional parameters from config
    if "temperature" in config:
        api_kwargs["temperature"] = config["temperature"]
    if "max_tokens" in config:
        api_kwargs["max_tokens"] = config["max_tokens"]
    if "top_p" in config:
        api_kwargs["top_p"] = config["top_p"]
    
    # Optional: Add site info headers for OpenRouter rankings
    extra_headers = {}
    if os.environ.get("OPENROUTER_SITE_URL"):
        extra_headers["HTTP-Referer"] = os.environ["OPENROUTER_SITE_URL"]
    if os.environ.get("OPENROUTER_SITE_NAME"):
        extra_headers["X-Title"] = os.environ["OPENROUTER_SITE_NAME"]
    
    if extra_headers:
        api_kwargs["extra_headers"] = extra_headers

    if model == 'qwen/qwen3-vl-235b-a22b-thinking':
        api_kwargs.setdefault("extra_body", {})
        api_kwargs["extra_body"]["provider"] = {
            "allow_fallbacks": False,
            "only": ["NovitaAI"],
        }

    
    # Call API
    response = client.chat.completions.create(**api_kwargs)
    
    # Validate response - empty responses need to be re-queried
    if response is None:
        raise ValueError("API returned None response - possible rate limit or service error")
    
    if not response.choices:
        raise ValueError("API returned empty choices - possible rate limit, content filter, or model overload")
    
    if response.choices[0].message is None:
        raise ValueError("API returned None message - model may have failed to generate response")
    
    # Extract text response
    response_text = response.choices[0].message.content
    
    if response_text is None:
        raise ValueError("API returned None content - model may have refused to respond")
    
    # Serialize full API response
    api_response_dict = response.model_dump()
    
    return response_text, api_response_dict


def compute_token_stats(responses: List[dict], model: str) -> Optional[dict]:
    """Compute token usage statistics from responses"""
    total_input_tokens = 0
    total_output_tokens = 0
    total_reasoning_tokens = 0
    num_valid_responses = 0
    
    for resp in responses:
        if response_has_error(resp) or not resp.get("api_response"):
            continue
        
        usage = resp["api_response"].get("usage", {})
        
        total_input_tokens += usage.get("prompt_tokens", 0)
        total_output_tokens += usage.get("completion_tokens", 0)
        total_output_tokens += usage.get("thoughts_token_count", 0)
        
        num_valid_responses += 1
    
    if num_valid_responses == 0:
        return None
    
    total_cost = 0.0
    avg_cost = 0.0
    if model in COST_PER_OUTPUT_TOKEN:
        total_cost = total_output_tokens * COST_PER_OUTPUT_TOKEN[model]
        avg_cost = total_cost / num_valid_responses

    return {
        "total_input_tokens": total_input_tokens,
        "avg_input_tokens": total_input_tokens / num_valid_responses,
        "total_output_tokens": total_output_tokens,
        "avg_output_tokens": total_output_tokens / num_valid_responses,
        "total_reasoning_tokens": total_reasoning_tokens,
        "avg_reasoning_tokens": total_reasoning_tokens / num_valid_responses,
        "num_valid_responses": num_valid_responses,
        "total_cost": total_cost,
        "avg_cost": avg_cost,
    }


def _merge_responses(
    all_puzzles: List[Path],
    successful_responses: Dict[str, Dict],
    new_responses: Dict[str, Dict],
) -> List[Dict[str, object]]:
    """
    Merge existing successful responses with new responses in the original puzzle order.
    
    Args:
        all_puzzles: List of all puzzle directories in original order
        successful_responses: Dict mapping puzzle_dir -> response for existing successes
        new_responses: Dict mapping puzzle_dir -> response for newly queried puzzles
        
    Returns:
        List of responses in the same order as all_puzzles
    """
    merged = []
    for puzzle_dir in all_puzzles:
        puzzle_dir_str = str(puzzle_dir)
        # Prefer new response (in case of retry), then existing successful response
        if puzzle_dir_str in new_responses:
            merged.append(new_responses[puzzle_dir_str])
        elif puzzle_dir_str in successful_responses:
            merged.append(successful_responses[puzzle_dir_str])
        # If neither, puzzle wasn't queried (shouldn't happen in normal flow)
    return merged


def run(
    task: str,
    dataset: str | Path,
    model: str,
    output: str | Path,
    *,
    api_key: Optional[str] = None,
    num_samples: Optional[int] = None,
    cache_interval: int = 1,
    config: Optional[Dict[str, object]] = None,
    prompt_file: str = "simple.txt",
    **kwargs
) -> Optional[Dict[str, object]]:
    """
    Query an OpenRouter model on a benchmark dataset.
    
    Args:
        task: Task name (form-board, paper-fold, etc.)
        dataset: Path to dataset directory
        model: OpenRouter model name (e.g., 'qwen/qwen3-vl-235b-a22b-thinking')
        output: Output path for responses JSON
        api_key: OpenRouter API key (or set OPENROUTER_API_KEY env var)
        num_samples: Limit number of samples to query
        cache_interval: Save intermediate results every N samples
        config: Model config (temperature, max_tokens, etc.)
        prompt_file: Prompt template filename
        
    Returns:
        Token statistics dict or None on error
    """
    print("=" * 60)
    print("Visual Thinking Benchmarks - OpenRouter Query")
    print("=" * 60)
    print(f"Task: {task}")
    print(f"Dataset: {dataset}")
    print(f"Model: {model}")
    print(f"Output: {output}")
    print("=" * 60)

    try:
        from openai import OpenAI

        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=api_key or os.environ.get("OPENROUTER_API_KEY")
        )
        print("✓ OpenRouter client initialized")
    except ImportError:
        print("✗ Error: openai package not installed")
        print("  Run: uv pip install openai")
        return None
    except Exception as exc:
        print(f"✗ Error initializing OpenRouter client: {exc}")
        print("  Make sure OPENROUTER_API_KEY is set")
        return None

    try:
        prompt_template = load_prompt(task, prompt_file)
        print(f"✓ Loaded prompt template for {task}/{prompt_file}")
    except FileNotFoundError as exc:
        print(f"✗ {exc}")
        return None

    dataset_path = Path(dataset)
    output_path = Path(output)
    all_puzzles = load_dataset_samples(dataset_path)

    if not all_puzzles:
        print(f"✗ No puzzles found in {dataset_path}")
        return None

    if num_samples:
        all_puzzles = all_puzzles[:num_samples]

    print(f"✓ Found {len(all_puzzles)} puzzles in dataset")
    
    # Check for existing responses and determine which puzzles need querying
    puzzles_to_query, successful_responses, stats = get_puzzles_to_query(
        all_puzzles, output_path
    )
    print_retry_stats(stats, output_path)
    
    if not puzzles_to_query:
        print("✅ All samples already successfully queried. Nothing to do.")
        # Return existing stats
        existing_responses = list(successful_responses.values())
        token_stats = compute_token_stats(existing_responses, model)
        return token_stats
    
    print(f"→ Will query {len(puzzles_to_query)} puzzles: {puzzles_to_query}")
    print()

    # Track new responses from this run
    new_responses: Dict[str, Dict[str, object]] = {}
    errors = 0

    for idx, puzzle_dir in enumerate(tqdm(puzzles_to_query, desc="Querying"), 1):
        metadata_file = puzzle_dir / "metadata.json"
        if not metadata_file.exists():
            print(f"⚠ No metadata in {puzzle_dir.name}, skipping")
            continue

        with open(metadata_file, "r", encoding="utf-8") as handle:
            metadata = json.load(handle)

        puzzle_id = metadata.get(
            "puzzle_id",
            metadata.get("instance_id", metadata.get("sample_id", "unknown")),
        )

        try:
            processed_prompt, image_paths = process_prompt_with_images(
                prompt_template, puzzle_dir
            )

            if not image_paths and "text" not in prompt_file:
                raise ValueError("No images found for this puzzle")

            prompt_content = build_prompt_content(processed_prompt, image_paths)

            effective_config = config or {}

            # Retry logic for API failures (e.g., None content responses)
            max_retries = 5
            response_text = None
            api_response = None
            last_error = None
            
            for attempt in range(max_retries):
                try:
                    response_text, api_response = query_openrouter(
                        prompt_content, model, client, effective_config
                    )
                    # If we got a valid response, break out of retry loop
                    break
                except ValueError as exc:
                    error_msg = str(exc)
                    # Retry for specific recoverable errors
                    if "API returned None" in error_msg or "may have refused to respond" in error_msg:
                        if attempt < max_retries - 1:
                            print(f"\n⚠️  Attempt {attempt + 1}/{max_retries} failed for puzzle {puzzle_id}: {error_msg}")
                            print(f"   Retrying...")
                            continue
                        else:
                            print(f"\n✗ All {max_retries} attempts failed for puzzle {puzzle_id}: {error_msg}")
                            raise
                    else:
                        # For other errors, don't retry
                        raise
            
            output_parsed = extract_json_from_text(response_text)

            new_responses[str(puzzle_dir)] = {
                "puzzle_id": puzzle_id,
                "puzzle_dir": str(puzzle_dir),
                "prompt": prompt_content,
                "config": effective_config,
                "output_text": response_text,
                "output_parsed": output_parsed,
                "api_response": api_response,
                "images_used": [str(path) for path in image_paths],
                "metadata": metadata,
                "error": None,
            }

        except Exception as exc:
            errors += 1
            print(f"\n✗ Error on puzzle {puzzle_id}: {exc}")

            new_responses[str(puzzle_dir)] = {
                "puzzle_id": puzzle_id,
                "puzzle_dir": str(puzzle_dir),
                "prompt": None,
                "config": None,
                "output_text": None,
                "output_parsed": None,
                "api_response": None,
                "images_used": [],
                "metadata": metadata,
                "error": str(exc),
            }

        # Intermediate save: merge new responses with existing successful ones
        if cache_interval and idx % cache_interval == 0:
            merged_responses = _merge_responses(all_puzzles, successful_responses, new_responses)
            token_stats = compute_token_stats(merged_responses, model)
            save_responses(merged_responses, output, task, model, dataset_path, token_stats)
            print(f"\n💾 Intermediate cache saved ({idx}/{len(puzzles_to_query)} new queries) to {output}")
    
    # Final merge: combine existing successful responses with new responses
    responses = _merge_responses(all_puzzles, successful_responses, new_responses)

    token_stats = compute_token_stats(responses, model)
    save_responses(responses, output, task, model, dataset_path, token_stats)

    # Count total errors in merged responses
    total_errors = sum(1 for r in responses if response_has_error(r))
    new_successes = len(puzzles_to_query) - errors

    print()
    print("=" * 60)
    print(f"✅ Saved {len(responses)} responses to {output}")
    print(f"   From existing: {stats.get('skipping', 0)} successful")
    print(f"   Newly queried: {len(puzzles_to_query)}")
    print(f"      → Successful: {new_successes}")
    print(f"      → Failed: {errors}")
    print(f"   Total errors remaining: {total_errors}")

    if token_stats:
        print()
        print("📊 Token Usage Statistics:")
        print(f"   Total input tokens: {token_stats['total_input_tokens']:,}")
        print(f"   Avg input tokens/sample: {token_stats['avg_input_tokens']:.1f}")
        print(f"   Total output tokens: {token_stats['total_output_tokens']:,}")
        print(f"   Avg output tokens/sample: {token_stats['avg_output_tokens']:.1f}")
        if token_stats['total_reasoning_tokens'] > 0:
            print(f"   Total reasoning tokens: {token_stats['total_reasoning_tokens']:,}")
            print(f"   Avg reasoning tokens/sample: {token_stats['avg_reasoning_tokens']:.1f}")
        print(f"   Valid responses: {token_stats['num_valid_responses']}")
        print(f"   Cost: ~${token_stats['total_cost']:.4f} USD")
        print(f"   Cost: ~${token_stats['avg_cost']:.6f} USD per sample")

    print("=" * 60)
    return token_stats


def main() -> None:
    raise SystemExit(
        "query_openrouter.py no longer provides a CLI entry point. "
        "Use query_model.py instead."
    )


if __name__ == "__main__":
    main()
