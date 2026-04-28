"""
Utilities to query Google Gemini models on benchmark datasets and save responses.
Each dataset folder can then evaluate the responses independently.
"""

import json
import mimetypes
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tqdm import tqdm

from google import genai
from google.genai import types

# Add parent directory to path for imports when run directly

from utils import (
    load_prompt,
    process_prompt_with_images,
    extract_json_from_text,
    save_responses,
    load_dataset_samples,
    sanitize_for_json,
    get_puzzles_to_query,
    print_retry_stats,
    response_has_error,
    encode_image_base64,
)


def log(msg: str, level: str = "INFO") -> None:
    """Print a timestamped log message."""
    timestamp = time.strftime("%H:%M:%S")
    print(f"[{timestamp}] [{level}] {msg}")

# Pricing for Gemini models (per token)
# Text output tokens
COST_PER_TEXT_OUTPUT_TOKEN = {
    'gemini-2.5-pro': 15 / 1_000_000,
    'gemini-2.5-flash-image': 2.5 / 1_000_000,
    'gemini-3-pro-preview': 12 / 1_000_000,
    'gemini-3-pro-image-preview': 12 / 1_000_000,
}

# Thinking/reasoning tokens (same as text output for these models)
COST_PER_THINKING_TOKEN = {
    'gemini-2.5-pro': 15 / 1_000_000,
    'gemini-2.5-flash-image': 2.5 / 1_000_000,
    'gemini-3-pro-preview': 12 / 1_000_000,
    'gemini-3-pro-image-preview': 12 / 1_000_000,
}

# Image output: $0.039 per image (or ~$30 per 1M tokens at ~1300 tokens/image)
COST_PER_IMAGE = {
   'gemini-2.5-flash-image': 0.039,
    'gemini-3-pro-image-preview': 0.139,
}

# Video output: Cost per video (pricing TBD - check current Veo pricing)
COST_PER_VIDEO = {
    'veo-3.1-generate-preview': 3.2,
    'veo-3.1-fast-generate-preview': 1.2,
}

def is_veo_model(model: str) -> bool:
    """Check if the model is a Veo video generation model."""
    return model.startswith("veo-")


def build_prompt_content(
    prompt: str, images: List[Path]
) -> Tuple[List[types.Part], List[Dict[str, Any]]]:
    """
    Build Gemini API content format with interleaved text and images.
    Matches the format from Gemini/cached_responses.
    
    Returns:
        (api_parts, serialized_prompt_parts)
    """
    content_parts: List[types.Part] = []
    serialized_prompt: List[Dict[str, Any]] = []
    parts = prompt.split('[IMAGE_')
    
    # Add initial text
    if parts[0]:
        text_value = parts[0]
        content_parts.append(types.Part(text=text_value))
        serialized_prompt.append({
            "type": "input_text",
            "text": text_value,
        })
    
    # Add images and remaining text
    for i, part in enumerate(parts[1:]):
        if i < len(images):
            with open(images[i], 'rb') as f:
                image_bytes = f.read()
            mime_type = mimetypes.guess_type(images[i].name)[0] or 'image/jpeg'
            content_parts.append(
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=mime_type,
                )
            )
            serialized_prompt.append({
                "type": "input_image",
                "path": str(images[i]),
                "mime_type": mime_type,
            })
        
        # Add text after placeholder
        remaining = part[part.find(']') + 1:] if ']' in part else part
        if remaining:
            content_parts.append(types.Part(text=remaining))
            serialized_prompt.append({
                "type": "input_text",
                "text": remaining,
            })
    
    return content_parts, serialized_prompt


def extract_text_from_prompt_parts(prompt_parts: List[types.Part]) -> str:
    """Extract text content from prompt parts, combining all text segments."""
    text_parts = []
    for part in prompt_parts:
        if hasattr(part, 'text') and part.text:
            text_parts.append(part.text)
    return " ".join(text_parts)


def get_initial_frame_from_prompt_parts(prompt_parts: List[types.Part], image_paths: List[Path]) -> Optional[Path]:
    """
    Extract the first image path from prompt parts to use as initial frame for Veo.
    Returns the Path to the image file, which can be used to create an Image object.
    """
    # Find the first image part and return its corresponding path
    image_idx = 0
    for part in prompt_parts:
        # Check if this is an image part
        is_image = False
        if hasattr(part, 'inline_data') and part.inline_data is not None:
            is_image = True
        elif hasattr(part, 'mime_type') and part.mime_type and part.mime_type.startswith('image/'):
            is_image = True
        elif hasattr(part, 'file_data') and part.file_data:
            if hasattr(part.file_data, 'mime_type') and part.file_data.mime_type.startswith('image/'):
                is_image = True
        
        if is_image:
            # Return the corresponding image path
            if image_idx < len(image_paths):
                return image_paths[image_idx]
            image_idx += 1
    
    return None


def create_veo_image_from_path(image_path: Path, client=None):
    """
    Create an Image object for Veo API from an image file path.
    Uses Part.from_bytes().as_image() to convert the image to the correct format.
    """
    log(f"Creating Image object from: {image_path}")
    mime_type = mimetypes.guess_type(str(image_path))[0] or 'image/jpeg'
    
    # Read image bytes
    with open(image_path, 'rb') as f:
        image_bytes = f.read()
    
    # Create Part from bytes, then convert to Image using as_image()
    part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    image = part.as_image()
    
    log(f"Created Image object using Part.from_bytes().as_image()")
    return image


def query_veo(
    prompt: str,
    model: str,
    client,
    output_dir: Path,
    initial_frame_path: Optional[Path] = None,
    **veo_config
) -> tuple:
    """
    Query Veo video generation model.
    
    Args:
        prompt: Text prompt for video generation
        model: Veo model name
        client: Gemini client
        output_dir: Directory to save generated video
        initial_frame_path: Optional path to initial frame image file
        **veo_config: Additional Veo config options (aspect_ratio, resolution, negative_prompt, etc.)
    
    Returns:
        (response_text, api_response_dict)
        For Veo, response_text is a JSON string with video metadata, and api_response_dict contains the operation response.
    """
    log(f"Preparing Veo API request for model: {model}")
    
    # Build GenerateVideosConfig
    config_kwargs = {}
    if veo_config:
        config_kwargs = {k: v for k, v in veo_config.items() if v is not None}
    
    config = types.GenerateVideosConfig(**config_kwargs) if config_kwargs else None
    
    # Build API kwargs
    api_kwargs = {
        "model": model,
        "prompt": prompt,
    }
    
    # Add initial frame (start frame) if provided
    # According to Veo API: image parameter is passed directly to generate_videos(), not in config
    # Upload the file first and use the file object
    if initial_frame_path is not None:
        log(f"Creating Image object from {initial_frame_path}...")
        try:
            veo_image = create_veo_image_from_path(initial_frame_path, client)
            log("Using initial frame image as start frame for video generation")
            api_kwargs["image"] = veo_image
        except Exception as e:
            log(f"Warning: Failed to create Image from path: {e}. Proceeding without initial frame.", "WARN")
    else:
        log("No initial frame image provided. Proceeding with text-to-video generation.")
    
    # Add config if we have any config options (last_frame, aspect_ratio, resolution, etc.)
    if config:
        api_kwargs["config"] = config
    
    log(f"Sending request to Veo API (prompt: {len(prompt)} chars)...")
    start_time = time.time()
    
    # Call API - this returns an operation
    operation = client.models.generate_videos(**api_kwargs)
    
    elapsed = time.time() - start_time
    log(f"Operation created in {elapsed:.2f}s, operation name: {getattr(operation, 'name', 'unknown')}")
    
    # Poll the operation until complete
    log("Polling operation status...")
    poll_count = 0
    max_polls = 60  # 60 * 20s = 20 minutes max (docs say max 6 minutes, but allow buffer)
    
    while not operation.done:
        poll_count += 1
        if poll_count > max_polls:
            raise TimeoutError(f"Operation did not complete within {max_polls * 20} seconds")
        
        log(f"Waiting for video generation (poll {poll_count})...")
        time.sleep(10)  # Docs recommend 10 second intervals
        operation = client.operations.get(operation)
        
        if hasattr(operation, 'error') and operation.error:
            raise RuntimeError(f"Operation failed: {operation.error}")
    
    total_elapsed = time.time() - start_time
    log(f"Video generation completed in {total_elapsed:.2f}s")
    
    # Extract the generated video
    if not hasattr(operation, 'response') or not operation.response:
        raise ValueError("Operation completed but no response found")
    
    if not hasattr(operation.response, 'generated_videos') or not operation.response.generated_videos:
        raise ValueError("Operation completed but no generated videos found")
    
    generated_video = operation.response.generated_videos[0]
    
    # Download and save the video
    log("Downloading generated video...")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    video_path = output_dir / "generated_video.mp4"
    
    try:
        client.files.download(file=generated_video.video)
        generated_video.video.save(str(video_path))
        log(f"✓ Video saved to {video_path}")
    except Exception as e:
        log(f"Error downloading video: {e}", "ERROR")
        raise
    
    # Create a text response with video metadata
    response_text = json.dumps({
        "video_path": str(video_path),
        "video_uri": getattr(generated_video.video, 'uri', None),
        "operation_name": getattr(operation, 'name', None),
        "generation_time_seconds": total_elapsed,
    }, indent=2)
    
    # Serialize the API response
    log("Serializing API response...")
    try:
        api_response_dict = operation.model_dump()
        api_response_dict = sanitize_for_json(api_response_dict)
        # Add video path to response for easier access
        if "response" in api_response_dict and "generatedVideos" in api_response_dict["response"]:
            if api_response_dict["response"]["generatedVideos"]:
                api_response_dict["response"]["generatedVideos"][0]["saved_video_path"] = str(video_path)
        log("Serialization complete")
    except Exception as e:
        log(f"Warning: Failed to serialize API response: {e}", "WARN")
        api_response_dict = {
            "serialization_error": str(e),
            "video_path": str(video_path),
            "operation_name": getattr(operation, 'name', None),
        }
    
    return response_text, api_response_dict


def query_gemini(
    prompt_parts: List[types.Part], model: str, client, output_dir: Path, reasoning_effort: str = "high"
) -> tuple:
    """
    Query Gemini model with prompt content.
    Saves any inline image data from the response to separate files.
    
    Args:
        prompt_parts: List of content parts (text and images)
        model: Model name
        client: Gemini client
        output_dir: Directory to save generated images
        reasoning_effort: Thinking level for reasoning models ("low", "high")
    """
    log(f"Preparing API request for model: {model}")

    if model == "gemini-2.5-pro" or model == "gemini-3-pro-preview":
        config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(
                include_thoughts=True,
                thinking_level=reasoning_effort
            )
        )
        log(f"Using thinking config (include_thoughts=True, thinking_level={reasoning_effort})")
    else:
        config = None

    # Build API kwargs
    api_kwargs = {
        "model": model,
        "contents": [
            types.Content(
                role="user",
                parts=prompt_parts,
            )
        ],
        "config": config
    }

    log(f"Sending request to Gemini API ({len(prompt_parts)} parts)...")
    start_time = time.time()
    
    # Call API
    response = client.models.generate_content(**api_kwargs)
    
    elapsed = time.time() - start_time
    log(f"API response received in {elapsed:.2f}s")
    
    # Validate response - empty responses need to be re-queried
    if response is None:
        raise ValueError("API returned None response - possible rate limit or service error")
    
    # Extract text response
    log("Extracting text from response...")
    response_text = response.text
    
    if response_text is None:
        raise ValueError("API returned None text - model may have refused to respond or hit content filter")
    
    log(f"Response text length: {len(response_text)} chars")
    
    # Ensure output directory exists
    output_dir = Path(output_dir)
    
    # First, save all inline images from the response
    # We'll track the saved paths to update the serialized response
    saved_image_paths = []
    image_idx = 0
    
    # Iterate through response candidates to find and save images
    log("Checking for inline images in response...")
    if hasattr(response, 'candidates') and response.candidates:
        for candidate in response.candidates:
            if hasattr(candidate, 'content') and candidate.content:
                if hasattr(candidate.content, 'parts') and candidate.content.parts:
                    for part in candidate.content.parts:
                        if hasattr(part, 'inline_data') and part.inline_data is not None:
                            try:
                                # Save the image
                                image = part.as_image()
                                image_path = output_dir / f"generated_image_{image_idx}.png"
                                output_dir.mkdir(parents=True, exist_ok=True)
                                image.save(str(image_path))
                                saved_image_paths.append({
                                    'index': image_idx,
                                    'path': str(image_path),
                                    'mime_type': getattr(part.inline_data, 'mime_type', 'image/png')
                                })
                                image_idx += 1
                            except Exception as e:
                                # If image saving fails, log but continue
                                print(f"Warning: Failed to save inline image {image_idx}: {e}")
                                saved_image_paths.append({
                                    'index': image_idx,
                                    'path': None,
                                    'error': str(e)
                                })
                                image_idx += 1
    
    # Now serialize the full API response to preserve all structure
    log("Serializing API response...")
    serialize_start = time.time()
    try:
        api_response_dict = response.model_dump()
        # Sanitize to remove any bytes objects that can't be JSON serialized
        api_response_dict = sanitize_for_json(api_response_dict)
        log(f"Serialization complete in {time.time() - serialize_start:.2f}s")
    except Exception as e:
        log(f"Warning: Failed to serialize API response: {e}", "WARN")
        api_response_dict = {"serialization_error": str(e)}
    
    # Replace inline_data in the serialized response with file path references
    # Walk through the dict structure and replace inline_data with saved paths
    # We iterate in the same order as when we saved images to ensure correct matching
    image_idx = 0
    if "candidates" in api_response_dict:
        for candidate in api_response_dict.get("candidates", []):
            if "content" in candidate and "parts" in candidate["content"]:
                for part in candidate["content"]["parts"]:
                    # Check if this part has inline_data (could be a dict with data or just present)
                    inline_data = part.get("inline_data")
                    if inline_data is not None:
                        # Check if it's a dict with actual data (not just metadata)
                        has_image_data = False
                        if isinstance(inline_data, dict):
                            # Check if it has 'data' field (the actual image bytes)
                            has_image_data = "data" in inline_data and inline_data.get("data") is not None
                        elif inline_data:  # Truthy non-dict value
                            has_image_data = True
                        
                        if has_image_data and image_idx < len(saved_image_paths):
                            saved_info = saved_image_paths[image_idx]
                            if saved_info.get("path"):
                                # Replace inline_data with file path reference
                                # Preserve the original structure but replace inline_data
                                original_inline_data = inline_data
                                part["saved_image_path"] = saved_info["path"]
                                part["saved_image_mime_type"] = saved_info["mime_type"]
                                # Keep a reference to original inline_data metadata (but not the actual data)
                                if isinstance(original_inline_data, dict):
                                    part["original_inline_data_metadata"] = {
                                        k: v for k, v in original_inline_data.items() 
                                        if k != "data"  # Don't store the actual image data
                                    }
                                # Remove the actual inline_data to save space
                                part["inline_data"] = None
                            image_idx += 1
                        elif has_image_data:
                            # We have inline_data but no saved path (save failed)
                            image_idx += 1
    
    return response_text, api_response_dict


def count_generated_images(api_response: dict) -> int:
    """Count the number of generated images in a response."""
    image_count = 0
    candidates = api_response.get("candidates", [])
    for candidate in candidates:
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        for part in parts:
            # Check for saved images (inline_data that was saved to disk)
            if part.get("saved_image_path"):
                image_count += 1
            # Check for inline_data that wasn't saved
            elif part.get("inline_data") is not None:
                inline_data = part.get("inline_data")
                if isinstance(inline_data, dict) and inline_data.get("data"):
                    image_count += 1
    return image_count


def count_generated_videos(api_response: dict) -> int:
    """Count the number of generated videos in a response."""
    # For Veo responses, check the response.generatedVideos field
    if "response" in api_response:
        generated_videos = api_response["response"].get("generatedVideos", [])
        if generated_videos:
            return len(generated_videos)
    # Also check for saved_video_path as a fallback
    if "response" in api_response and "generatedVideos" in api_response["response"]:
        videos = api_response["response"]["generatedVideos"]
        if videos and any(v.get("saved_video_path") for v in videos):
            return 1
    return 0


def compute_token_stats(responses, model: str):
    """Compute token usage statistics from responses.
    
    Calculates costs separately for:
    - Text output tokens (model-dependent pricing)
    - Thinking/reasoning tokens (model-dependent pricing)
    - Generated images ($0.039 per image)
    - Generated videos (model-dependent pricing)
    """
    total_output_tokens = 0
    total_reasoning_tokens = 0
    total_images = 0
    total_videos = 0
    num_valid_responses = 0

    for resp in responses:
        if response_has_error(resp):
            continue

        api_response = resp.get("api_response") or {}
        
        # For Veo models, check for videos instead of usage_metadata
        if is_veo_model(model):
            # Veo responses may not have usage_metadata in the same format
            videos = count_generated_videos(api_response)
            if videos > 0:
                num_valid_responses += 1
                total_videos += videos
            continue
        
        # For regular Gemini models, check usage_metadata
        usage = api_response.get("usage_metadata") or {}
        if not usage:
            continue

        num_valid_responses += 1
        total_output_tokens += usage.get("candidates_token_count") or 0
        total_reasoning_tokens += usage.get("thoughts_token_count") or 0
        total_images += count_generated_images(api_response)

    if num_valid_responses == 0:
        return None

    # Calculate costs separately
    text_cost = 0.0
    thinking_cost = 0.0
    image_cost = 0.0
    video_cost = 0.0
    
    if is_veo_model(model):
        # For Veo models, calculate video cost
        if model in COST_PER_VIDEO:
            video_cost = total_videos * COST_PER_VIDEO[model]
        else:
            print(f"Warning: No cost per video found for model: {model}")
            video_cost = 0.0
    else:
        # For regular models, calculate text/image costs
        if model in COST_PER_IMAGE:
            image_cost = total_images * COST_PER_IMAGE[model]
        else:
            print(f"Warning: No cost per image found for model: {model}")
            image_cost = 0.0

        if model in COST_PER_TEXT_OUTPUT_TOKEN:
            text_cost = total_output_tokens * COST_PER_TEXT_OUTPUT_TOKEN[model]
        else:
            print(f"Warning: No cost per text output token found for model: {model}")
            text_cost = 0.0
        if model in COST_PER_THINKING_TOKEN:
            thinking_cost = total_reasoning_tokens * COST_PER_THINKING_TOKEN[model]
        else:
            print(f"Warning: No cost per thinking token found for model: {model}")
            thinking_cost = 0.0
    
    total_cost = text_cost + thinking_cost + image_cost + video_cost
    avg_cost = total_cost / num_valid_responses if num_valid_responses > 0 else 0.0

    result = {
        "total_output_tokens": total_output_tokens,
        "avg_output_tokens": total_output_tokens / num_valid_responses if num_valid_responses > 0 else 0.0,
        "total_reasoning_tokens": total_reasoning_tokens,
        "avg_reasoning_tokens": total_reasoning_tokens / num_valid_responses if num_valid_responses > 0 else 0.0,
        "total_images": total_images,
        "total_videos": total_videos,
        "num_valid_responses": num_valid_responses,
        "text_cost": text_cost,
        "thinking_cost": thinking_cost,
        "image_cost": image_cost,
        "video_cost": video_cost,
        "total_cost": total_cost,
        "avg_cost": avg_cost,
    }
    
    return result


def _merge_responses(
    all_puzzles: List[Path],
    successful_responses: Dict[str, Dict],
    new_responses: Dict[str, Dict],
) -> List[Dict[str, Any]]:
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
    prompt_file: str = "simple.txt",
    reasoning_effort: str = "high",  # Thinking level for reasoning models ("low", "medium", "high")
    max_no_image_attempts: int = 6,  # Max retries when generate_images prompt returns no images
    **kwargs
) -> Optional[Dict[str, Any]]:
    print("=" * 60)
    print("Visual Thinking Benchmarks - Model Query")
    print("=" * 60)
    print(f"Task: {task}")
    print(f"Dataset: {dataset}")
    print(f"Model: {model}")
    print(f"Output: {output}")
    print("=" * 60)

    log("Initializing Gemini client...")
    client = genai.Client(api_key=api_key or os.environ.get("GEMINI_API_KEY"))
    log("✓ Gemini client initialized")

    try:
        log(f"Loading prompt template: {task}/{prompt_file}")
        prompt_template = load_prompt(task, prompt_file)
        log(f"✓ Loaded prompt template ({len(prompt_template)} chars)")
    except FileNotFoundError as e:
        log(f"✗ {e}", "ERROR")
        return None

    dataset_path = Path(dataset)
    output_path = Path(output)
    # When using a generate_images prompt, enforce that responses contain images
    require_images = "generate_images" in prompt_file
    no_image_output_path = output_path.parent / "responses_no_images.json"
    no_image_attempts_all: List[Dict[str, Any]] = []
    log(f"Discovering puzzles in {dataset_path}...")
    all_puzzles = load_dataset_samples(dataset_path)

    if not all_puzzles:
        log(f"✗ No puzzles found in {dataset_path}", "ERROR")
        return None

    if num_samples:
        all_puzzles = all_puzzles[:num_samples]

    log(f"✓ Found {len(all_puzzles)} puzzles in dataset")
    
    # Check for existing responses and determine which puzzles need querying
    puzzles_to_query, successful_responses, stats = get_puzzles_to_query(
        all_puzzles, output_path, require_images=require_images
    )
    print_retry_stats(stats, output_path)
    
    if not puzzles_to_query:
        log("✅ All samples already successfully queried. Nothing to do.")
        # Return existing stats
        existing_responses = list(successful_responses.values())
        token_stats = compute_token_stats(existing_responses, model)
        return token_stats
    
    log(f"→ Will query {len(puzzles_to_query)} puzzles")
    print()

    # Track new responses from this run
    new_responses: Dict[str, Dict[str, Any]] = {}
    errors = 0

    # Track the overall sample index across all puzzles (for generated_images folder structure)
    # We need to know the position in all_puzzles, not just puzzles_to_query
    puzzle_to_overall_idx = {str(p): i + 1 for i, p in enumerate(all_puzzles)}
    
    for idx, puzzle_dir in enumerate(tqdm(puzzles_to_query, desc="Querying"), 1):
        log(f"--- Processing puzzle {idx}/{len(puzzles_to_query)}: {puzzle_dir.name} ---")
        
        metadata_file = puzzle_dir / "metadata.json"
        if not metadata_file.exists():
            log(f"No metadata in {puzzle_dir.name}, skipping", "WARN")
            continue

        log("Loading metadata...")
        with open(metadata_file, "r", encoding="utf-8") as f:
            metadata = json.load(f)

        puzzle_id = metadata.get(
            "puzzle_id",
            metadata.get("instance_id", metadata.get("sample_id", "unknown")),
        )
        log(f"Puzzle ID: {puzzle_id}")

        try:
            log("Processing prompt template with images...")
            processed_prompt, image_paths = process_prompt_with_images(
                prompt_template, puzzle_dir
            )
            log(f"Found {len(image_paths)} image(s)")

            if not image_paths:
                raise ValueError("No images found for this puzzle")

            # Save generated media into generated_images/1, generated_images/2, etc.
            # Use the overall sample index (1-based) for folder naming
            overall_sample_idx = puzzle_to_overall_idx.get(str(puzzle_dir), idx)
            output_parent_dir = output_path.parent
            output_dir = output_parent_dir / "generated_images" / str(overall_sample_idx)

            # Check if this is a Veo model
            if is_veo_model(model):
                log("Detected Veo model - using video generation API")
                
                # For Veo, extract text prompt and initial frame
                log("Building prompt content...")
                prompt_parts, prompt_serialized = build_prompt_content(
                    processed_prompt, image_paths
                )
                log(f"Built {len(prompt_parts)} prompt parts")
                
                # Extract text from prompt parts
                prompt_text = extract_text_from_prompt_parts(prompt_parts)
                log(f"Extracted prompt text ({len(prompt_text)} chars)")
                
                # Extract first image path as initial frame if available
                initial_frame_path = get_initial_frame_from_prompt_parts(prompt_parts, image_paths)
                if initial_frame_path:
                    log(f"Using first input image as initial frame: {initial_frame_path}")
                else:
                    log("No initial frame image found - using text-to-video only")
                
                # Query Veo API
                # Extract any Veo-specific config from kwargs (aspect_ratio, resolution, negative_prompt, etc.)
                veo_config = {}
                if 'aspect_ratio' in kwargs:
                    veo_config['aspect_ratio'] = kwargs['aspect_ratio']
                if 'resolution' in kwargs:
                    veo_config['resolution'] = kwargs['resolution']
                if 'negative_prompt' in kwargs:
                    veo_config['negative_prompt'] = kwargs['negative_prompt']
                
                response_text, api_response = query_veo(
                    prompt_text, model, client, output_dir, initial_frame_path, **veo_config
                )
                
                log("Parsing response JSON...")
                output_parsed = extract_json_from_text(response_text)
                log(f"Parsed response: {output_parsed}")
            else:
                # Gemini image/text models
                log("Building prompt content...")
                prompt_parts, prompt_serialized = build_prompt_content(
                    processed_prompt, image_paths
                )
                log(f"Built {len(prompt_parts)} prompt parts")

                attempt = 0
                last_response_text = None
                last_api_response = None
                last_output_parsed = None

                while True:
                    attempt += 1
                    log(f"Sending Gemini request (attempt {attempt}/{max_no_image_attempts})...")
                    try:
                        response_text, api_response = query_gemini(
                            prompt_parts, model, client, output_dir, reasoning_effort
                        )
                    except Exception as e:
                        # Handle transient API errors (including "API returned None text")
                        log(
                            f"Gemini request failed on attempt {attempt}/{max_no_image_attempts}: {e}",
                            "WARN",
                        )
                        if attempt >= max_no_image_attempts:
                            log(
                                f"Max attempts ({max_no_image_attempts}) reached; "
                                "marking puzzle as failed due to repeated API errors.",
                                "ERROR",
                            )
                            last_response_text = None
                            last_api_response = None
                            last_output_parsed = None
                            error_msg = f"api_error_after_max_attempts: {e}"
                            errors += 1
                            break
                        # Retry on next loop iteration
                        continue
                
                    log("Parsing response JSON...")
                    output_parsed = extract_json_from_text(response_text)
                    log(f"Parsed response: {output_parsed}")

                    last_response_text = response_text
                    last_api_response = api_response
                    last_output_parsed = output_parsed

                    # If we are not in a generate_images setting, accept the first answer
                    if not require_images:
                        error_msg = None
                        break

                    # For generate_images prompts, require that the model actually returns images
                    num_generated_images = count_generated_images(api_response)
                    if num_generated_images > 0:
                        log(f"✓ Model generated {num_generated_images} image(s); accepting response")
                        error_msg = None
                        break

                    # No images generated – record this attempt and potentially retry
                    log(
                        f"No images generated in response (attempt {attempt}/{max_no_image_attempts}); "
                        "saving to responses_no_images.json",
                        "WARN",
                    )
                    no_image_attempt = {
                "puzzle_id": puzzle_id,
                "puzzle_dir": str(puzzle_dir),
                "prompt": prompt_serialized,
                "output_text": response_text,
                "output_parsed": output_parsed,
                "api_response": api_response,
                "images_used": [str(p) for p in image_paths],
                "metadata": metadata,
                        "error": "no_images_generated",
                        "attempt": attempt,
                    }
                    no_image_attempts_all.append(no_image_attempt)

                    if attempt >= max_no_image_attempts:
                        log(
                            f"Max no-image attempts ({max_no_image_attempts}) reached; "
                            "marking puzzle as failed due to missing images.",
                            "ERROR",
                        )
                        error_msg = "no_images_generated_after_max_attempts"
                        errors += 1
                        break

                    log("Retrying due to missing images...")

                # Use last response (successful or final failed) as canonical for this puzzle
                log(f"✓ Puzzle {puzzle_id} completed with "
                    f"{'images' if error_msg is None and (not require_images or count_generated_images(last_api_response) > 0) else 'no images'}")

                new_responses[str(puzzle_dir)] = {
                    "puzzle_id": puzzle_id,
                    "puzzle_dir": str(puzzle_dir),
                    "prompt": prompt_serialized,
                    "output_text": last_response_text,
                    "output_parsed": last_output_parsed,
                    "api_response": last_api_response,
                    "images_used": [str(p) for p in image_paths],
                    "metadata": metadata,
                    "error": error_msg,
            }

        except Exception as e:
            errors += 1
            log(f"✗ Error on puzzle {puzzle_id}: {e}", "ERROR")
            import traceback
            log(f"Traceback: {traceback.format_exc()}", "ERROR")

            new_responses[str(puzzle_dir)] = {
                "puzzle_id": puzzle_id,
                "puzzle_dir": str(puzzle_dir),
                "prompt": None,
                "output_text": None,
                "output_parsed": None,
                "api_response": None,
                "images_used": [],
                "metadata": metadata,
                "error": str(e),
            }

        # Intermediate save: merge new responses with existing successful ones
        if cache_interval and idx % cache_interval == 0:
            log(f"Saving intermediate cache ({idx}/{len(puzzles_to_query)} new queries)...")
            try:
                merged_responses = _merge_responses(all_puzzles, successful_responses, new_responses)
                token_stats = compute_token_stats(merged_responses, model)
                save_responses(merged_responses, output, task, model, dataset_path, token_stats)
                log(f"💾 Cache saved to {output}")
                # Also save intermediate no-image attempts if any
                if no_image_attempts_all:
                    log(f"Saving {len(no_image_attempts_all)} no-image responses to {no_image_output_path}...")
                    save_responses(
                        no_image_attempts_all,
                        no_image_output_path,
                        task,
                        model,
                        dataset_path,
                        {"note": "Responses where generate_images prompt produced no images"},
                    )
            except Exception as e:
                log(f"Warning: Failed to save cache: {e}", "WARN")
                # Continue processing - don't crash on save errors

    # Final merge: combine existing successful responses with new responses
    responses = _merge_responses(all_puzzles, successful_responses, new_responses)
    
    log("Computing final token statistics...")
    token_stats = compute_token_stats(responses, model)
    log("Saving final responses...")
    try:
        save_responses(responses, output, task, model, dataset_path, token_stats)
        log("✓ Final save complete")
    except Exception as e:
        log(f"Error saving final responses: {e}", "ERROR")
        # Try one more time with aggressive sanitization
        try:
            log("Retrying with sanitized responses...")
            sanitized_responses = sanitize_for_json(responses)
            save_responses(sanitized_responses, output, task, model, dataset_path, token_stats)
            log("✓ Saved with sanitized data")
        except Exception as e2:
            log(f"Failed to save even after sanitization: {e2}", "ERROR")

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
        print(
            f"   Total reasoning tokens: {token_stats['total_reasoning_tokens']:,}"
        )
        print(
            f"   Avg reasoning tokens/sample: {token_stats['avg_reasoning_tokens']:.1f}"
        )
        if token_stats.get('total_images', 0) > 0:
            print(f"   Total images generated: {token_stats['total_images']}")
        if token_stats.get('total_videos', 0) > 0:
            print(f"   Total videos generated: {token_stats['total_videos']}")
        print(f"   Valid responses: {token_stats['num_valid_responses']}")
        print()
        print("💰 Cost Breakdown:")
        if token_stats.get('text_cost', 0) > 0:
            print(f"   Text output:  ${token_stats.get('text_cost', 0):.4f}")
        if token_stats.get('thinking_cost', 0) > 0:
            print(f"   Thinking:     ${token_stats.get('thinking_cost', 0):.4f}")
        if token_stats.get('image_cost', 0) > 0:
            print(f"   Images:       ${token_stats.get('image_cost', 0):.4f} ({token_stats.get('total_images', 0)} × $0.039)")
        if token_stats.get('video_cost', 0) > 0:
            print(f"   Videos:       ${token_stats.get('video_cost', 0):.4f} ({token_stats.get('total_videos', 0)} videos)")
        print(f"   Total:        ${token_stats['total_cost']:.4f} USD")
        print(f"   Per sample:   ${token_stats['avg_cost']:.4f} USD")

    print("=" * 60)
    return token_stats


def main() -> None:
    raise SystemExit(
        "query_google_model.py no longer provides a CLI entry point. "
        "Use query_model.py instead."
    )


if __name__ == "__main__":
    main()

