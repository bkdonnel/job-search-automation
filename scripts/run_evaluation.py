"""Run the evaluator against the labeled dataset and report accuracy.

Usage:
    python scripts/run_evaluation.py [--dataset config/eval_dataset.json]

Requires OPENAI_API_KEY in environment or .env file.
Saves a timestamped JSON report to eval_reports/.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.models import Job, AIEvaluation
from src.evaluator import evaluate


VERDICTS = ["apply", "borderline", "skip"]
POSITIVE = {"apply", "borderline"}  # verdicts that trigger a notification


def load_dataset(path: Path) -> list[dict]:
    with open(path) as f:
        data = json.load(f)
    jobs = data.get("jobs", [])
    labeled = [j for j in jobs if j.get("ground_truth_verdict") in VERDICTS]
    if len(labeled) < len(jobs):
        print(f"  Skipping {len(jobs) - len(labeled)} jobs with missing/invalid ground_truth_verdict")
    return labeled


def run_evaluations(jobs: list[dict]) -> list[dict]:
    results = []
    for i, job_data in enumerate(jobs, 1):
        job = Job(
            job_id=job_data["job_id"],
            board=job_data.get("board", "greenhouse"),
            company=job_data["company"],
            company_token=job_data.get("company_token", ""),
            title=job_data["title"],
            location=job_data["location"],
            is_remote=job_data.get("is_remote", False),
            url=job_data.get("url", ""),
            description_text=job_data["description_text"],
        )
        ground_truth = job_data["ground_truth_verdict"]

        try:
            evaluation, usage = evaluate(job)
            predicted = evaluation.verdict
            correct = predicted == ground_truth
            print(
                f"[{i:>3}/{len(jobs)}] {job.company:20s} | {job.title[:30]:30s} | "
                f"truth={ground_truth:10s} predicted={predicted:10s} score={evaluation.fit_score} "
                f"{'OK' if correct else 'WRONG'}"
            )
            results.append({
                "job_id": job.job_id,
                "company": job.company,
                "title": job.title,
                "ground_truth": ground_truth,
                "predicted_verdict": predicted,
                "predicted_score": evaluation.fit_score,
                "correct": correct,
                "match_reasons": evaluation.match_reasons,
                "concerns": evaluation.concerns,
            })
        except Exception as exc:
            print(f"[{i:>3}/{len(jobs)}] ERROR evaluating {job.job_id}: {exc}")
            results.append({
                "job_id": job.job_id,
                "company": job.company,
                "title": job.title,
                "ground_truth": ground_truth,
                "predicted_verdict": None,
                "predicted_score": None,
                "correct": False,
                "error": str(exc),
            })

    return results


def compute_metrics(results: list[dict]) -> dict:
    evaluated = [r for r in results if r.get("predicted_verdict")]
    if not evaluated:
        return {}

    total = len(evaluated)
    correct = sum(1 for r in evaluated if r["correct"])

    # Per-verdict precision and recall
    verdict_metrics = {}
    for v in VERDICTS:
        tp = sum(1 for r in evaluated if r["ground_truth"] == v and r["predicted_verdict"] == v)
        fp = sum(1 for r in evaluated if r["ground_truth"] != v and r["predicted_verdict"] == v)
        fn = sum(1 for r in evaluated if r["ground_truth"] == v and r["predicted_verdict"] != v)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        verdict_metrics[v] = {"precision": round(precision, 3), "recall": round(recall, 3), "tp": tp, "fp": fp, "fn": fn}

    # False negative rate: good jobs (apply/borderline) predicted as skip
    good_jobs = [r for r in evaluated if r["ground_truth"] in POSITIVE]
    false_negatives = [r for r in good_jobs if r["predicted_verdict"] == "skip"]
    fnr = len(false_negatives) / len(good_jobs) if good_jobs else 0.0

    # False positive rate: skip jobs predicted as apply/borderline
    skip_jobs = [r for r in evaluated if r["ground_truth"] == "skip"]
    false_positives = [r for r in skip_jobs if r["predicted_verdict"] in POSITIVE]
    fpr = len(false_positives) / len(skip_jobs) if skip_jobs else 0.0

    # Threshold sensitivity: what accuracy would we get at different thresholds?
    threshold_sensitivity = {}
    for apply_thresh in [6, 7, 8]:
        for borderline_thresh in [4, 5, 6]:
            if borderline_thresh >= apply_thresh:
                continue
            key = f"apply>={apply_thresh}_borderline>={borderline_thresh}"
            hits = 0
            for r in evaluated:
                score = r.get("predicted_score")
                if score is None:
                    continue
                if score >= apply_thresh:
                    pred = "apply"
                elif score >= borderline_thresh:
                    pred = "borderline"
                else:
                    pred = "skip"
                if pred == r["ground_truth"]:
                    hits += 1
            threshold_sensitivity[key] = round(hits / total, 3)

    return {
        "total": total,
        "correct": correct,
        "accuracy": round(correct / total, 3),
        "false_negative_rate": round(fnr, 3),
        "false_positive_rate": round(fpr, 3),
        "missed_good_jobs": len(false_negatives),
        "false_alarms": len(false_positives),
        "per_verdict": verdict_metrics,
        "threshold_sensitivity": threshold_sensitivity,
    }


def print_report(metrics: dict, results: list[dict]) -> None:
    print("\n" + "=" * 70)
    print("EVALUATION REPORT")
    print("=" * 70)
    print(f"  Total evaluated:      {metrics['total']}")
    print(f"  Correct:              {metrics['correct']}")
    print(f"  Accuracy:             {metrics['accuracy']:.1%}")
    print(f"  False negative rate:  {metrics['false_negative_rate']:.1%}  (good jobs predicted skip)")
    print(f"  False positive rate:  {metrics['false_positive_rate']:.1%}  (skip jobs surfaced)")
    print(f"  Missed good jobs:     {metrics['missed_good_jobs']}")
    print(f"  False alarms:         {metrics['false_alarms']}")

    print("\n" + "-" * 70)
    print("PER-VERDICT METRICS")
    print("-" * 70)
    print(f"  {'Verdict':12s} {'Precision':>10s} {'Recall':>10s} {'TP':>6s} {'FP':>6s} {'FN':>6s}")
    for v, m in metrics["per_verdict"].items():
        print(f"  {v:12s} {m['precision']:>10.1%} {m['recall']:>10.1%} {m['tp']:>6d} {m['fp']:>6d} {m['fn']:>6d}")

    print("\n" + "-" * 70)
    print("THRESHOLD SENSITIVITY  (current: apply>=7, borderline>=5)")
    print("-" * 70)
    current = metrics["threshold_sensitivity"].get("apply>=7_borderline>=5", "N/A")
    for key, acc in sorted(metrics["threshold_sensitivity"].items(), key=lambda x: -x[1]):
        marker = " <-- current" if key == "apply>=7_borderline>=5" else ""
        print(f"  {key:40s} {acc:.1%}{marker}")

    print("\n" + "-" * 70)
    print("WRONG PREDICTIONS")
    print("-" * 70)
    wrong = [r for r in results if not r.get("correct") and r.get("predicted_verdict")]
    if wrong:
        for r in wrong:
            print(f"  {r['company']:20s} | {r['title'][:35]:35s} | truth={r['ground_truth']} predicted={r['predicted_verdict']} score={r.get('predicted_score')}")
    else:
        print("  None — perfect accuracy!")

    print("=" * 70)


def save_report(metrics: dict, results: list[dict], output_dir: Path) -> Path:
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"eval_report_{timestamp}.json"
    with open(path, "w") as f:
        json.dump({"metrics": metrics, "results": results, "generated_at": datetime.now(tz=timezone.utc).isoformat()}, f, indent=2)
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run evaluator against labeled dataset.")
    parser.add_argument("--dataset", type=Path, default=REPO_ROOT / "config" / "eval_dataset.json")
    args = parser.parse_args()

    if not args.dataset.exists():
        print(f"Dataset not found: {args.dataset}")
        print("Run: python scripts/export_eval_dataset.py")
        sys.exit(1)

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set. Add it to .env or export it.")
        sys.exit(1)

    print(f"Loading dataset from {args.dataset}...")
    jobs = load_dataset(args.dataset)
    print(f"  {len(jobs)} labeled jobs to evaluate\n")

    print("Running evaluations (this will make OpenAI API calls)...")
    results = run_evaluations(jobs)

    metrics = compute_metrics(results)
    print_report(metrics, results)

    report_path = save_report(metrics, results, REPO_ROOT / "eval_reports")
    print(f"\nReport saved to {report_path}")
    print(f"Estimated cost: ~${len(jobs) * 0.0002:.4f}")
