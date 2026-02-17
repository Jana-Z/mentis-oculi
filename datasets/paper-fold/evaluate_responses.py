# Load json from the given path
# Answer is already extracted from the response in the 'output_parsed' key
# Compare the answer with the ground truth answer
# Compute the accuracy
# Save the metrics to a new json file (in the same directory as the responses file)
# The metrics should include the accuracy
# Also plot the accuracy with CI and the CI around the random performance (1 out of 5 chance)

import json
import argparse
import os
import sys
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np
from collections import Counter

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
    predictions = []
    ground_truth = []
    valid_responses = []
    
    for r in responses:
        try:
            pred = r.get("output_parsed", {}).get("answer")
            gt = r.get("metadata", {}).get("correct_choice")
            
            if pred and gt:
                predictions.append(pred)
                ground_truth.append(gt)
                valid_responses.append(r)
        except:
            continue
    
    n_valid = len(predictions)
    n_invalid = n - n_valid
    
    if n_invalid > 0:
        print(f"⚠️  Warning: {n_invalid} responses could not be parsed")
    
    # Compute accuracy
    # Track per-response correctness for pass@k evaluation
    per_response_correct = [p == g for p, g in zip(predictions, ground_truth)]
    correct = sum(per_response_correct)
    accuracy = correct / n_valid if n_valid > 0 else 0.0
    
    # Compute confidence intervals
    ci_lower, ci_upper = compute_confidence_interval(accuracy, n_valid)
    random_accuracy = 0.2  # 1 out of 5
    random_ci_lower, random_ci_upper = compute_confidence_interval(random_accuracy, n_valid)
    
    # Count prediction distribution
    prediction_counts = Counter(predictions)
    all_choices = ['A', 'B', 'C', 'D', 'E']
    prediction_distribution = {choice: prediction_counts.get(choice, 0) for choice in all_choices}
    
    # Count ground truth distribution (for reference)
    gt_counts = Counter(ground_truth)
    gt_distribution = {choice: gt_counts.get(choice, 0) for choice in all_choices}
    
    # Print metrics
    print(f"📊 Results:")
    print(f"   Accuracy: {accuracy:.3f} ({correct}/{n_valid})")
    print(f"   95% CI: [{ci_lower:.3f}, {ci_upper:.3f}]")
    print(f"   Random baseline: {random_accuracy:.3f}")
    print(f"   Random 95% CI: [{random_ci_lower:.3f}, {random_ci_upper:.3f}]")
    print(f"\n📈 Prediction Distribution:")
    for choice in all_choices:
        count = prediction_distribution[choice]
        pct = count / n_valid * 100 if n_valid > 0 else 0
        print(f"   {choice}: {count:3d} ({pct:5.1f}%)")
    
    # Prepare output directory
    output_dir = Path(responses_path).parent
    base_name = Path(responses_path).stem
    
    # Save metrics to JSON
    metrics = {
        "total_responses": n,
        "valid_responses": n_valid,
        "invalid_responses": n_invalid,
        "accuracy": accuracy,
        "correct_count": correct,
        "confidence_interval_95": {
            "lower": ci_lower,
            "upper": ci_upper
        },
        "random_baseline": {
            "accuracy": random_accuracy,
            "confidence_interval_95": {
                "lower": random_ci_lower,
                "upper": random_ci_upper
            }
        },
        "prediction_distribution": prediction_distribution,
        "ground_truth_distribution": gt_distribution,
        # Per-response correctness for pass@k evaluation
        "per_response_correct": {
            r.get("puzzle_id", i): correct 
            for i, (r, correct) in enumerate(zip(valid_responses, per_response_correct))
        }
    }
    
    metrics_path = output_dir / f"{base_name}_metrics.json"
    with open(metrics_path, 'w') as f:
        json.dump(metrics, f, indent=2)
    
    print(f"\n💾 Saved metrics to: {metrics_path}")
    
    # ── Plot 1: Accuracy with Confidence Intervals ──────────────────────────
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Plot random baseline as colored box (CI region) in background
    ax.axhspan(random_ci_lower, random_ci_upper, alpha=0.2, color='#e74c3c', 
               label='Random Baseline 95% CI (1/5)')
    ax.axhline(y=random_accuracy, color='#e74c3c', linestyle='--', linewidth=2, 
               label=f'Random Baseline ({random_accuracy:.3f})')
    
    model_name = Path(responses_path).parts[-3]

    # Plot model accuracy
    ax.bar(0, accuracy, width=0.6, label=f'{model_name.capitalize()} Accuracy', color='#2ecc71', alpha=0.8)
    ax.errorbar(0, accuracy, yerr=[[accuracy - ci_lower], [ci_upper - accuracy]], 
                fmt='none', color='black', capsize=10, capthick=2, linewidth=2)
    
    # Styling
    ax.set_ylabel('Accuracy', fontsize=14, fontweight='bold')
    ax.set_title(f'Paper Fold: Model Performance vs Random Baseline\n(n={n_valid}, 95% CI)', 
                 fontsize=16, fontweight='bold', pad=20)
    ax.set_xticks([0])
    ax.set_xticklabels([model_name.capitalize()], fontsize=12)
    ax.set_xlim(-0.5, 0.5)
    ax.set_ylim(0, 1.0)
    ax.grid(axis='y', alpha=0.3)
    ax.legend(fontsize=11, loc='upper right')
    
    # Add accuracy text on bar
    ax.text(0, accuracy + 0.05, f'{accuracy:.3f}', ha='center', fontsize=12, fontweight='bold')
    
    plt.tight_layout()
    accuracy_plot_path = output_dir / f"{base_name}_accuracy.png"
    plt.savefig(accuracy_plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"📊 Saved accuracy plot to: {accuracy_plot_path}")
    
    # ── Plot 2: Prediction Distribution (Answer Bias) ──────────────────────
    fig, ax = plt.subplots(figsize=(12, 6))
    
    x = np.arange(len(all_choices))
    width = 0.35
    
    # Plot predicted distribution
    pred_counts = [prediction_distribution[c] for c in all_choices]
    gt_counts_list = [gt_distribution[c] for c in all_choices]
    
    bars1 = ax.bar(x - width/2, pred_counts, width, label='Model Predictions', 
                   color='#3498db', alpha=0.8)
    bars2 = ax.bar(x + width/2, gt_counts_list, width, label='Ground Truth', 
                   color='#95a5a6', alpha=0.6)
    
    # Add uniform distribution reference line
    uniform_count = n_valid / 5
    ax.axhline(y=uniform_count, color='red', linestyle='--', alpha=0.5, 
               linewidth=2, label=f'Uniform ({uniform_count:.1f})')
    
    # Styling
    ax.set_xlabel('Answer Choice', fontsize=14, fontweight='bold')
    ax.set_ylabel('Count', fontsize=14, fontweight='bold')
    ax.set_title(f'Paper Fold: Prediction Distribution: Answer Bias Analysis\n(n={n_valid})', 
                 fontsize=16, fontweight='bold', pad=20)
    ax.set_xticks(x)
    ax.set_xticklabels(all_choices, fontsize=12)
    ax.legend(fontsize=11)
    ax.grid(axis='y', alpha=0.3)
    
    # Add count labels on bars
    for bars in [bars1, bars2]:
        for bar in bars:
            height = bar.get_height()
            if height > 0:
                ax.text(bar.get_x() + bar.get_width()/2., height,
                       f'{int(height)}',
                       ha='center', va='bottom', fontsize=10)
    
    plt.tight_layout()
    distribution_plot_path = output_dir / f"{base_name}_distribution.png"
    plt.savefig(distribution_plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"📊 Saved distribution plot to: {distribution_plot_path}")
    
    # ── Plot 3: Per-Choice Accuracy (Bonus) ──────────────────────────────
    # This shows if the model is better at predicting certain answer positions
    fig, ax = plt.subplots(figsize=(10, 6))
    
    per_choice_accuracy = {}
    for choice in all_choices:
        # For each choice, compute accuracy when ground truth is that choice
        gt_mask = [g == choice for g in ground_truth]
        if sum(gt_mask) > 0:
            correct_for_choice = sum(1 for p, g, mask in zip(predictions, ground_truth, gt_mask) 
                                    if mask and p == g)
            per_choice_accuracy[choice] = correct_for_choice / sum(gt_mask)
        else:
            per_choice_accuracy[choice] = 0.0
    
    choices = list(per_choice_accuracy.keys())
    accuracies = list(per_choice_accuracy.values())
    
    bars = ax.bar(choices, accuracies, color='#9b59b6', alpha=0.8)
    ax.axhline(y=accuracy, color='green', linestyle='--', linewidth=2, 
               label=f'Overall Accuracy ({accuracy:.3f})')
    ax.axhline(y=random_accuracy, color='red', linestyle='--', linewidth=2, 
               label=f'Random Baseline ({random_accuracy:.3f})')
    
    ax.set_xlabel('Ground Truth Answer', fontsize=14, fontweight='bold')
    ax.set_ylabel('Accuracy', fontsize=14, fontweight='bold')
    ax.set_title('Paper Fold: Per-Answer Accuracy: Position Bias Analysis', 
                 fontsize=16, fontweight='bold', pad=20)
    ax.set_ylim(0, 1.0)
    ax.grid(axis='y', alpha=0.3)
    ax.legend(fontsize=11)
    
    # Add accuracy labels
    for bar, acc in zip(bars, accuracies):
        if acc > 0:
            ax.text(bar.get_x() + bar.get_width()/2., acc + 0.03,
                   f'{acc:.3f}',
                   ha='center', va='bottom', fontsize=11, fontweight='bold')
    
    plt.tight_layout()
    per_choice_plot_path = output_dir / f"{base_name}_per_choice_accuracy.png"
    plt.savefig(per_choice_plot_path, dpi=300, bbox_inches='tight')
    plt.close()
    
    print(f"📊 Saved per-choice accuracy plot to: {per_choice_plot_path}")
    
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