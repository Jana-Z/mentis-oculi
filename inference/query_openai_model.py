"""
Utilities to query OpenAI models on benchmark datasets and save responses.
Each dataset folder can then evaluate the responses independently.
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from tqdm import tqdm

# Add parent directory to path for imports when run directly

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

COST_PER_OUTPUT_TOKEN = {
    'gpt-5-pro': 120 / 1000000,
    'gpt-5': 10 / 1000000,
    'gpt-5-mini': 2 / 1000000,
    'gpt-5-nano': 0.4 / 1000000,
    'gpt-5.1': 10 / 1000000,
    'qwen/qwen3-vl-235b-a22b-thinking': 1.2 / 1000000,
}


def build_prompt_content(prompt: str, images: List[Path]) -> List[dict]:
    """
    Build OpenAI API content format with interleaved text and images.
    Matches the format from OpenAI/cached_responses.
    
    Returns:
        List of content dicts with type: input_text/input_image
    """
    content = []
    parts = prompt.split('[IMAGE_')
    
    # Add initial text
    if parts[0]:
        content.append({
            "type": "input_text",
            "text": parts[0]
        })
    
    # Add images and remaining text
    for i, part in enumerate(parts[1:]):
        if i < len(images):
            image_data = encode_image_base64(images[i])
            content.append({
                "type": "input_image",
                "image_url": f"data:image/jpeg;base64,{image_data}"
            })
        
        # Add text after placeholder
        remaining = part[part.find(']')+1:] if ']' in part else part
        if remaining:
            content.append({
                "type": "input_text",
                "text": remaining
            })
    
    return content


def query_openai(prompt_content: List[dict], model: str, client, openai_config: dict = None) -> tuple:
    """
    Query OpenAI model with prompt content.
    
    Args:
        prompt_content: List of content dicts (input_text/input_image)
        model: Model name
        client: OpenAI client
        openai_config: OpenAI specific config (reasoning, etc.)
        
    Returns:
        (response_text, full_api_response_dict)
    """
    if openai_config is None:
        openai_config = {
            "model": model,
            "reasoning": {"effort": "high"}
        }
    
    # Convert our format to OpenAI API format
    api_content = []
    for item in prompt_content:
        if item["type"] == "input_text":
            api_content.append({"type": "input_text", "text": item["text"]})
        elif item["type"] == "input_image":
            api_content.append({
                "type": "input_image",
                "image_url": item["image_url"]
            })

    reasoning = openai_config.get("reasoning", None)
    if reasoning is None:
        print(f"WARNING: {model} reasoning effort not specified. Using default high effort")
        reasoning = {"effort": "high"}
    
    # Build API kwargs
    api_kwargs = {
        "model": model,
        "input": [{"role": "user", "content": api_content}],
        "reasoning": reasoning
    }
    
    # Add any additional fields from openai_config that aren't already handled
    # Fields we've already handled: model, reasoning
    handled_fields = {"model", "reasoning"}
    for key, value in openai_config.items():
        if key not in handled_fields:
            api_kwargs[key] = value

    print(f'Querying {model} with {api_kwargs}')

    # Call API
    response = client.responses.create(**api_kwargs)
    
    # Validate response - empty responses need to be re-queried
    if response is None:
        raise ValueError("API returned None response - possible rate limit or service error")
    
    # Extract text response
    response_text = response.output_text
    
    if response_text is None:
        raise ValueError("API returned None output_text - model may have refused to respond")
    
    # Serialize full API response
    api_response_dict = response.model_dump()
    
    return response_text, api_response_dict


def compute_token_stats(responses, model: str):
    """Compute token usage statistics from responses"""
    total_output_tokens = 0
    total_reasoning_tokens = 0
    num_valid_responses = 0
    
    for resp in responses:
        if response_has_error(resp) or not resp.get("api_response"):
            continue
        
        usage = resp["api_response"].get("usage", {})
        output_tokens_details = usage.get("output_tokens_details", {})
        
        total_output_tokens += usage.get("output_tokens", 0)
        total_reasoning_tokens += output_tokens_details.get("reasoning_tokens", 0)
        num_valid_responses += 1
    
    if num_valid_responses == 0:
        return None
    
    total_cost = 0.0
    avg_cost = 0.0
    if model in COST_PER_OUTPUT_TOKEN:
        total_cost = total_output_tokens * COST_PER_OUTPUT_TOKEN[model]
        avg_cost = total_cost / num_valid_responses

    return {
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
    openai_config: Optional[Dict[str, object]] = None,
    prompt_file: str = "simple.txt",
    reasoning_effort: str = "high",
    tool_use: bool = False,
    **kwargs,
) -> Optional[Dict[str, object]]:
    print("=" * 60)
    print("Visual Thinking Benchmarks - Model Query")
    print("=" * 60)
    print(f"Task: {task}")
    print(f"Dataset: {dataset}")
    print(f"Model: {model}")
    print(f"Output: {output}")
    print("=" * 60)

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))
        print("✓ OpenAI client initialized")
    except ImportError:
        print("✗ Error: openai package not installed")
        print("  Run: uv pip install openai")
        return None
    except Exception as exc:
        print(f"✗ Error initializing OpenAI client: {exc}")
        print("  Make sure OPENAI_API_KEY is set")
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
    
    print(f"→ Will query {len(puzzles_to_query)} puzzles")
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

            if not image_paths and not 'text' in prompt_file:
                raise ValueError("No images found for this puzzle")

            prompt_content = build_prompt_content(processed_prompt, image_paths)

            if openai_config is not None and reasoning_effort is not None:
                if 'reasoning' in openai_config and 'effort' in openai_config['reasoning']:
                    if openai_config['reasoning']['effort'] != reasoning_effort:
                        print(f'WARNING: {model} reasoning effort mismatch: {openai_config["reasoning"]["effort"]} != {reasoning_effort}. Using {reasoning_effort}')
                        openai_config['reasoning']['effort'] = reasoning_effort

            if tool_use is True:
                tools = [
                    {
                        "type": "code_interpreter",
                        "container": {"type": "auto", "memory_limit": "1g"}
                    }
                ]
            else:
                tools = None
                        
            effective_config = openai_config or {
                "model": model,
                "reasoning": {"effort": reasoning_effort},
                "tools": tools
            }
            print(f'Querying {model} with {effective_config}')

            response_text, api_response = query_openai(
                prompt_content, model, client, effective_config
            )
            output_parsed = extract_json_from_text(response_text)

            new_responses[str(puzzle_dir)] = {
                "puzzle_id": puzzle_id,
                "puzzle_dir": str(puzzle_dir),
                "prompt": prompt_content,
                "openai_config": effective_config,
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
                "openai_config": None,
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
        print(f"   Total output tokens: {token_stats['total_output_tokens']:,}")
        print(f"   Avg output tokens/sample: {token_stats['avg_output_tokens']:.1f}")
        print(f"   Total reasoning tokens: {token_stats['total_reasoning_tokens']:,}")
        print(f"   Avg reasoning tokens/sample: {token_stats['avg_reasoning_tokens']:.1f}")
        print(f"   Valid responses: {token_stats['num_valid_responses']}")
        print(f"   Cost: ~${token_stats['total_cost']:.4f} USD")
        print(f"   Cost: ~${token_stats['avg_cost']:.4f} USD per sample")

    print("=" * 60)
    return token_stats


def main() -> None:
    raise SystemExit(
        "query_openai_model.py no longer provides a CLI entry point. "
        "Use query_model.py instead."
    )


if __name__ == "__main__":
    main()

