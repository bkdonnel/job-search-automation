"""Writes one evaluation trace record to DynamoDB per AI evaluation."""
from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone

import boto3

from .models import Job, AIEvaluation
from . import cost_tracker

TRACE_TABLE_NAME = os.environ.get("EVALUATIONS_TABLE", "evaluations")
TTL_DAYS = 90

_table = None


def _get_table():
    global _table
    if _table is None:
        _table = boto3.resource("dynamodb").Table(TRACE_TABLE_NAME)
    return _table


def save_trace(
    job: Job,
    evaluation: AIEvaluation,
    usage: object,
    model: str,
    embedding_score: float | None = None,
) -> None:
    """Persist a full evaluation record to the evaluations table."""
    input_tokens = getattr(usage, "prompt_tokens", 0)
    output_tokens = getattr(usage, "completion_tokens", 0)
    cost_usd = cost_tracker.estimate_cost(model, input_tokens, output_tokens)

    ttl_epoch = int(time.time()) + TTL_DAYS * 86400

    _get_table().put_item(Item={
        "eval_id": str(uuid.uuid4()),
        "job_id": job.job_id,
        "company": job.company,
        "title": job.title,
        "evaluated_at": datetime.now(tz=timezone.utc).isoformat(),
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": str(round(cost_usd, 6)),
        "embedding_score": str(round(embedding_score, 4)) if embedding_score is not None else None,
        "fit_score": evaluation.fit_score,
        "verdict": evaluation.verdict,
        "match_reasons": evaluation.match_reasons,
        "concerns": evaluation.concerns,
        "ttl": ttl_epoch,
    })
