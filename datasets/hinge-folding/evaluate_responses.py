# Load json from the given path
# Answer is already extracted from the response in the 'output_parsed' key
# Compare the answer with the ground truth answer
# Compute the accuracy
# Save the metrics to a new json file (in the same directory as the responses file)
# The metrics should include the accuracy
# Also plot the accuracy with CI and the CI around the random performance

import json
import argparse
import os
import sys
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np
from collections import Counter, defaultdict


def compute_confidence_interval(accuracy: float, n: int, confidence: float = 0.95) -> tuple:
    """Compute Wilson score confidence interval for a binomial proportion.
    
    Args:
        accuracy: Observed proportion (accuracy)
        n: Sample size
        confidence: Confidence level (default 0.95 for 95% CI)
        
    Returns:
        (lower_bound, upper_bound) tuple
    """
    from scipy import stats
    
    # Wilson score interval
    z = stats.norm.ppf((1 + confidence) / 2)
    denominator = 1 + z**2 / n
    center = (accuracy + z**2 / (2 * n)) / denominator
    margin = z * np.sqrt((accuracy * (1 - accuracy) / n + z**2 / (4 * n**2))) / denominator
    
    return (center - margin, center + margin)


def normalize_rotation_sequence(seq: str) -> set:
    """Normalize a rotation sequence to a set of (hinge, angle) tuples.
    
    Args:
        seq: Rotation sequence like "A 90, B 180" or "1 90, 2 180"
    
    Returns:
        Set of (hinge_id, angle) tuples
    """
    if not seq:
        return set()
    
    rotations = set()
    # Split by comma and parse each rotation
    for part in seq.split(','):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        if len(tokens) >= 2:
            hinge_id = tokens[0].strip()
            try:
                angle = int(tokens[1].strip())
                rotations.add((hinge_id, angle))
            except ValueError:
                continue
    
    return rotations


def extract_hinge_ids(seq: str) -> set:
    """Extract hinge IDs from a rotation sequence.
    
    Args:
        seq: Rotation sequence like "A 90, B 180" or "1 90, 2 180"
    
    Returns:
        Set of hinge IDs
    """
    if not seq:
        return set()
    
    hinge_ids = set()
    for part in seq.split(','):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        if len(tokens) >= 1:
            hinge_id = tokens[0].strip()
            hinge_ids.add(hinge_id)
    
    return hinge_ids


def filter_valid_rotations(seq: str, valid_hinge_ids: set) -> set:
    """Filter a rotation sequence to keep only rotations with valid hinge IDs.
    
    Args:
        seq: Rotation sequence like "A 90, B 180, C 90"
        valid_hinge_ids: Set of valid hinge IDs
    
    Returns:
        Set of (hinge_id, angle) tuples for valid rotations only
    """
    if not seq:
        return set()
    
    rotations = set()
    # Split by comma and parse each rotation
    for part in seq.split(','):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        if len(tokens) >= 2:
            hinge_id = tokens[0].strip()
            if hinge_id in valid_hinge_ids:  # Only include if hinge ID is valid
                try:
                    angle = int(tokens[1].strip())
                    rotations.add((hinge_id, angle))
                except ValueError:
                    continue
    
    return rotations


def evaluate_responses(responses_path: str):
    """Evaluate model responses and generate metrics and plots.
    
    Args:
        responses_path: Path to the responses JSON file
    """
    # Load responses
    with open(responses_path, 'r') as f:
        data = json.load(f)
    
    responses = data["responses"]
    n = len(responses)
    
    print(f"\n{'='*60}")
    print(f"Evaluating {n} responses from: {Path(responses_path).name}")
    print(f"{'='*60}\n")
    
    # Extract predictions and ground truth
    all_predictions = []  # All responses (for lenient accuracy)
    all_ground_truth = []
    all_num_hinges = []  # Number of hinges in ground truth
    all_pred_num_hinges = []  # Number of hinges model tried to actuate
    all_is_valid = []  # Track which responses are valid
    all_valid_hinge_ids = []  # Track valid hinge IDs for each response (for lenient accuracy)
    
    predictions = []  # Only valid responses (for strict accuracy)
    ground_truth = []
    valid_responses = []
    num_hinges_list = []
    
    # Track validity categories
    n_parse_failed = 0
    n_invalid_hinge_ids = 0
    invalid_hinge_responses = []

    model_name = Path(responses_path).parts[-3]
    
    for r in responses:
        gt = r.get("metadata", {}).get("rotation_sequence")
        num_hinges = r.get("metadata", {}).get("num_hinges", 1)
        
        # Track all responses for lenient accuracy
        if gt:
            all_ground_truth.append(gt)
            all_num_hinges.append(num_hinges)
            valid_hinge_ids = extract_hinge_ids(gt)
            all_valid_hinge_ids.append(valid_hinge_ids)
        else:
            all_ground_truth.append("")
            all_num_hinges.append(num_hinges)
            all_valid_hinge_ids.append(set())
        
        try:
            pred = r.get("output_parsed", {}).get("answer")
            
            if not pred or not gt:
                n_parse_failed += 1
                all_predictions.append("")  # Empty prediction for failed parse
                # Try to extract number of hinges even if parse failed
                if pred:
                    pred_hinge_ids = extract_hinge_ids(pred)
                    all_pred_num_hinges.append(len(pred_hinge_ids))
                else:
                    all_pred_num_hinges.append(0)  # No hinges actuated if no prediction
                all_is_valid.append(False)
                continue
            
            # Extract number of hinges model tried to actuate
            pred_hinge_ids = extract_hinge_ids(pred)
            pred_num_hinges = len(pred_hinge_ids)
            
            # Check if predicted hinge IDs are valid
            valid_hinge_ids = extract_hinge_ids(gt)
            
            if not pred_hinge_ids.issubset(valid_hinge_ids):
                n_invalid_hinge_ids += 1
                invalid_hinge_responses.append({
                    "prediction": pred,
                    "ground_truth": gt,
                    "valid_hinge_ids": list(valid_hinge_ids),
                    "pred_hinge_ids": list(pred_hinge_ids),
                    "invalid_ids": list(pred_hinge_ids - valid_hinge_ids)
                })
                all_predictions.append(pred)
                all_pred_num_hinges.append(pred_num_hinges)
                all_is_valid.append(False)
                continue
            
            # Valid response
            all_predictions.append(pred)
            all_pred_num_hinges.append(pred_num_hinges)
            all_is_valid.append(True)
            predictions.append(pred)
            ground_truth.append(gt)
            num_hinges_list.append(num_hinges)
            valid_responses.append(r)
        except:
            n_parse_failed += 1
            all_predictions.append("")
            all_pred_num_hinges.append(0)  # No hinges actuated if exception
            all_is_valid.append(False)
            continue
    
    n_valid = len(predictions)
    n_invalid = n - n_valid
    
    if n_parse_failed > 0:
        print(f"⚠️  Warning: {n_parse_failed} responses failed to parse")
    if n_invalid_hinge_ids > 0:
        print(f"⚠️  Warning: {n_invalid_hinge_ids} responses contain invalid hinge IDs")
    
    # Compute both lenient and strict accuracy over all samples (n_all)
    # The only difference is which samples are considered correct:
    # - Lenient: filter out invalid hinge IDs and compare remaining valid rotations
    # - Strict: invalid hinge IDs mark the entire response as wrong
    n_all = len(all_predictions)
    correct_lenient = 0
    correct_strict = 0
    per_response_correct_strict = []  # Track per-response correctness for pass@k
    
    for pred, gt, valid_hinge_ids, is_valid in zip(all_predictions, all_ground_truth, all_valid_hinge_ids, all_is_valid):
        if not pred or not gt:
            # Parse failures are wrong for both lenient and strict
            per_response_correct_strict.append(False)
            continue
        
        gt_set = normalize_rotation_sequence(gt)
        
        # For strict: if there are invalid hinge IDs, mark as wrong
        is_correct_strict = False
        if is_valid:
            # No invalid hinge IDs - compare full prediction
            pred_set = normalize_rotation_sequence(pred)
            if pred_set == gt_set:
                correct_strict += 1
                is_correct_strict = True
        # If not valid (has invalid hinge IDs), strict marks it as wrong (don't increment)
        per_response_correct_strict.append(is_correct_strict)
        
        # For lenient: filter out invalid hinge IDs and compare remaining valid rotations
        pred_filtered = filter_valid_rotations(pred, valid_hinge_ids)
        if pred_filtered == gt_set:
            correct_lenient += 1
    
    accuracy_strict = correct_strict / n_all if n_all > 0 else 0.0
    ci_strict_lower, ci_strict_upper = compute_confidence_interval(accuracy_strict, n_all)
    
    accuracy_lenient = correct_lenient / n_all if n_all > 0 else 0.0
    ci_lenient_lower, ci_lenient_upper = compute_confidence_interval(accuracy_lenient, n_all)
    
    # Calculate random baseline
    # For hinge-folding: each hinge can be rotated at multiple angles (45, 90, 135, 180, 270, etc.)
    # Assuming 3 possible angles (90, 180, 270) per hinge
    avg_num_hinges = np.mean(all_num_hinges) if all_num_hinges else 1
    random_accuracy = 1 / (3 ** avg_num_hinges)
    random_ci_lower, random_ci_upper = compute_confidence_interval(random_accuracy, n_all)
    
    # Count number of hinges distribution
    hinge_distribution = Counter(num_hinges_list)
    
    # Count how many got correct per number of hinges
    correct_by_hinges = defaultdict(int)
    total_by_hinges = defaultdict(int)
    
    for pred, gt, nh in zip(predictions, ground_truth, num_hinges_list):
        pred_set = normalize_rotation_sequence(pred)
        gt_set = normalize_rotation_sequence(gt)
        total_by_hinges[nh] += 1
        if pred_set == gt_set:
            correct_by_hinges[nh] += 1
    
    # Print metrics
    print(f"📋 Response Validity:")
    print(f"   Total responses: {n}")
    print(f"   Valid responses: {n_valid} ({n_valid/n*100:.1f}%)")
    print(f"   Parse failed: {n_parse_failed} ({n_parse_failed/n*100:.1f}%)")
    print(f"   Invalid hinge IDs: {n_invalid_hinge_ids} ({n_invalid_hinge_ids/n*100:.1f}%)")
    print(f"\n📊 Lenient Accuracy (over all {n_all} samples, invalid hinge IDs ignored):")
    print(f"   Accuracy: {accuracy_lenient:.3f} ({correct_lenient}/{n_all})")
    print(f"   95% CI: [{ci_lenient_lower:.3f}, {ci_lenient_upper:.3f}]")
    print(f"\n📊 Strict Accuracy (over all {n_all} samples, invalid hinge IDs mark as wrong):")
    print(f"   Accuracy: {accuracy_strict:.3f} ({correct_strict}/{n_all})")
    print(f"   95% CI: [{ci_strict_lower:.3f}, {ci_strict_upper:.3f}]")
    print(f"\n📉 Random Baseline:")
    print(f"   Accuracy: {random_accuracy:.6f} (avg {avg_num_hinges:.1f} hinges)")
    print(f"   95% CI: [{random_ci_lower:.6f}, {random_ci_upper:.6f}]")
    print(f"\n📈 Distribution by Number of Hinges:")
    for num_hinges in sorted(hinge_distribution.keys()):
        count = hinge_distribution[num_hinges]
        acc = correct_by_hinges[num_hinges] / total_by_hinges[num_hinges] if total_by_hinges[num_hinges] > 0 else 0
        pct = count / n_valid * 100 if n_valid > 0 else 0
        print(f"   {num_hinges} hinge(s): {count:3d} samples ({pct:5.1f}%), accuracy: {acc:.3f}")
    
    # Prepare output directory
    output_dir = Path(responses_path).parent
    base_name = Path(responses_path).stem
    
    # Prepare accuracy by hinges for metrics
    accuracy_by_hinges = {}
    for nh in sorted(total_by_hinges.keys()):
        accuracy_by_hinges[nh] = {
            "accuracy": correct_by_hinges[nh] / total_by_hinges[nh] if total_by_hinges[nh] > 0 else 0,
            "correct": correct_by_hinges[nh],
            "total": total_by_hinges[nh]
        }
    
    # Save metrics to JSON
    metrics = {
        "total_responses": n,
        "valid_responses": n_valid,
        "invalid_responses": n_invalid,
        "validity_breakdown": {
            "valid": n_valid,
            "parse_failed": n_parse_failed,
            "invalid_hinge_ids": n_invalid_hinge_ids
        },
        "invalid_hinge_examples": invalid_hinge_responses[:10],  # Save up to 10 examples
        "accuracy_lenient": {
            "description": "Accuracy over all samples, invalid hinge IDs are ignored (filtered out)",
            "accuracy": accuracy_lenient,
            "correct_count": correct_lenient,
            "total_count": n_all,
            "confidence_interval_95": {
                "lower": ci_lenient_lower,
                "upper": ci_lenient_upper
            }
        },
        "accuracy_strict": {
            "description": "Accuracy over all samples, invalid hinge IDs mark response as wrong",
            "accuracy": accuracy_strict,
            "correct_count": correct_strict,
            "total_count": n_all,
            "confidence_interval_95": {
                "lower": ci_strict_lower,
                "upper": ci_strict_upper
            }
        },
        "random_baseline": {
            "accuracy": random_accuracy,
            "avg_num_hinges": avg_num_hinges,
            "confidence_interval_95": {
                "lower": random_ci_lower,
                "upper": random_ci_upper
            }
        },
        "hinge_distribution": dict(hinge_distribution),
        "accuracy_by_num_hinges": accuracy_by_hinges,
        # Per-response correctness for pass@k evaluation
        "per_response_correct": {
            r.get("puzzle_id", r.get("metadata", {}).get("puzzle_id", i)): correct
            for i, (r, correct) in enumerate(zip(responses, per_response_correct_strict))
        }
    }
    
    metrics_path = output_dir / f"{base_name}_metrics.json"
    with open(metrics_path, 'w') as f:
        json.dump(metrics, f, indent=2)
    
    print(f"\n💾 Saved metrics to: {metrics_path}")
    
    # ── Plot 1: Accuracy with Confidence Intervals ──────────────────────────
    fig, ax = plt.subplots(figsize=(12, 6))
    
    # Plot random baseline as colored box (CI region) in background
    ax.axhspan(random_ci_lower, random_ci_upper, alpha=0.2, color='#e74c3c', 
        xmin=0.05, xmax=0.95, label=f'Random Baseline 95% CI (n={n_valid})')
    ax.axhline(y=random_accuracy, color='#e74c3c', linestyle='--', linewidth=2, 
               label=f'Random Baseline ({random_accuracy:.4f})')
    
    # Plot both lenient and strict accuracies
    x_positions = [-0.35, 0.35]
    accuracies = [accuracy_lenient, accuracy_strict]
    ci_lowers = [ci_lenient_lower, ci_strict_lower]
    ci_uppers = [ci_lenient_upper, ci_strict_upper]
    colors = ['#3498db', '#2ecc71']
    labels = [f'Lenient (n={n_all})', f'Strict (n={n_all})']
    
    for x, acc, ci_low, ci_up, color, label in zip(x_positions, accuracies, ci_lowers, ci_uppers, colors, labels):
        ax.bar(x, acc, width=0.25, label=label, color=color, alpha=0.8)
        ax.errorbar(x, acc, yerr=[[acc - ci_low], [ci_up - acc]], 
                    fmt='none', color='black', capsize=8, capthick=2, linewidth=2)
        # Add accuracy text on bar
        y_offset = 0.05
        ax.text(x, acc + y_offset, f'{acc:.3f}', ha='center', fontsize=11, fontweight='bold')
    
    # Styling
    ax.set_ylabel('Accuracy', fontsize=14, fontweight='bold')
    ax.set_title(f'Hinge Folding: Model Performance vs Random Baseline\n(Lenient: invalid IDs ignored | Strict: invalid IDs mark as wrong, 95% CI)', 
                 fontsize=16, fontweight='bold', pad=20)
    ax.set_xticks([0])
    ax.set_xticklabels([model_name.capitalize()], fontsize=12)
    ax.set_xlim(-0.7, 0.7)
    ax.set_ylim(0, 1.0)
    ax.grid(axis='y', alpha=0.3)
    ax.legend(fontsize=11, loc='upper right')
    
    plt.tight_layout()
    accuracy_plot_path = output_dir / f"{base_name}_accuracy.png"
    plt.savefig(accuracy_plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"📊 Saved accuracy plot to: {accuracy_plot_path}")
    
    # ── Plot 2: Accuracy by Number of Hinges ──────────────────────
    fig, ax = plt.subplots(figsize=(12, 6))
    
    hinge_nums = sorted(total_by_hinges.keys())
    accuracies_by_hinge = [correct_by_hinges[nh] / total_by_hinges[nh] if total_by_hinges[nh] > 0 else 0 
                           for nh in hinge_nums]
    counts_by_hinge = [total_by_hinges[nh] for nh in hinge_nums]
    
    # Create bar plot
    bars = ax.bar(hinge_nums, accuracies_by_hinge, color='#3498db', alpha=0.8)
    
    # Add overall strict accuracy line
    ax.axhline(y=accuracy_strict, color='green', linestyle='--', linewidth=2, 
               label=f'Overall Strict Accuracy ({accuracy_strict:.3f})')
    
    # Styling
    ax.set_xlabel('Number of Hinges', fontsize=14, fontweight='bold')
    ax.set_ylabel('Accuracy', fontsize=14, fontweight='bold')
    ax.set_title(f'Hinge Folding: Accuracy by Number of Hinges\n(n={n_valid})', 
                 fontsize=16, fontweight='bold', pad=20)
    ax.set_xticks(hinge_nums)
    ax.set_ylim(0, 1.0)
    ax.legend(fontsize=11)
    ax.grid(axis='y', alpha=0.3)
    
    # Add accuracy and count labels on bars
    for bar, acc, count in zip(bars, accuracies_by_hinge, counts_by_hinge):
        height = bar.get_height()
        ax.text(bar.get_x() + bar.get_width()/2., height + 0.03,
               f'{acc:.3f}\n(n={count})',
               ha='center', va='bottom', fontsize=10, fontweight='bold')
    
    plt.tight_layout()
    distribution_plot_path = output_dir / f"{base_name}_by_hinges.png"
    plt.savefig(distribution_plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"📊 Saved accuracy by hinges plot to: {distribution_plot_path}")
    
    # ── Plot 3: Confusion Matrix for Number of Hinges ──────────────────────────────
    # Build confusion matrix: rows = predicted hinges, cols = required hinges
    max_hinges = max(max(all_num_hinges, default=0), max(all_pred_num_hinges, default=0))
    if max_hinges == 0:
        max_hinges = 1

    # Create matrix: rows = predicted, cols = required
    confusion_matrix = np.zeros((max_hinges + 1, max_hinges + 1), dtype=int)
    for pred_num, gt_num in zip(all_pred_num_hinges, all_num_hinges):
        pred_num = int(pred_num)
        gt_num = int(gt_num)
        if 0 <= pred_num <= max_hinges and 0 <= gt_num <= max_hinges:
            confusion_matrix[pred_num, gt_num] += 1

    # Create the plot
    fig, ax = plt.subplots(figsize=(10, 10))
    im = ax.imshow(confusion_matrix, cmap='Blues', aspect='auto', origin='lower')

    # Add colorbar
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label('Number of Samples', fontsize=12, fontweight='bold')

    # Set labels and ticks
    hinge_range = list(range(max_hinges + 1))
    ax.set_xticks(hinge_range)
    ax.set_yticks(hinge_range)
    ax.set_xticklabels(hinge_range)
    ax.set_yticklabels(hinge_range)

    ax.set_xlabel('Required Hinges (Ground Truth)', fontsize=13, fontweight='bold')
    ax.set_ylabel('Predicted Hinges (Model)', fontsize=13, fontweight='bold')
    ax.set_title('Hinge Folding: Hinge Count Confusion Matrix', fontsize=15, fontweight='bold')

    # Add text annotations in each cell
    for i in range(max_hinges + 1):
        for j in range(max_hinges + 1):
            count = confusion_matrix[i, j]
            if count > 0:
                # Use white text for dark cells, black for light cells
                text_color = 'white' if count > confusion_matrix.max() / 2 else 'black'
                ax.text(j, i, str(count), ha='center', va='center',
                       color=text_color, fontsize=10, fontweight='bold')

    # Add grid
    ax.set_xticks(np.arange(max_hinges + 1) - 0.5, minor=True)
    ax.set_yticks(np.arange(max_hinges + 1) - 0.5, minor=True)
    ax.grid(which='minor', color='gray', linestyle='-', linewidth=0.5, alpha=0.3)

    plt.tight_layout()
    distribution_count_plot_path = output_dir / f"{base_name}_sample_distribution.png"
    plt.savefig(distribution_count_plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"📊 Saved hinge count confusion matrix to: {distribution_count_plot_path}")
    
    # ── Plot 4: Response Validity Breakdown ──────────────────────────────
    fig, ax = plt.subplots(figsize=(10, 6))
    
    categories = ['Valid', 'Parse Failed', 'Invalid Hinge IDs']
    counts = [n_valid, n_parse_failed, n_invalid_hinge_ids]
    colors = ['#2ecc71', '#e74c3c', '#f39c12']
    
    bars = ax.bar(categories, counts, color=colors, alpha=0.8)
    
    ax.set_ylabel('Number of Responses', fontsize=14, fontweight='bold')
    ax.set_title(f'Hinge Folding: Response Validity Breakdown\n(n={n})', 
                 fontsize=16, fontweight='bold', pad=20)
    ax.grid(axis='y', alpha=0.3)
    
    # Add count and percentage labels on bars
    for bar, count in zip(bars, counts):
        height = bar.get_height()
        pct = count / n * 100 if n > 0 else 0
        ax.text(bar.get_x() + bar.get_width()/2., height + max(counts) * 0.02,
               f'{count}\n({pct:.1f}%)',
               ha='center', va='bottom', fontsize=12, fontweight='bold')
    
    plt.tight_layout()
    validity_plot_path = output_dir / f"{base_name}_validity.png"
    plt.savefig(validity_plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"📊 Saved validity breakdown plot to: {validity_plot_path}")
    
    print(f"\n{'='*60}")
    print("✅ Evaluation complete!")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate model responses for hinge-folding benchmark"
    )
    parser.add_argument("--responses", type=str, required=True, 
                       help="Path to the responses JSON file")
    args = parser.parse_args()
    
    evaluate_responses(args.responses)


if __name__ == "__main__":
    main()