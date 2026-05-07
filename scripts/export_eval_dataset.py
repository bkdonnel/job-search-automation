"""Export past job evaluations from DynamoDB for manual labeling.

Usage:
    python scripts/export_eval_dataset.py [--limit 100]

Exports jobs that have both description_text and ai_verdict set.
Review the output file and correct any wrong ground_truth_verdict values,
then run scripts/run_evaluation.py to measure evaluator accuracy.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Attr
from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).parent.parent
OUTPUT_PATH = REPO_ROOT / "config" / "eval_dataset.json"
TABLE_NAME = os.environ.get("DYNAMODB_TABLE", "jobs")
REGION = "us-east-1"


def export(limit: int) -> None:
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)

    print(f"Scanning {TABLE_NAME} for evaluated jobs with description_text...")

    items: list = []
    resp = table.scan(
        FilterExpression=Attr("ai_verdict").exists() & Attr("description_text").exists(),
        ProjectionExpression=(
            "job_id, board, company, company_token, title, #loc, is_remote, "
            "#u, description_text, first_seen_at, ai_verdict, ai_score, "
            "ai_reasons, ai_concerns, embedding_score"
        ),
        ExpressionAttributeNames={"#u": "url", "#loc": "location"},
    )
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp:
        resp = table.scan(
            ExclusiveStartKey=resp["LastEvaluatedKey"],
            FilterExpression=Attr("ai_verdict").exists() & Attr("description_text").exists(),
            ProjectionExpression=(
                "job_id, board, company, company_token, title, #loc, is_remote, "
                "#u, description_text, first_seen_at, ai_verdict, ai_score, "
                "ai_reasons, ai_concerns, embedding_score"
            ),
            ExpressionAttributeNames={"#u": "url", "#loc": "location"},
        )
        items.extend(resp.get("Items", []))

    if not items:
        print(
            "No evaluated jobs with description_text found.\n"
            "Jobs need description_text populated (available after recent pipeline runs) "
            "and an ai_verdict (must have passed keyword + embedding filters)."
        )
        sys.exit(1)

    items.sort(key=lambda x: x.get("first_seen_at", ""), reverse=True)
    items = items[:limit]

    jobs = []
    for item in items:
        jobs.append({
            "job_id": item.get("job_id", ""),
            "board": item.get("board", "greenhouse"),
            "company": item.get("company", ""),
            "company_token": item.get("company_token", ""),
            "title": item.get("title", ""),
            "location": item.get("location", ""),
            "is_remote": item.get("is_remote", False),
            "url": item.get("url", ""),
            "description_text": item.get("description_text", ""),
            "first_seen_at": item.get("first_seen_at", ""),
            "original_score": int(item.get("ai_score", 0)),
            "original_verdict": item.get("ai_verdict", ""),
            "original_reasons": item.get("ai_reasons", []),
            "original_concerns": item.get("ai_concerns", []),
            "embedding_score": item.get("embedding_score", ""),
            # Set ground_truth_verdict to the original verdict by default.
            # Correct this field manually where you disagree with the AI.
            "ground_truth_verdict": item.get("ai_verdict", ""),
        })

    dataset = {
        "version": "1.0",
        "exported_at": datetime.now(tz=timezone.utc).isoformat(),
        "total": len(jobs),
        "instructions": (
            "Review each job below. Where the original_verdict is wrong, "
            "update ground_truth_verdict to your manual assessment "
            "(apply / borderline / skip). Then run: python scripts/run_evaluation.py"
        ),
        "jobs": jobs,
    }

    with open(OUTPUT_PATH, "w") as f:
        json.dump(dataset, f, indent=2, default=str)

    print(f"Exported {len(jobs)} jobs to {OUTPUT_PATH}")
    print(
        f"  apply:     {sum(1 for j in jobs if j['original_verdict'] == 'apply')}\n"
        f"  borderline:{sum(1 for j in jobs if j['original_verdict'] == 'borderline')}\n"
        f"  skip:      {sum(1 for j in jobs if j['original_verdict'] == 'skip')}\n"
    )
    print("Next step: open config/eval_dataset.json, correct any wrong ground_truth_verdict values,")
    print("then run: python scripts/run_evaluation.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export evaluated jobs for manual labeling.")
    parser.add_argument("--limit", type=int, default=100, help="Max jobs to export (default 100)")
    args = parser.parse_args()
    export(args.limit)
