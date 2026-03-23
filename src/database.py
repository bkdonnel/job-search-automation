from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

from .models import Job, AIEvaluation

TABLE_NAME = os.environ.get("DYNAMODB_TABLE", "jobs")
TTL_DAYS = 90

_table = None


def _get_table():
    global _table
    if _table is None:
        dynamodb = boto3.resource("dynamodb")
        _table = dynamodb.Table(TABLE_NAME)
    return _table


def is_seen(job_id: str) -> bool:
    """Return True if this job_id already exists in DynamoDB."""
    table = _get_table()
    resp = table.get_item(Key={"job_id": job_id}, ProjectionExpression="job_id")
    return "Item" in resp


def save_job(job: Job) -> None:
    """Insert a new job record at stage='seen'."""
    table = _get_table()
    ttl_epoch = int(time.time()) + TTL_DAYS * 86400
    now = datetime.now(tz=timezone.utc).isoformat()
    table.put_item(Item={
        "job_id": job.job_id,
        "board": job.board,
        "company": job.company,
        "title": job.title,
        "location": job.location,
        "url": job.url,
        "first_seen_at": now,
        "stage": "seen",
        "ttl": ttl_epoch,
    })


def update_stage(job_id: str, stage: str) -> None:
    table = _get_table()
    table.update_item(
        Key={"job_id": job_id},
        UpdateExpression="SET stage = :s",
        ExpressionAttributeValues={":s": stage},
    )


def save_evaluation(job: Job, evaluation: AIEvaluation) -> None:
    """Update the job record with AI evaluation results."""
    table = _get_table()
    now = datetime.now(tz=timezone.utc).isoformat()

    stage = "notified" if evaluation.verdict in ("apply", "borderline") else "skipped"

    update_expr = (
        "SET stage = :stage, "
        "ai_score = :score, "
        "ai_verdict = :verdict, "
        "ai_reasons = :reasons, "
        "ai_concerns = :concerns, "
        "notified_at = :notified_at"
    )
    expr_values = {
        ":stage": stage,
        ":score": evaluation.fit_score,
        ":verdict": evaluation.verdict,
        ":reasons": evaluation.match_reasons,
        ":concerns": evaluation.concerns,
        ":notified_at": now if stage == "notified" else None,
    }
    table.update_item(
        Key={"job_id": job.job_id},
        UpdateExpression=update_expr,
        ExpressionAttributeValues=expr_values,
    )
