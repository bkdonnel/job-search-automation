"""Optimize the job-fit evaluator system prompt using DSPy BootstrapFewShot.

Usage:
    python scripts/optimize_prompt.py [--dataset config/eval_dataset.json] [--trials 20]

Reads the labeled eval dataset, runs DSPy optimization, and writes the best
system prompt to config/optimized_system_prompt.txt. The evaluator will
automatically use it on the next run.

Requires OPENAI_API_KEY in environment or .env file.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

VERDICTS = ["apply", "borderline", "skip"]
OUTPUT_PATH = REPO_ROOT / "config" / "optimized_system_prompt.txt"

JD_MAX_WORDS = 800


def _truncate(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " [truncated]"


def load_dataset(path: Path) -> list[dict]:
    with open(path) as f:
        data = json.load(f)
    jobs = data.get("jobs", [])
    return [j for j in jobs if j.get("ground_truth_verdict") in VERDICTS]


def _build_user_content(job: dict, profile: str) -> str:
    jd = _truncate(job.get("description_text", ""), JD_MAX_WORDS)
    remote = "(Remote)" if job.get("is_remote") else ""
    return (
        f"## Candidate Profile\n{profile}\n\n"
        f"## Job: {job['title']} at {job['company']}\n"
        f"Location: {job['location']} {remote}\n\n"
        f"{jd}"
    )


def run(dataset_path: Path, trials: int) -> None:
    try:
        import dspy
    except ImportError:
        print("dspy-ai not installed. Run: pip install dspy-ai")
        sys.exit(1)

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY not set.")
        sys.exit(1)

    jobs = load_dataset(dataset_path)
    if not jobs:
        print(f"No labeled jobs found in {dataset_path}. Run export_eval_dataset.py first.")
        sys.exit(1)

    print(f"Loaded {len(jobs)} labeled jobs for optimization.")

    profile_path = REPO_ROOT / "config" / "profile.txt"
    profile = profile_path.read_text().strip()

    lm = dspy.OpenAI(model="gpt-4o-mini", max_tokens=256, temperature=0)
    dspy.settings.configure(lm=lm)

    class JobFitSignature(dspy.Signature):
        """Evaluate how well a candidate fits a job opening.

        Return a JSON object with fit_score (1-10), match_reasons (list),
        concerns (list), and verdict ("apply", "borderline", or "skip").
        Rules: apply if score>=7, borderline if score>=5, skip if score<5.
        Return ONLY valid JSON, no markdown fences."""

        candidate_and_job: str = dspy.InputField(desc="Candidate profile and job description")
        evaluation_json: str = dspy.OutputField(desc="JSON with fit_score, match_reasons, concerns, verdict")

    class JobEvaluator(dspy.Module):
        def __init__(self):
            super().__init__()
            self.evaluate = dspy.ChainOfThought(JobFitSignature)

        def forward(self, candidate_and_job: str) -> dspy.Prediction:
            return self.evaluate(candidate_and_job=candidate_and_job)

    def verdict_from_json(raw: str) -> str:
        try:
            data = json.loads(raw)
            score = int(data.get("fit_score", 5))
            if score >= 7:
                return "apply"
            if score >= 5:
                return "borderline"
            return "skip"
        except Exception:
            return "skip"

    def metric(example: dspy.Example, prediction: dspy.Prediction, trace=None) -> float:
        predicted = verdict_from_json(prediction.evaluation_json)
        truth = example.verdict
        if predicted == truth:
            return 1.0
        # False negatives (missing a good job) are penalized more than false positives
        if truth in ("apply", "borderline") and predicted == "skip":
            return 0.0
        return 0.5

    examples = []
    for job in jobs:
        content = _build_user_content(job, profile)
        ex = dspy.Example(
            candidate_and_job=content,
            verdict=job["ground_truth_verdict"],
        ).with_inputs("candidate_and_job")
        examples.append(ex)

    # 80/20 train/val split
    split = max(1, int(len(examples) * 0.8))
    trainset = examples[:split]
    valset = examples[split:]

    print(f"Training on {len(trainset)} examples, validating on {len(valset)}.")
    print("Running BootstrapFewShot optimization...")

    optimizer = dspy.BootstrapFewShot(metric=metric, max_bootstrapped_demos=4, max_labeled_demos=4)
    module = JobEvaluator()
    optimized = optimizer.compile(module, trainset=trainset)

    # Extract the optimized system prompt from the compiled program
    optimized_prompt = None
    try:
        predict = optimized.evaluate
        if hasattr(predict, "extended_signature"):
            optimized_prompt = predict.extended_signature.instructions
        elif hasattr(predict, "signature"):
            optimized_prompt = predict.signature.instructions
    except Exception:
        pass

    if not optimized_prompt:
        # Fall back: grab the last system message DSPy sent
        history = lm.history if hasattr(lm, "history") else []
        for entry in reversed(history):
            msgs = entry.get("messages", [])
            for msg in msgs:
                if msg.get("role") == "system":
                    optimized_prompt = msg["content"]
                    break
            if optimized_prompt:
                break

    if not optimized_prompt:
        print("Could not extract optimized prompt. No changes written.")
        sys.exit(1)

    # Append the scoring rules so the normalisation in evaluator.py never breaks
    rules_block = (
        "\n\nRules:\n"
        "- \"apply\" if fit_score >= 7\n"
        "- \"borderline\" if fit_score >= 5\n"
        "- \"skip\" if fit_score < 5\n"
        "Return ONLY valid JSON, no markdown fences."
    )
    if "Return ONLY valid JSON" not in optimized_prompt:
        optimized_prompt += rules_block

    OUTPUT_PATH.write_text(optimized_prompt)
    print(f"\nOptimized prompt written to {OUTPUT_PATH}")
    print("-" * 60)
    print(optimized_prompt[:500])
    if len(optimized_prompt) > 500:
        print(f"... ({len(optimized_prompt)} chars total)")

    if valset:
        print("\nValidating optimized module on held-out set...")
        correct = 0
        for ex in valset:
            try:
                pred = optimized(candidate_and_job=ex.candidate_and_job)
                if verdict_from_json(pred.evaluation_json) == ex.verdict:
                    correct += 1
            except Exception:
                pass
        print(f"Validation accuracy: {correct}/{len(valset)} = {correct/len(valset):.1%}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Optimize evaluator system prompt with DSPy.")
    parser.add_argument("--dataset", type=Path, default=REPO_ROOT / "config" / "eval_dataset.json")
    parser.add_argument("--trials", type=int, default=20, help="Max optimization trials (unused by BootstrapFewShot, reserved for MIPROv2)")
    args = parser.parse_args()

    if not args.dataset.exists():
        print(f"Dataset not found: {args.dataset}")
        print("Run: python scripts/export_eval_dataset.py")
        sys.exit(1)

    run(args.dataset, args.trials)
