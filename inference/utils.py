"""
Shared utilities for benchmark evaluation.
"""

from pathlib import Path
from typing import List, Dict, Any
import json
import re
import base64


class SafeJSONEncoder(json.JSONEncoder):
    """JSON encoder that handles non-serializable types gracefully."""
    
    def default(self, obj):
        if isinstance(obj, bytes):
            # Convert bytes to base64 string with marker
            return f"<bytes:{len(obj)}>"
        if isinstance(obj, (set, frozenset)):
            return list(obj)
        if hasattr(obj, '__dict__'):
            return str(obj)
        try:
            return super().default(obj)
        except TypeError:
            return f"<non-serializable:{type(obj).__name__}>"


def sanitize_for_json(obj: Any, max_depth: int = 50) -> Any:
    """
    Recursively sanitize an object for JSON serialization.
    Converts bytes to placeholders, handles circular references, etc.
    """
    if max_depth <= 0:
        return "<max-depth-exceeded>"
    
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    
    if isinstance(obj, bytes):
        # Replace bytes with a placeholder indicating size
        return f"<bytes:{len(obj)}>"
    
    if isinstance(obj, (list, tuple)):
        return [sanitize_for_json(item, max_depth - 1) for item in obj]
    
    if isinstance(obj, dict):
        return {
            str(k): sanitize_for_json(v, max_depth - 1) 
            for k, v in obj.items()
        }
    
    if isinstance(obj, (set, frozenset)):
        return [sanitize_for_json(item, max_depth - 1) for item in obj]
    
    # For other objects, try to convert to string
    try:
        return str(obj)
    except Exception:
        return f"<non-serializable:{type(obj).__name__}>"


def _is_no_images_timeout_error(error_str: Any) -> bool:
    """
    True if the error is due to timeout/no images generated (do not count as model error).
    """
    if error_str is None or not isinstance(error_str, str):
        return False
    s = error_str.strip()
    if s in ("no_images_generated", "no_images_generated_after_max_attempts"):
        return True
    if s.startswith("api_error_after_max_attempts:"):
        # e.g. "api_error_after_max_attempts: API returned None text - ..."
        rest = s[len("api_error_after_max_attempts:"):].lower()
        if "none text" in rest or "no images" in rest or "refused" in rest:
            return True
    return False


def response_is_no_images_timeout(resp: Dict[str, Any]) -> bool:
    """
    True if this response is a no-images/timeout outcome (do not requery).
    """
    return _is_no_images_timeout_error(resp.get("error"))


def response_has_error(resp: Dict[str, Any]) -> bool:
    """
    Check if a response has an error.
    
    Errors can be at:
    - Top level: resp["error"]
    - Nested in API response choices: resp["api_response"]["choices"][X]["error"]
      (OpenRouter/provider errors like network issues, context length exceeded)
    
    Timeout / no-images cases (no_images_generated, api_error_after_max_attempts with
    None text or no images) are not counted as errors.
    
    Args:
        resp: A response dict from the responses list
        
    Returns:
        True if the response has any error, False otherwise
    """
    # Check top-level error
    top_error = resp.get("error")
    if top_error is not None:
        if _is_no_images_timeout_error(top_error):
            return False
        return True
    
    # Check for errors in api_response.choices (OpenRouter/provider errors)
    api_response = resp.get("api_response", {})
    if api_response:
        choices = api_response.get("choices", [])
        for choice in choices:
            choice_error = choice.get("error")
            if choice_error is not None:
                if _is_no_images_timeout_error(choice_error):
                    continue
                return True
    
    return False


def load_dataset_samples(dataset_path: Path):
    """Load all puzzle samples from dataset directory"""
    dataset_path = Path(dataset_path)
    
    # Try puzzle_* pattern (form-board, paper-fold, sliding-puzzle)
    puzzles = sorted(dataset_path.glob("puzzle_*"))
    
    if not puzzles:
        # Try instance_* pattern (rush-hour, hinge-folding)
        puzzles = sorted(dataset_path.glob("instance_*"))
    
    if not puzzles:
        # Try hf_* pattern (hinge-folding alternative)
        puzzles = sorted(dataset_path.glob("hf_*"))
    
    return puzzles

def process_prompt_with_images(prompt: str, puzzle_dir: Path) -> tuple:
    """
    Replace <image filename> tags with actual images for API.
    Replace <text filename> tags with contents of text files.
    Supports wildcard matching for filenames with prefixes.
    Special tag <images visual cot> scans for CoT/step images and appends them in order.
    
    Tags are processed in the order they appear in the prompt text, regardless of type.
    
    Returns:
        (processed_prompt, list_of_image_paths)
    """
    image_paths = []
    processed_prompt = prompt
    
    # Find all tags with their positions
    image_pattern = r'<image\s+([^>]+)>'
    cot_pattern = r'<images\s+visual\s+cot>'
    text_pattern = r'<text\s+([^>]+)>'
    
    # Find all matches with positions
    tags = []
    
    # Find regular image tags
    for match in re.finditer(image_pattern, prompt):
        tags.append({
            'type': 'image',
            'start': match.start(),
            'end': match.end(),
            'full_match': match.group(0),
            'filename': match.group(1).strip()
        })
    
    # Find visual cot tags
    for match in re.finditer(cot_pattern, prompt):
        tags.append({
            'type': 'cot',
            'start': match.start(),
            'end': match.end(),
            'full_match': match.group(0)
        })
    
    # Find text tags
    for match in re.finditer(text_pattern, prompt):
        tags.append({
            'type': 'text',
            'start': match.start(),
            'end': match.end(),
            'full_match': match.group(0),
            'filename': match.group(1).strip()
        })
    
    # Sort tags by their position in the prompt
    tags.sort(key=lambda x: x['start'])
    
    # Process tags in order, building replacements
    replacements = []  # List of (original_text, replacement_text, image_paths_to_add)
    
    for tag in tags:
        if tag['type'] == 'image':
            # Regular image tag
            try:
                image_path = find_image_file(puzzle_dir, tag['filename'])
                current_idx = len(image_paths)
                replacements.append({
                    'original': tag['full_match'],
                    'replacement': f'[IMAGE_{current_idx}]',
                    'images': [image_path]
                })
                image_paths.append(image_path)
            except FileNotFoundError as e:
                print(f"Warning: {e}")
                # Remove the tag but don't add any images
                replacements.append({
                    'original': tag['full_match'],
                    'replacement': '',
                    'images': []
                })
        
        elif tag['type'] == 'cot':
            # Visual CoT tag
            cot_images = find_visual_cot_images(puzzle_dir)
            
            if cot_images:
                # Create placeholders for each CoT image
                placeholders = []
                for img_path in cot_images:
                    current_idx = len(image_paths)
                    placeholders.append(f'[IMAGE_{current_idx}]')
                    image_paths.append(img_path)
                
                replacements.append({
                    'original': tag['full_match'],
                    'replacement': '\n'.join(placeholders),
                    'images': cot_images
                })
            else:
                # No CoT images found, just remove the tag
                print(f"Warning: No CoT images found in {puzzle_dir}")
                replacements.append({
                    'original': tag['full_match'],
                    'replacement': '',
                    'images': []
                })
        
        elif tag['type'] == 'text':
            # Text file tag - replace with file contents
            try:
                text_content = find_and_read_text_file(puzzle_dir, tag['filename'])
                replacements.append({
                    'original': tag['full_match'],
                    'replacement': text_content,
                    'images': []
                })
            except FileNotFoundError as e:
                print(f"Warning: {e}")
                # Remove the tag if file not found
                replacements.append({
                    'original': tag['full_match'],
                    'replacement': '',
                    'images': []
                })
    
    # Apply replacements (only replace first occurrence to handle duplicates correctly)
    for repl in replacements:
        processed_prompt = processed_prompt.replace(repl['original'], repl['replacement'], 1)
    
    return processed_prompt, image_paths


def find_visual_cot_images(puzzle_dir: Path) -> list:
    """
    Find visual chain-of-thought images in the puzzle directory.
    Looks for patterns like:
    - cot_00.png, cot_01.png, ...
    - step_00.png, step_01.png, ...
    - 1_cot_00.png, 2_cot_00.png, ... (with numeric prefixes)
    
    Returns them sorted by the numeric indices in their filenames.
    
    Returns:
        List of Path objects for CoT images, sorted by number
    """
    if not puzzle_dir.exists():
        return []
    
    # Collect all potential CoT/step images
    cot_images = []
    
    # Pattern 1: cot_XX.png
    cot_images.extend(list(puzzle_dir.glob('cot_*.png')))
    
    # Pattern 2: step_XX.png
    cot_images.extend(list(puzzle_dir.glob('step_*.png')))
    
    # Pattern 3: N_cot_XX.png (with numeric prefix)
    cot_images.extend(list(puzzle_dir.glob('*_cot_*.png')))
    
    # Pattern 4: N_step_XX.png (with numeric prefix)
    cot_images.extend(list(puzzle_dir.glob('*_step_*.png')))
    
    if not cot_images:
        return []
    
    # Sort by extracting all numbers from filename and using them as sort key
    def extract_numbers(path: Path) -> tuple:
        """Extract all numbers from filename for sorting."""
        import re
        numbers = re.findall(r'\d+', path.stem)
        # Convert to integers for proper numeric sorting
        return tuple(int(n) for n in numbers) if numbers else (0,)
    
    cot_images.sort(key=extract_numbers)
    
    return cot_images

def encode_image_base64(image_path: Path) -> str:
    """Encode image as base64 for OpenAI API"""
    with open(image_path, 'rb') as f:
        return base64.b64encode(f.read()).decode('utf-8')


def load_prompt(task_name: str, prompt_file: str = "simple.txt") -> str:
    """Load prompt template for a task"""
    prompt_path = (
        Path(__file__).parent.parent / task_name / "prompts" / prompt_file
    )
    
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt not found: {prompt_path}")
    
    with open(prompt_path, 'r') as f:
        return f.read()


def find_image_file(puzzle_dir: Path, filename_pattern: str) -> Path:
    """
    Find image file matching pattern, allowing for preceding characters.
    
    Args:
        puzzle_dir: Directory containing puzzle files
        filename_pattern: Filename or pattern (e.g., 'silhouette.png')
        
    Returns:
        Path to matching image file
        
    Example:
        Pattern 'silhouette.png' matches:
        - silhouette.png
        - 1_silhouette.png
        - puzzle_001_silhouette.png
        - any_prefix_silhouette.png
    """
    # Try exact match first
    exact_path = puzzle_dir / filename_pattern
    if exact_path.exists():
        return exact_path
    
    # Try with wildcard prefix
    matches = list(puzzle_dir.glob(f'*{filename_pattern}'))
    
    if matches:
        # Return first match (they should all be equivalent for this puzzle)
        return matches[0]
    
    # No match found
    raise FileNotFoundError(f"No image matching '{filename_pattern}' in {puzzle_dir}")


def find_and_read_text_file(puzzle_dir: Path, filename_pattern: str) -> str:
    """
    Find text file matching pattern and return its contents.
    Supports wildcard matching for filenames with prefixes.
    
    Args:
        puzzle_dir: Directory containing puzzle files
        filename_pattern: Filename or pattern (e.g., 'text_description.txt')
        
    Returns:
        Contents of the matching text file
        
    Example:
        Pattern 'text_description.txt' matches:
        - text_description.txt
        - 1_text_description.txt
        - puzzle_001_text_description.txt
    """
    # Try exact match first
    exact_path = puzzle_dir / filename_pattern
    if exact_path.exists():
        with open(exact_path, 'r') as f:
            return f.read()
    
    # Try with wildcard prefix
    matches = list(puzzle_dir.glob(f'*{filename_pattern}'))
    
    if matches:
        # Return contents of first match
        with open(matches[0], 'r') as f:
            return f.read()
    
    # No match found
    raise FileNotFoundError(f"No text file matching '{filename_pattern}' in {puzzle_dir}")


def save_responses(responses, output_path, task, model, dataset_path, meta_data: dict = None, num_runs: int = 1):
    """Save responses to JSON file (used for intermediate caching)"""
    unique_puzzles = len(set(r.get("puzzle_id") for r in responses if r.get("puzzle_id")))
    
    output_data = {
        "task": task,
        "model": model,
        "dataset_path": str(dataset_path),
        "num_samples": len(responses),
        "num_puzzles": unique_puzzles,
        "num_runs": num_runs,
        "num_errors": sum(1 for r in responses if response_has_error(r)),
        "responses": responses,
        **(meta_data or {})
    }
    
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        # First try normal JSON dump
        with open(output_path, 'w') as f:
            json.dump(output_data, f, indent=2)
    except TypeError as e:
        # If that fails due to non-serializable objects, sanitize and retry
        print(f"Warning: JSON serialization failed ({e}), sanitizing data...")
        sanitized_data = sanitize_for_json(output_data)
        with open(output_path, 'w') as f:
            json.dump(sanitized_data, f, indent=2, cls=SafeJSONEncoder)
        print(f"Saved sanitized data to {output_path}")


def extract_json_from_text(text: str) -> Dict[str, Any]:
    """
    Extract JSON object from text that may contain additional content.
    
    Args:
        text: Text potentially containing JSON
        
    Returns:
        Parsed JSON dictionary
    """
    # Try direct parsing first
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    
    # Try to find JSON object in text
    json_pattern = r'\{[^{}]*"answer"[^{}]*\}'
    matches = re.findall(json_pattern, text)
    
    if matches:
        try:
            return json.loads(matches[0])
        except json.JSONDecodeError:
            pass
    
    # Return empty dict if no valid JSON found
    return {}


def normalize_answer(answer: Any, task_name: str) -> Any:
    """
    Normalize answer format for comparison.
    
    Args:
        answer: Raw answer from model or ground truth
        task_name: Task name for task-specific normalization
        
    Returns:
        Normalized answer
    """
    if isinstance(answer, str):
        return answer.strip().upper()
    return answer


def compare_answers(predicted: Any, ground_truth: Any, task_name: str) -> bool:
    """
    Compare predicted answer with ground truth.
    
    Args:
        predicted: Model's predicted answer
        ground_truth: Correct answer
        task_name: Task name for task-specific comparison
        
    Returns:
        True if answers match
    """
    pred_norm = normalize_answer(predicted, task_name)
    gt_norm = normalize_answer(ground_truth, task_name)
    
    return pred_norm == gt_norm


def get_image_paths_for_task(sample: Dict[str, Any], task_name: str) -> List[Path]:
    """
    Get the required image paths for a task based on the prompt.
    
    Args:
        sample: Sample metadata
        task_name: Task name
        
    Returns:
        List of image paths needed for this task
    """
    puzzle_dir = Path(sample['puzzle_dir'])
    images = []

    if task_name == "form-board":
        # Form board needs silhouette and combined
        if 'silhouette_image' in sample:
            images.append(puzzle_dir / sample['silhouette_image'])
        if 'combined_image' in sample:
            images.append(puzzle_dir / sample['combined_image'])
    
    elif task_name == "sliding-puzzle":
        # Sliding puzzle only needs initial
        if 'initial_image' in sample:
            images.append(puzzle_dir / sample['initial_image'])
    
    elif task_name == "hinge-folding":
        # Hinge folding needs initial and target
        if 'initial_image' in sample:
            images.append(puzzle_dir / sample['initial_image'])
        if 'target_image' in sample:
            images.append(puzzle_dir / sample['target_image'])
    
    elif task_name == "paper-fold":
        # Paper fold needs question and combined
        if 'question_image' in sample:
            images.append(puzzle_dir / sample['question_image'])
        if 'combined_image' in sample:
            images.append(puzzle_dir / sample['combined_image'])
    
    return images


def load_existing_responses(output_path: Path) -> Dict[str, Any] | None:
    """
    Load existing responses JSON file if it exists.
    
    Args:
        output_path: Path to responses JSON file
        
    Returns:
        Parsed JSON data or None if file doesn't exist
    """
    output_path = Path(output_path)
    if not output_path.exists():
        return None
    
    try:
        with open(output_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Failed to load existing responses from {output_path}: {e}")
        return None


def analyze_existing_responses(existing_data: Dict[str, Any], require_images: bool = False) -> tuple:
    """
    Analyze existing responses to find successful and failed samples.
    
    A response is considered FAILED if it has any error (top-level or nested in choices).
    A response is considered SUCCESSFUL if it has no errors (even if output_parsed is None).
    
    Args:
        existing_data: Loaded responses JSON data
        
    Returns:
        Tuple of:
        - successful_by_dir: Dict mapping puzzle_dir -> response for successful queries
        - failed_dirs: Set of puzzle_dir strings that had errors
        - total_count: Total number of responses
        - success_count: Number of successful responses
        - fail_count: Number of failed responses
    """
    responses = existing_data.get("responses", [])
    
    successful_by_dir = {}
    failed_dirs = set()
    
    for resp in responses:
        puzzle_dir = resp.get("puzzle_dir")
        if puzzle_dir is None:
            continue
            
        # A response is failed if it has any error (top-level or nested)
        failed = response_has_error(resp)

        # Additionally, when require_images is True (e.g., Gemini generate_images prompts),
        # treat responses with zero generated images as failed so they will be re-queried.
        # This includes no-images/timeout responses — they should be retried with
        # the current (potentially higher) retry budget.
        if not failed and require_images:
            api_response = resp.get("api_response") or {}
            # Minimal image counting logic (mirrors query_google_model.count_generated_images)
            image_count = 0
            candidates = api_response.get("candidates", [])
            for candidate in candidates:
                content = candidate.get("content", {})
                parts = content.get("parts", [])
                for part in parts:
                    if part.get("saved_image_path"):
                        image_count += 1
                    else:
                        inline_data = part.get("inline_data")
                        if isinstance(inline_data, dict) and inline_data.get("data"):
                            image_count += 1
            if image_count == 0:
                failed = True

        if failed:
            failed_dirs.add(puzzle_dir)
        else:
            successful_by_dir[puzzle_dir] = resp
    
    total_count = len(responses)
    success_count = len(successful_by_dir)
    fail_count = len(failed_dirs)
    
    return successful_by_dir, failed_dirs, total_count, success_count, fail_count


def get_puzzles_to_query(
    puzzles: List[Path],
    output_path: Path,
    require_images: bool = False,
) -> tuple:
    """
    Determine which puzzles need to be queried based on existing responses.
    
    Args:
        puzzles: List of puzzle directories to potentially query
        output_path: Path to existing responses JSON file
        
    Returns:
        Tuple of:
        - puzzles_to_query: List of puzzle dirs that need querying (failed or missing)
        - successful_responses: Dict mapping puzzle_dir -> existing successful response
        - stats: Dict with statistics about existing responses
    """
    existing_data = load_existing_responses(output_path)
    
    if existing_data is None:
        # No existing file, query all puzzles
        return puzzles, {}, {
            "existing_file": False,
            "total_existing": 0,
            "successful_existing": 0,
            "failed_existing": 0,
            "to_query": len(puzzles),
        }
    
    successful_by_dir, failed_dirs, total, success, fail = analyze_existing_responses(
        existing_data, require_images=require_images
    )
    
    # Determine which puzzles need querying
    puzzles_to_query = []
    for puzzle_dir in puzzles:
        puzzle_dir_str = str(puzzle_dir)
        # Query if: failed before OR never queried (not in successful_by_dir and not in failed_dirs)
        if puzzle_dir_str in failed_dirs:
            puzzles_to_query.append(puzzle_dir)
        elif puzzle_dir_str not in successful_by_dir:
            # This puzzle wasn't in the existing responses at all
            puzzles_to_query.append(puzzle_dir)
        # else: puzzle was successful, skip it
    
    stats = {
        "existing_file": True,
        "total_existing": total,
        "successful_existing": success,
        "failed_existing": fail,
        "to_query": len(puzzles_to_query),
        "skipping": len(puzzles) - len(puzzles_to_query),
    }
    
    return puzzles_to_query, successful_by_dir, stats


def print_retry_stats(stats: Dict[str, Any], output_path: Path) -> None:
    """Print statistics about retry operation."""
    if not stats.get("existing_file"):
        return
    
    print()
    print(f"📂 Found existing responses: {output_path}")
    print(f"   Total responses: {stats['total_existing']}")
    print(f"   ✓ Successful: {stats['successful_existing']}")
    print(f"   ✗ Failed: {stats['failed_existing']}")
    print(f"   → Will re-query: {stats['to_query']} samples")
    print(f"   → Skipping: {stats['skipping']} successful samples")
    print()

