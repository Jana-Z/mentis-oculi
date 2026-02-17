import json
import argparse
import re
from pathlib import Path
from typing import List

import matplotlib.pyplot as plt
import numpy as np

from generate_puzzles import apply_move, get_valid_moves


chance_performance = {
    'level_01': 0.77490234375,
    'level_02': 0.58447265625,
    'level_03': 0.39404296875,
    'level_04': 0.289306640625,
    'level_05': 0.1845703125,
    'level_06': 0.1845703125
}


def compute_confidence_interval(accuracy: float, n: int, confidence: float = 0.95) -> tuple:
    """Compute Wilson score confidence interval for a binomial proportion."""
    from scipy import stats

    if n <= 0:
        return (0.0, 0.0)

    z = stats.norm.ppf((1 + confidence) / 2)
    denominator = 1 + z**2 / n
    center = (accuracy + z**2 / (2 * n)) / denominator
    margin = z * np.sqrt((accuracy * (1 - accuracy) / n + z**2 / (4 * n**2))) / denominator
    return (center - margin, center + margin)


def _is_solved(grid: List[List[int]], target_state: List[List[int]]) -> bool:
    """Check if the puzzle is solved (matches target state)."""
    return grid == target_state


def _parse_action_sequence(text: str) -> List[str]:
    """Parse action sequence from text response.
    
    Expected formats:
    - JSON: {"answer": "up right down left"}
    - Plain text: "up right down left"
    - With action: prefix: "action: move up action: move right"
    """
    if not text or not isinstance(text, str):
        return []
    
    # Try to parse as JSON first
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "answer" in data:
            answer = data["answer"]
            if isinstance(answer, str):
                return [a.strip().lower() for a in answer.split() if a.strip()]
    except (json.JSONDecodeError, KeyError):
        pass
    
    # Try to extract from <answer> tags
    answer_pattern = r'<answer>(.*?)</answer>'
    answer_matches = re.findall(answer_pattern, text, re.DOTALL | re.IGNORECASE)
    if answer_matches:
        answer_text = answer_matches[-1].strip()
        # Try JSON in answer tag
        try:
            data = json.loads(answer_text)
            if isinstance(data, dict) and "answer" in data:
                answer = data["answer"]
                if isinstance(answer, str):
                    return [a.strip().lower() for a in answer.split() if a.strip()]
        except (json.JSONDecodeError, KeyError):
            pass
        # If not JSON, treat as plain text
        return [a.strip().lower() for a in answer_text.split() if a.strip()]
    
    # Try to find "action: move <direction>" patterns
    pattern = r'\baction:\s*move\s+(\w+)\b'
    matches = re.findall(pattern, text, flags=re.IGNORECASE)
    if matches:
        valid_directions = {'up', 'down', 'left', 'right'}
        actions = [m.lower() for m in matches if m.lower() in valid_directions]
        if actions:
            return actions
    
    # Try plain text parsing (space-separated directions)
    valid_directions = {'up', 'down', 'left', 'right'}
    words = text.lower().split()
    actions = [w for w in words if w in valid_directions]
    if actions:
        return actions
    
    return []


def evaluate_responses(responses_path: str):
    """Evaluate model responses for Sliding Puzzle.

    For each response:
    1. Load the initial state from trace data
    2. Parse the model's proposed actions
    3. Apply the actions to the initial state
    4. Check if solved

    Computes strict accuracy (valid responses only) and lenient accuracy (all responses).
    """
    with open(responses_path, 'r') as f:
        data = json.load(f)

    responses = data["responses"]
    n = len(responses)

    print(f"\n{'='*60}")
    print(f"Evaluating {n} responses from: {Path(responses_path).name}")
    print(f"{'='*60}\n")

    # Aggregates
    solved_flags_lenient: List[bool] = []  # Lenient: skip invalid moves, continue evaluating
    solved_flags_strict: List[bool] = []    # Strict: invalid moves mark response as wrong
    valid_mask: List[bool] = []
    has_invalid_move: List[bool] = []  # Track per sample if it has invalid moves
    has_out_of_bounds: List[bool] = []  # Track per sample if it has out of bounds moves
    parse_failed_mask: List[bool] = []  # Track per sample if parse failed

    pred_num_actions_all: List[int] = []
    gt_num_actions_all: List[int] = []

    model_name = Path(responses_path).parts[-3] if len(Path(responses_path).parts) >= 3 else "model"

    for idx, r in enumerate(responses):
        # Locate puzzle metadata
        puzzle_dir = r.get("puzzle_dir")
        if puzzle_dir is None:
            # Try dataset_path + puzzle_id fallback
            dataset_path = r.get("dataset_path") or data.get("dataset_path")
            pid = r.get("puzzle_id")
            if dataset_path is not None and pid is not None:
                puzzle_dir = str(Path(dataset_path) / f"puzzle_{pid:04d}")
        
        if puzzle_dir is None:
            print(f"Warning: Could not determine puzzle_dir for response {idx}")
            parse_failed_mask.append(True)
            has_invalid_move.append(False)
            has_out_of_bounds.append(False)
            solved_flags_lenient.append(False)
            solved_flags_strict.append(False)
            valid_mask.append(False)
            pred_num_actions_all.append(0)
            gt_num_actions_all.append(0)  # Can't determine GT without puzzle_dir
            continue

        puzzle_dir = Path(puzzle_dir)

        # Load metadata first (separate try block to always get GT even if response processing fails)
        gt_len = 0  # Default to 0 if metadata can't be loaded
        initial_state = None
        target_state = None
        try:
            meta_path = puzzle_dir / "metadata.json"
            with open(meta_path, 'r') as mf:
                meta = json.load(mf)
            initial_state = meta["initial_state"]
            target_state = meta["target_state"]
            solution_moves = meta.get("solution_moves", [])
            gt_len = len(solution_moves)
        except Exception as e:
            print(f"Warning: Could not load metadata for response {idx} from {puzzle_dir}: {e}")

        try:
            if initial_state is None or target_state is None:
                # Metadata loading failed
                parse_failed_mask.append(True)
                has_invalid_move.append(False)
                has_out_of_bounds.append(False)
                solved_flags_lenient.append(False)
                solved_flags_strict.append(False)
                valid_mask.append(False)
                pred_num_actions_all.append(0)
                gt_num_actions_all.append(gt_len)
                continue

            # Parse model's action sequence
            output = r.get("output") or r.get("response") or r.get("text") or r.get("output_parsed").get("answer") if r.get("output_parsed") else None
            if not output:
                parse_failed_mask.append(True)
                has_invalid_move.append(False)
                has_out_of_bounds.append(False)
                solved_flags_lenient.append(False)
                solved_flags_strict.append(False)
                valid_mask.append(False)
                pred_num_actions_all.append(0)
                gt_num_actions_all.append(gt_len)
                continue

            predicted_actions = _parse_action_sequence(output)
            
            if len(predicted_actions) == 0:
                parse_failed_mask.append(True)
                has_invalid_move.append(False)
                has_out_of_bounds.append(False)
                solved_flags_lenient.append(False)
                solved_flags_strict.append(False)
                valid_mask.append(False)
                pred_num_actions_all.append(0)
                gt_num_actions_all.append(gt_len)
                continue

            # Apply each move
            # For lenient: skip invalid moves and continue
            # For strict: invalid moves mark response as wrong
            current_state_lenient = [list(row) for row in initial_state]
            current_state_strict = [list(row) for row in initial_state]
            all_valid_strict = True
            sample_has_invalid_move = False
            sample_has_out_of_bounds = False

            for action in predicted_actions:
                # Check if action is valid direction
                valid_directions = {"up", "down", "left", "right"}
                if action not in valid_directions:
                    # Invalid direction: lenient skips, strict marks as invalid
                    sample_has_invalid_move = True
                    all_valid_strict = False
                    # For lenient, skip this move and continue
                    continue
                
                # Check if move is valid (not out of bounds)
                valid_moves_lenient = get_valid_moves(current_state_lenient)
                if action not in valid_moves_lenient:
                    # Out of bounds: lenient skips, strict marks as invalid
                    sample_has_out_of_bounds = True
                    all_valid_strict = False
                    # For lenient, skip this move and continue
                    continue
                
                # Valid move: apply to both states
                current_state_lenient = apply_move(current_state_lenient, action)
                
                if all_valid_strict:
                    current_state_strict = apply_move(current_state_strict, action)

            # Check if solved for lenient (even if there were invalid moves)
            solved_lenient = _is_solved(current_state_lenient, target_state)

            # For strict: if there were invalid moves or out of bounds, mark as wrong
            if not all_valid_strict:
                solved_strict = False
                valid_mask.append(False)
            else:
                solved_strict = _is_solved(current_state_strict, target_state)
                valid_mask.append(True)

            # Track per-sample flags
            parse_failed_mask.append(False)
            has_invalid_move.append(sample_has_invalid_move)
            has_out_of_bounds.append(sample_has_out_of_bounds)
            
            solved_flags_lenient.append(solved_lenient)
            solved_flags_strict.append(solved_strict)
            pred_num_actions_all.append(len(predicted_actions))
            gt_num_actions_all.append(gt_len)

        except Exception as e:
            print(f"Error processing response {idx}: {e}")
            import traceback
            traceback.print_exc()
            parse_failed_mask.append(True)
            has_invalid_move.append(False)
            has_out_of_bounds.append(False)
            solved_flags_lenient.append(False)
            solved_flags_strict.append(False)
            valid_mask.append(False)
            pred_num_actions_all.append(0)
            gt_num_actions_all.append(gt_len)  # Use actual GT from metadata (loaded earlier)

    # Compute metrics
    n_all = len(solved_flags_lenient)
    n_valid = sum(valid_mask)

    # Both lenient and strict use correct / total
    correct_lenient = sum(solved_flags_lenient)
    accuracy_lenient = correct_lenient / n_all if n_all > 0 else 0.0
    ci_lenient_lower, ci_lenient_upper = compute_confidence_interval(accuracy_lenient, n_all)

    correct_strict = sum(solved_flags_strict)
    accuracy_strict = correct_strict / n_all if n_all > 0 else 0.0
    # For strict, always use 50 as denominator if we have at least 50 responses
    n_strict_denom = 50
    if n_all >= n_strict_denom:
        # Scale proportionally to 50
        scale_factor = n_strict_denom / n_all
        correct_strict_scaled = int(round(correct_strict * scale_factor))
        accuracy_strict = correct_strict_scaled / n_strict_denom
        ci_strict_lower, ci_strict_upper = compute_confidence_interval(accuracy_strict, n_strict_denom)
        correct_strict_display = correct_strict_scaled
        n_strict_display = n_strict_denom
    else:
        # Use actual counts
        ci_strict_lower, ci_strict_upper = compute_confidence_interval(accuracy_strict, n_all)
        correct_strict_display = correct_strict
        n_strict_display = n_all

    # Save metrics JSON
    output_dir = Path(responses_path).parent
    base_name = Path(responses_path).stem
    
    # Extract level key from parent folder: .../level_03/responses.json -> "level_03"
    difficulty_key = output_dir.name

    # Count samples (not individual actions)
    parse_failed_count = sum(parse_failed_mask)
    invalid_moves_count = sum(has_invalid_move)
    out_of_bounds_count = sum(has_out_of_bounds)

    random_accuracy = chance_performance.get(difficulty_key)
    random_ci_lower = random_ci_upper = None
    if random_accuracy is not None:
        random_ci_lower, random_ci_upper = compute_confidence_interval(random_accuracy, n_all)
        random_baseline_entry = {
            "description": "Chance performance assuming random valid moves (max 6 moves).",
            "accuracy": random_accuracy,
            "confidence_interval_95": {
                "lower": random_ci_lower,
                "upper": random_ci_upper,
            },
        }
    else:
        random_baseline_entry = None

    # Build per-response correctness map for pass@k evaluation
    per_response_correct = {}
    for i, r in enumerate(responses):
        puzzle_id = r.get("puzzle_id", r.get("metadata", {}).get("puzzle_id", i))
        # Use strict correctness (more conservative)
        per_response_correct[puzzle_id] = solved_flags_strict[i] if i < len(solved_flags_strict) else False

    metrics = {
        "total_responses": n_all,
        "validity_breakdown": {
            "parse_failed": parse_failed_count,
            "invalid_moves": invalid_moves_count,
            "out_of_bounds": out_of_bounds_count,
            "completely_valid": n_valid,
        },
        "accuracy_lenient": {
            "description": "Accuracy where invalid moves are skipped and evaluation continues",
            "accuracy": accuracy_lenient,
            "correct_count": correct_lenient,
            "total_count": n_all,
            "confidence_interval_95": {
                "lower": ci_lenient_lower,
                "upper": ci_lenient_upper,
            },
        },
        "accuracy_strict": {
            "description": "Accuracy where invalid moves mark response as wrong, always calculated with 50 samples if available",
            "accuracy": accuracy_strict,
            "correct_count": correct_strict_display,
            "total_count": n_strict_display,
            "actual_correct_count": correct_strict,
            "actual_total_count": n_all,
            "confidence_interval_95": {
                "lower": ci_strict_lower,
                "upper": ci_strict_upper,
            },
        },
        "predicted_actions": pred_num_actions_all,
        "required_actions": gt_num_actions_all,
        # Per-response correctness for pass@k evaluation
        "per_response_correct": per_response_correct,
    }

    if random_baseline_entry is not None:
        metrics["random_baseline"] = random_baseline_entry.copy()
        metrics["accuracy_lenient"]["random_baseline"] = random_baseline_entry.copy()
        metrics["accuracy_strict"]["random_baseline"] = random_baseline_entry.copy()

    metrics_path = output_dir / f"{base_name}_metrics.json"
    with open(metrics_path, 'w') as f:
        json.dump(metrics, f, indent=2)

    print(f"📋 Response Validity:")
    print(f"   Total responses: {n_all}")
    print(f"   Parse failed: {parse_failed_count}")
    print(f"   Invalid moves: {invalid_moves_count}")
    print(f"   Out of bounds: {out_of_bounds_count}")
    print(f"   Completely valid: {n_valid}")
    print(f"\n📊 Lenient Accuracy (invalid moves skipped): {accuracy_lenient:.3f} ({correct_lenient}/{n_all})")
    print(f"   95% CI: [{ci_lenient_lower:.3f}, {ci_lenient_upper:.3f}]")
    print(f"📊 Strict Accuracy (invalid moves mark as wrong): {accuracy_strict:.3f} ({correct_strict_display}/{n_strict_display})")
    if n_all >= 50:
        print(f"   (Scaled from {correct_strict}/{n_all} to n=50)")
    print(f"   95% CI: [{ci_strict_lower:.3f}, {ci_strict_upper:.3f}]")
    print(f"\n💾 Saved metrics to: {metrics_path}")

    # Plot: Confusion matrix for Proposed vs Required number of actions
    # Build confusion matrix
    max_actions = max(max(pred_num_actions_all, default=0), max(gt_num_actions_all, default=0))
    if max_actions == 0:
        max_actions = 1

    # Create matrix: rows = predicted, cols = required
    confusion_matrix = np.zeros((max_actions + 1, max_actions + 1), dtype=int)
    for pred, gt in zip(pred_num_actions_all, gt_num_actions_all):
        pred = int(pred)
        gt = int(gt)
        if 0 <= pred <= max_actions and 0 <= gt <= max_actions:
            confusion_matrix[pred, gt] += 1

    # Create the plot
    fig, ax = plt.subplots(figsize=(10, 10))
    im = ax.imshow(confusion_matrix, cmap='Blues', aspect='auto', origin='lower')

    # Add colorbar
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label('Number of Samples', fontsize=12, fontweight='bold')

    # Set labels and ticks
    action_range = list(range(max_actions + 1))
    ax.set_xticks(action_range)
    ax.set_yticks(action_range)
    ax.set_xticklabels(action_range)
    ax.set_yticklabels(action_range)

    ax.set_xlabel('Required Actions (Ground Truth)', fontsize=13, fontweight='bold')
    ax.set_ylabel('Proposed Actions (Model)', fontsize=13, fontweight='bold')
    ax.set_title('Sliding Puzzle: Action Count Confusion Matrix', fontsize=15, fontweight='bold')

    # Add text annotations in each cell
    for i in range(max_actions + 1):
        for j in range(max_actions + 1):
            count = confusion_matrix[i, j]
            if count > 0:
                # Use white text for dark cells, black for light cells
                text_color = 'white' if count > confusion_matrix.max() / 2 else 'black'
                ax.text(j, i, str(count), ha='center', va='center',
                       color=text_color, fontsize=10, fontweight='bold')

    # Add grid
    ax.set_xticks(np.arange(max_actions + 1) - 0.5, minor=True)
    ax.set_yticks(np.arange(max_actions + 1) - 0.5, minor=True)
    ax.grid(which='minor', color='gray', linestyle='-', linewidth=0.5, alpha=0.3)

    plt.tight_layout()
    actions_plot_path = output_dir / f"{base_name}_actions_comparison.png"
    plt.savefig(actions_plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"📈 Saved actions confusion matrix to: {actions_plot_path}")

    # Validity breakdown bar plot
    fig, ax = plt.subplots(figsize=(10, 5))
    categories = ["Parse Failed", "Invalid Moves", "Out of Bounds", "Valid"]
    counts = [parse_failed_count, invalid_moves_count, out_of_bounds_count, n_valid]
    colors = ['#e74c3c', '#f39c12', '#9b59b6', '#2ecc71']
    bars = ax.bar(categories, counts, color=colors, alpha=0.85)
    ax.set_ylabel('Number of Responses', fontsize=12, fontweight='bold')
    ax.set_title('Sliding Puzzle: Response Validity Breakdown', fontsize=14, fontweight='bold')
    ax.grid(axis='y', alpha=0.3)
    for bar, count in zip(bars, counts):
        height = bar.get_height()
        pct = count / n_all * 100 if n_all > 0 else 0.0
        ax.text(bar.get_x() + bar.get_width()/2., height + max(counts) * 0.03,
                f'{count}\n({pct:.1f}%)', ha='center', va='bottom', fontsize=11, fontweight='bold')
    plt.tight_layout()
    validity_plot_path = output_dir / f"{base_name}_validity.png"
    plt.savefig(validity_plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"📊 Saved validity breakdown plot to: {validity_plot_path}")

    # Accuracy plot with confidence intervals
    fig, ax = plt.subplots(figsize=(10, 6))
    categories = [f'Lenient Accuracy\n(Invalid Moves Skipped; n={n_all})', f'Strict Accuracy\n(Invalid Moves = Wrong; n={n_strict_display})']
    accuracies = [accuracy_lenient, accuracy_strict]
    ci_lowers = [ci_lenient_lower, ci_strict_lower]
    ci_uppers = [ci_lenient_upper, ci_strict_upper]

    # Calculate error bars (distance from center to bounds)
    errors_lower = [acc - lower for acc, lower in zip(accuracies, ci_lowers)]
    errors_upper = [upper - acc for acc, upper in zip(accuracies, ci_uppers)]

    # Random baseline: chance performance
    if random_accuracy is not None and random_ci_lower is not None and random_ci_upper is not None:
        # Plot random baseline in background (before bars so it appears behind)
        ax.axhspan(random_ci_lower, random_ci_upper, alpha=0.2, color='#e74c3c',
                   label='Chance Performance 95% CI\n(Random valid moves)')
        ax.axhline(y=random_accuracy, color='#e74c3c', linestyle='--', linewidth=2,
                   label=f'Chance Performance ({random_accuracy:.3f}). Assuming random valid moves, stopping when reaching target state. Max 6 moves.')

    # Create bars
    bars = ax.bar(categories, accuracies, color=['#3498db', '#2ecc71'], alpha=0.85, width=0.6)

    # Add error bars for confidence intervals (asymmetric)
    ax.errorbar(categories, accuracies, yerr=(errors_lower, errors_upper),
                fmt='none', color='black', capsize=8, capthick=2, linewidth=2, elinewidth=2)

    ax.set_ylabel('Accuracy', fontsize=13, fontweight='bold')
    ax.set_title(f'Sliding Puzzle {model_name.capitalize()} Accuracy (n={n_all})', fontsize=15, fontweight='bold')
    ax.set_ylim([0, min(1.1, max(accuracies) + max(errors_upper) + 0.1)])
    ax.grid(axis='y', alpha=0.3)
    ax.axhline(y=1.0, color='gray', linestyle='--', alpha=0.5, linewidth=1)
    ax.legend(fontsize=10, loc='upper right')

    plt.tight_layout()
    accuracy_plot_path = output_dir / f"{base_name}_accuracy.png"
    plt.savefig(accuracy_plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    print(f"📊 Saved accuracy plot to: {accuracy_plot_path}")

    print(f"\n{'='*60}")
    print("✅ Evaluation complete!")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate model responses for sliding puzzle benchmark"
    )
    parser.add_argument("--responses", type=str, required=True, help="Path to the responses JSON file")
    args = parser.parse_args()
    evaluate_responses(args.responses)


if __name__ == "__main__":
    main()


