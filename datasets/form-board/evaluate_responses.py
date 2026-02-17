import json
import argparse
import sys
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np


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


def parse_answer(answer_str):
    """Parse answer string into a set of pieces.
    
    Handles formats like:
    - "A C E" (space-separated)
    - "A, C, E" (comma-separated)
    - ["A", "C", "E"] (list)
    
    Returns:
        set: Set of piece labels
    """
    if isinstance(answer_str, list):
        return set(answer_str)
    elif isinstance(answer_str, str):
        # Split by space or comma
        pieces = [p.strip() for p in answer_str.replace(",", " ").split()]
        return set(p for p in pieces if p)  # Filter empty strings
    else:
        return set()


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
    
    # Extract predictions and ground truth (as sets for multi-select)
    predictions = []
    ground_truth = []
    valid_responses = []
    
    for r in responses:
        
        try:
            pred_raw = r.get("output_parsed", {}).get("answer")
            gt_raw = r.get("metadata", {}).get("solution_pieces")
            
            if pred_raw is not None and gt_raw is not None:
                pred = parse_answer(pred_raw)
                gt = parse_answer(gt_raw)
                
                if pred or gt:  # At least one is non-empty
                    predictions.append(pred)
                    ground_truth.append(gt)
                    valid_responses.append(r)
        except Exception as e:
            continue
    
    n_valid = len(predictions)
    n_invalid = n - n_valid
    
    if n_invalid > 0:
        print(f"⚠️  Warning: {n_invalid} responses could not be parsed")
    
    if n_valid == 0:
        print("❌ No valid responses to evaluate!")
        return
    
    # ═══════════════════════════════════════════════════════════════════════
    # TOTAL ACCURACY: Exact match (all pieces correct)
    # ═══════════════════════════════════════════════════════════════════════
    # Track per-response correctness for pass@k evaluation
    per_response_correct = [p == g for p, g in zip(predictions, ground_truth)]
    correct_total = sum(per_response_correct)
    accuracy_total = correct_total / n_valid
    
    # Compute confidence intervals
    ci_lower_total, ci_upper_total = compute_confidence_interval(accuracy_total, n_valid)
    
    # Random baseline for total accuracy
    # Random agent: uniformly chooses from ALL subsets of size 1, 2, 3, 4, or 5
    from scipy.special import comb
    
    output_dir = Path(responses_path).parent
    total_options = comb(5, 1) + comb(5, 2) + comb(5, 3) + comb(5, 4) + comb(5, 5)
    random_accuracy_total = 1.0 / total_options
    
    random_ci_lower_total, random_ci_upper_total = compute_confidence_interval(random_accuracy_total, n_valid)
    
    # ═══════════════════════════════════════════════════════════════════════
    # PER-PIECE ACCURACY: Individual piece selection accuracy
    # ═══════════════════════════════════════════════════════════════════════
    all_choices = ['A', 'B', 'C', 'D', 'E']
    
    # For each piece, count: correct selections, incorrect selections
    per_piece_stats = {choice: {'tp': 0, 'fp': 0, 'tn': 0, 'fn': 0} for choice in all_choices}
    
    for pred, gt in zip(predictions, ground_truth):
        for choice in all_choices:
            pred_has = choice in pred
            gt_has = choice in gt
            
            if pred_has and gt_has:
                per_piece_stats[choice]['tp'] += 1  # True positive
            elif pred_has and not gt_has:
                per_piece_stats[choice]['fp'] += 1  # False positive
            elif not pred_has and not gt_has:
                per_piece_stats[choice]['tn'] += 1  # True negative
            else:  # not pred_has and gt_has
                per_piece_stats[choice]['fn'] += 1  # False negative
    
    # Compute per-piece accuracy (both selecting and not-selecting correctly)
    per_piece_accuracy = {}
    per_piece_precision = {}
    per_piece_recall = {}
    
    for choice in all_choices:
        stats = per_piece_stats[choice]
        total = stats['tp'] + stats['fp'] + stats['tn'] + stats['fn']
        
        # Accuracy: (TP + TN) / Total
        per_piece_accuracy[choice] = (stats['tp'] + stats['tn']) / total if total > 0 else 0.0
        
        # Precision: TP / (TP + FP)
        per_piece_precision[choice] = stats['tp'] / (stats['tp'] + stats['fp']) if (stats['tp'] + stats['fp']) > 0 else 0.0
        
        # Recall: TP / (TP + FN)
        per_piece_recall[choice] = stats['tp'] / (stats['tp'] + stats['fn']) if (stats['tp'] + stats['fn']) > 0 else 0.0
    
    # Average per-piece accuracy
    avg_per_piece_accuracy = np.mean(list(per_piece_accuracy.values()))
    ci_lower_total_per_piece, ci_upper_total_per_piece = compute_confidence_interval(avg_per_piece_accuracy, n_valid)
    
    # Random baseline for per-piece: 0.5 (50% chance of correct selection/non-selection)
    random_per_piece_accuracy = 0.5
    random_ci_lower_total_per_piece, random_ci_upper_total_per_piece = compute_confidence_interval(random_per_piece_accuracy, n_valid)
    
    # ═══════════════════════════════════════════════════════════════════════
    # SELECTION BIAS: Which pieces are over/under-selected
    # ═══════════════════════════════════════════════════════════════════════
    
    # Count how many times each piece is selected (predicted)
    prediction_selection_counts = {choice: 0 for choice in all_choices}
    for pred in predictions:
        for choice in pred:
            if choice in prediction_selection_counts:
                prediction_selection_counts[choice] += 1
    
    # Count how many times each piece should be selected (ground truth)
    gt_selection_counts = {choice: 0 for choice in all_choices}
    for gt in ground_truth:
        for choice in gt:
            if choice in gt_selection_counts:
                gt_selection_counts[choice] += 1
    
    # Print metrics
    print(f"📊 TOTAL ACCURACY (Exact Match):")
    print(f"   Accuracy: {accuracy_total:.3f} ({correct_total}/{n_valid})")
    print(f"   95% CI: [{ci_lower_total:.3f}, {ci_upper_total:.3f}]")
    print(f"   Random baseline: {random_accuracy_total:.3f}")
    print(f"   Random 95% CI: [{random_ci_lower_total:.3f}, {random_ci_upper_total:.3f}]")
    
    print(f"\n📊 PER-PIECE ACCURACY (Individual Selections):")
    print(f"   Average: {avg_per_piece_accuracy:.3f}")
    print(f"   Random baseline: {random_per_piece_accuracy:.3f}")
    print(f"\n   Per-piece breakdown:")
    for choice in all_choices:
        acc = per_piece_accuracy[choice]
        prec = per_piece_precision[choice]
        rec = per_piece_recall[choice]
        print(f"   {choice}: Acc={acc:.3f}, Prec={prec:.3f}, Rec={rec:.3f}")
    
    print(f"\n📈 SELECTION COUNTS (Prediction vs Ground Truth):")
    for choice in all_choices:
        pred_count = prediction_selection_counts[choice]
        gt_count = gt_selection_counts[choice]
        diff = pred_count - gt_count
        sign = "+" if diff > 0 else ""
        print(f"   {choice}: Predicted={pred_count:3d}, GT={gt_count:3d}, Diff={sign}{diff:3d}")
    
    # Prepare output directory
    output_dir = Path(responses_path).parent
    base_name = Path(responses_path).stem
    
    # Build chance baseline entry used across accuracy views
    random_baseline_entry = {
        "description": (
            "Chance accuracy for exact set selection assuming uniform random choice "
            "over all ground-truth set sizes."
        ),
        "accuracy": random_accuracy_total,
        "confidence_interval_95": {
            "lower": random_ci_lower_total,
            "upper": random_ci_upper_total
        }
    }

    accuracy_entry = {
        "description": "Exact-match accuracy over valid responses.",
        "accuracy": accuracy_total,
        "correct_count": correct_total,
        "total_count": n_valid,
        "confidence_interval_95": {
            "lower": ci_lower_total,
            "upper": ci_upper_total
        },
        "random_baseline": random_baseline_entry.copy()
    }

    # Save metrics to JSON
    metrics = {
        "total_responses": n,
        "valid_responses": n_valid,
        "invalid_responses": n_invalid,
        "validity_breakdown": {
            "parse_failed": n_invalid,
            "completely_valid": n_valid
        },
        "accuracy_lenient": accuracy_entry.copy(),
        "accuracy_strict": accuracy_entry.copy(),
        "per_piece_accuracy": {
            "average": avg_per_piece_accuracy,
            "random_baseline": random_per_piece_accuracy,
            "by_choice": per_piece_accuracy,
            "precision_by_choice": per_piece_precision,
            "recall_by_choice": per_piece_recall,
            "stats_by_choice": per_piece_stats,
            "confidence_interval_95_per_piece": {
                "lower": ci_lower_total_per_piece,
                "upper": ci_upper_total_per_piece
            },
            "confidence_interval_95_random_baseline": {
                "lower": random_ci_lower_total_per_piece,
                "upper": random_ci_upper_total_per_piece
            }
        },
        "selection_bias": {
            "predicted_counts": prediction_selection_counts,
            "ground_truth_counts": gt_selection_counts,
            "difference": {choice: prediction_selection_counts[choice] - gt_selection_counts[choice] 
                          for choice in all_choices}
        },
        # Per-response correctness for pass@k evaluation
        # Maps puzzle_id to whether the response was correct
        "per_response_correct": {
            r.get("puzzle_id", i): correct 
            for i, (r, correct) in enumerate(zip(valid_responses, per_response_correct))
        }
    }

    metrics["random_baseline"] = random_baseline_entry.copy()
    
    metrics_path = output_dir / f"{base_name}_metrics.json"
    with open(metrics_path, 'w') as f:
        json.dump(metrics, f, indent=2)
    
    print(f"\n💾 Saved metrics to: {metrics_path}")
    
    # ══════════════════════════════════════════════════════════════════════
    # Plot 1: Total + Per-Piece Accuracy Comparison
    # ══════════════════════════════════════════════════════════════════════
    fig, ax = plt.subplots(figsize=(12, 6))
    
    # Plot random baseline regions as colored boxes (CI regions) in background
    # Total accuracy random baseline
    ax.axhspan(random_ci_lower_total, random_ci_upper_total, 
               xmin=0, xmax=0.45, alpha=0.15, color='#e74c3c')
    ax.axhline(y=random_accuracy_total, xmin=0, xmax=0.45, 
               color='#e74c3c', linestyle='--', linewidth=2)
    
    # Per-piece accuracy random baseline
    ax.axhspan(random_ci_lower_total_per_piece, random_ci_upper_total_per_piece, 
               xmin=0.55, xmax=1.0, alpha=0.15, color='#e74c3c')
    ax.axhline(y=random_per_piece_accuracy, xmin=0.55, xmax=1.0, 
               color='#e74c3c', linestyle='--', linewidth=2)
    
    x_positions = [0, 1]
    labels = ['Total\n(Exact Match)', 'Per-Piece\n(Avg)']
    accuracies = [accuracy_total, avg_per_piece_accuracy]
    colors = ['#2ecc71', '#3498db']
    
    bars = ax.bar(x_positions, accuracies, width=0.6, 
                  color=colors, alpha=0.8)
    
    # Add error bars for model accuracies
    ax.errorbar(0, accuracy_total, 
                yerr=[[accuracy_total - ci_lower_total], [ci_upper_total - accuracy_total]], 
                fmt='none', color='black', capsize=10, capthick=2, linewidth=2)
    ax.errorbar(1, avg_per_piece_accuracy, 
                yerr=[[avg_per_piece_accuracy - ci_lower_total_per_piece], [ci_upper_total_per_piece - avg_per_piece_accuracy]], 
                fmt='none', color='black', capsize=10, capthick=2, linewidth=2)
    
    # Styling
    ax.set_ylabel('Accuracy', fontsize=14, fontweight='bold')
    ax.set_title(f'Form Board: Total vs Per-Piece Accuracy\n(n={n_valid}, 95% CI)', 
                 fontsize=16, fontweight='bold', pad=20)
    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylim(0, 1.0)
    ax.grid(axis='y', alpha=0.3)
    
    # Add accuracy text on bars
    for pos, acc in zip(x_positions, accuracies):
        ax.text(pos, acc + 0.04, f'{acc:.3f}', ha='center', 
                fontsize=11, fontweight='bold')
    
    # Add legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='#2ecc71', alpha=0.8, label='Total Model'),
        Patch(facecolor='#3498db', alpha=0.8, label='Per-Piece Model'),
        Patch(facecolor='#e74c3c', alpha=0.3, label='Random Baseline CI'),
        ax.plot([], [], color='#e74c3c', linestyle='--', linewidth=2)[0]
    ]
    legend_elements[-1].set_label('Random Baseline')
    ax.legend(handles=legend_elements, fontsize=11, loc='upper right')
    
    plt.tight_layout()
    accuracy_plot_path = output_dir / f"{base_name}_accuracy.png"
    plt.savefig(accuracy_plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"📊 Saved accuracy plot to: {accuracy_plot_path}")
    
    # ══════════════════════════════════════════════════════════════════════
    # Plot 2: Selection Bias (Prediction vs Ground Truth)
    # ══════════════════════════════════════════════════════════════════════
    fig, ax = plt.subplots(figsize=(12, 6))
    
    x = np.arange(len(all_choices))
    width = 0.35
    
    # Plot selection counts
    pred_counts_list = [prediction_selection_counts[c] for c in all_choices]
    gt_counts_list = [gt_selection_counts[c] for c in all_choices]
    
    bars1 = ax.bar(x - width/2, pred_counts_list, width, label='Model Selections', 
                   color='#3498db', alpha=0.8)
    bars2 = ax.bar(x + width/2, gt_counts_list, width, label='Ground Truth', 
                   color='#95a5a6', alpha=0.6)
    
    # Styling
    ax.set_xlabel('Piece Choice', fontsize=14, fontweight='bold')
    ax.set_ylabel('Selection Count', fontsize=14, fontweight='bold')
    ax.set_title(f'Form Board: Selection Bias: Predicted vs Ground Truth Selections\n(n={n_valid})', 
                 fontsize=16, fontweight='bold', pad=20)
    ax.set_xticks(x)
    ax.set_xticklabels(all_choices, fontsize=12)
    ax.legend(fontsize=11)
    ax.grid(axis='y', alpha=0.3)
    
    # Add count labels and difference indicators
    for i, choice in enumerate(all_choices):
        pred_h = pred_counts_list[i]
        gt_h = gt_counts_list[i]
        diff = pred_h - gt_h
        
        # Prediction count label
        if pred_h > 0:
            ax.text(i - width/2, pred_h, f'{int(pred_h)}',
                   ha='center', va='bottom', fontsize=10)
        
        # GT count label
        if gt_h > 0:
            ax.text(i + width/2, gt_h, f'{int(gt_h)}',
                   ha='center', va='bottom', fontsize=10)
        
        # Difference indicator (above bars)
        if diff != 0:
            sign = "+" if diff > 0 else ""
            color = '#e74c3c' if diff > 0 else '#2ecc71'
            max_h = max(pred_h, gt_h)
            if max(pred_counts_list) > 0:  # Avoid division by zero
                ax.text(i, max_h + max(pred_counts_list) * 0.05, 
                       f'{sign}{diff}',
                       ha='center', va='bottom', fontsize=10, 
                       fontweight='bold', color=color)
    
    plt.tight_layout()
    selection_bias_plot_path = output_dir / f"{base_name}_selection_bias.png"
    plt.savefig(selection_bias_plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"📊 Saved selection bias plot to: {selection_bias_plot_path}")
    
    # ══════════════════════════════════════════════════════════════════════
    # Plot 3: Per-Piece Accuracy Breakdown
    # ══════════════════════════════════════════════════════════════════════
    fig, ax = plt.subplots(figsize=(12, 6))
    
    x = np.arange(len(all_choices))
    width = 0.25
    
    # Extract accuracy, precision, recall for each choice
    accs = [per_piece_accuracy[c] for c in all_choices]
    precs = [per_piece_precision[c] for c in all_choices]
    recs = [per_piece_recall[c] for c in all_choices]
    
    bars1 = ax.bar(x - width, accs, width, label='Accuracy', 
                   color='#9b59b6', alpha=0.8)
    bars2 = ax.bar(x, precs, width, label='Precision', 
                   color='#3498db', alpha=0.8)
    bars3 = ax.bar(x + width, recs, width, label='Recall', 
                   color='#e67e22', alpha=0.8)
    
    # Reference lines
    ax.axhline(y=avg_per_piece_accuracy, color='green', linestyle='--', 
               linewidth=2, alpha=0.7, label=f'Avg Accuracy ({avg_per_piece_accuracy:.3f})')
    ax.axhline(y=random_per_piece_accuracy, color='red', linestyle='--', 
               linewidth=2, alpha=0.7, label=f'Random ({random_per_piece_accuracy:.3f})')
    
    # Styling
    ax.set_xlabel('Piece Choice', fontsize=14, fontweight='bold')
    ax.set_ylabel('Score', fontsize=14, fontweight='bold')
    ax.set_title('Form Board: Per-Piece Performance: Accuracy, Precision, Recall\n' +
                 '(Accuracy = correct select + correct reject; Precision = TP/(TP+FP); Recall = TP/(TP+FN))', 
                 fontsize=14, fontweight='bold', pad=20)
    ax.set_xticks(x)
    ax.set_xticklabels(all_choices, fontsize=12)
    ax.set_ylim(0, 1.0)
    ax.grid(axis='y', alpha=0.3)
    ax.legend(fontsize=10, loc='lower right')
    
    # Add value labels on bars
    for bars, values in [(bars1, accs), (bars2, precs), (bars3, recs)]:
        for bar, val in zip(bars, values):
            if val > 0.05:  # Only show if not too small
                ax.text(bar.get_x() + bar.get_width()/2., val + 0.02,
                       f'{val:.2f}',
                       ha='center', va='bottom', fontsize=8)
    
    plt.tight_layout()
    per_piece_plot_path = output_dir / f"{base_name}_per_piece_breakdown.png"
    plt.savefig(per_piece_plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"📊 Saved per-piece breakdown plot to: {per_piece_plot_path}")
    
    print(f"\n{'='*60}")
    print("✅ Evaluation complete!")
    print(f"{'='*60}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Evaluate model responses for paper-fold benchmark"
    )
    parser.add_argument("--responses", type=str, required=True, 
                       help="Path to the responses JSON file")
    args = parser.parse_args()
    
    evaluate_responses(args.responses)


if __name__ == "__main__":
    main()