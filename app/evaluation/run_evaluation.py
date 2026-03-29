"""Run the evidence-based bias pipeline on a labeled dataset."""

from __future__ import annotations

import argparse
from collections import Counter
from typing import Any

from app.analysis.bias_detector import analyze_bias
from app.evaluation.dataset_loader import load_dataset


def _label_from_scores(scores: dict[str, Any]) -> str:
    factual = float(scores.get("factual_accuracy", 0.0))
    narrative = float(scores.get("narrative_bias", 0.0))
    completeness = float(scores.get("completeness", 0.0))

    if factual >= 0.7 and narrative <= 0.35 and completeness >= 0.55:
        return "low_bias"
    if narrative >= 0.65 or factual <= 0.4:
        return "high_bias"
    return "mixed"


def _claim_consistency(result_a: dict[str, Any], result_b: dict[str, Any]) -> float:
    claims_a = {item["claim"]: item["stance"] for item in result_a.get("claim_analysis", [])}
    claims_b = {item["claim"]: item["stance"] for item in result_b.get("claim_analysis", [])}
    shared = set(claims_a) & set(claims_b)
    if not shared:
        return 0.0
    matches = sum(1 for claim in shared if claims_a[claim] == claims_b[claim])
    return matches / len(shared)


def evaluate_dataset(dataset_path: str, retrieval_base_dir: str) -> dict[str, Any]:
    """Evaluate the pipeline on a dataset and return aggregate metrics."""
    dataset = load_dataset(dataset_path)
    total = len(dataset)
    if total == 0:
        raise ValueError("Dataset is empty.")

    correct = 0
    consistency_scores: list[float] = []
    predictions = Counter()

    for item in dataset:
        first_run = analyze_bias(item["article_text"], retrieval_base_dir=retrieval_base_dir)
        second_run = analyze_bias(item["article_text"], retrieval_base_dir=retrieval_base_dir)
        predicted_label = _label_from_scores(first_run.get("scores", {}))
        predictions[predicted_label] += 1

        expected_label = item["expected_bias_label"]
        if expected_label and predicted_label == expected_label:
            correct += 1

        consistency_scores.append(_claim_consistency(first_run, second_run))

    accuracy = correct / total if total else 0.0
    consistency = sum(consistency_scores) / len(consistency_scores) if consistency_scores else 0.0
    return {
        "articles_evaluated": total,
        "accuracy": round(accuracy, 4),
        "consistency": round(consistency, 4),
        "prediction_distribution": dict(predictions),
    }


def main() -> None:
    """Parse CLI arguments and print evaluation metrics."""
    parser = argparse.ArgumentParser(description="Evaluate the evidence-based news bias analyzer.")
    parser.add_argument("dataset", help="Path to the labeled JSON dataset.")
    parser.add_argument(
        "--retrieval-base-dir",
        default="app/embeddings/vector_index",
        help="Directory containing the FAISS site indexes.",
    )
    args = parser.parse_args()

    metrics = evaluate_dataset(args.dataset, args.retrieval_base_dir)
    print("Evaluation Metrics")
    print("==================")
    print(f"Articles Evaluated: {metrics['articles_evaluated']}")
    print(f"Accuracy: {metrics['accuracy']:.4f}")
    print(f"Consistency: {metrics['consistency']:.4f}")
    print(f"Prediction Distribution: {metrics['prediction_distribution']}")


if __name__ == "__main__":
    main()
