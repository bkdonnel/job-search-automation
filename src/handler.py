"""Lambda entry point."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import boto3
import yaml

from .boards.greenhouse import GreenhouseClient
from .boards.lever import LeverClient
from .boards.ashby import AshbyClient
from .database import is_seen, save_job, update_stage, save_evaluation
from .embedder import score_job
from .evaluator import evaluate
from . import evaluator
from .filter import keyword_filter
from .models import Job
from .notifier import notify
from .reranker import rerank_candidates
from .tracer import save_trace
from . import cost_tracker

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_CLIENTS = {
    "greenhouse": GreenhouseClient,
    "lever": LeverClient,
    "ashby": AshbyClient,
}

EMBEDDING_THRESHOLD = 0.35

_secrets_loaded = False


def _load_secrets() -> None:
    """Fetch secrets from SSM and inject into environment (once per cold start)."""
    global _secrets_loaded
    if _secrets_loaded:
        return

    ssm = boto3.client("ssm")
    param_map = {
        "/jobsearch/openai_key": "OPENAI_API_KEY",
        "/jobsearch/slack_webhook": "SLACK_WEBHOOK_URL",
    }
    for param_name, env_var in param_map.items():
        if os.environ.get(env_var):
            continue  # already set (e.g. local testing)
        try:
            resp = ssm.get_parameter(Name=param_name, WithDecryption=True)
            os.environ[env_var] = resp["Parameter"]["Value"]
        except Exception as exc:
            logger.error("Failed to load SSM param %s: %s", param_name, exc)
            raise

    _secrets_loaded = True


def _load_companies() -> list[dict]:
    config_path = Path(__file__).parent.parent / "config" / "companies.yaml"
    with open(config_path) as f:
        data = yaml.safe_load(f)
    return data.get("companies", [])


def main(event: dict[str, Any], context: Any) -> dict[str, Any]:
    cost_tracker.reset()
    _load_secrets()
    companies = _load_companies()

    total_fetched = 0
    total_new = 0
    total_evaluated = 0
    total_notified = 0

    # Phase 1: fetch, dedup, keyword filter, and embed across all companies
    embedding_candidates: list[tuple[Job, float, list[float] | None]] = []

    for company in companies:
        name = company["name"]
        board_type = company["board_type"]
        board_token = company["board_token"]

        try:
            client_cls = _CLIENTS[board_type]
            client = client_cls(company_name=name, board_token=board_token)
            jobs = client.fetch_jobs()
            total_fetched += len(jobs)
            logger.info("Fetched %d jobs from %s (%s)", len(jobs), name, board_type)
        except Exception as exc:
            logger.error("Error fetching jobs for %s: %s", name, exc)
            continue

        new_jobs: list[Job] = []
        for job in jobs:
            if not is_seen(job.job_id):
                save_job(job)
                new_jobs.append(job)

        total_new += len(new_jobs)
        logger.info("%d new jobs for %s", len(new_jobs), name)

        if not new_jobs:
            continue

        keyword_candidates = keyword_filter(new_jobs)
        logger.info("%d/%d passed keyword filter for %s", len(keyword_candidates), len(new_jobs), name)

        for job in new_jobs:
            if job not in keyword_candidates:
                update_stage(job.job_id, "keyword_fail")

        for job in keyword_candidates:
            update_stage(job.job_id, "keyword_pass")
            try:
                sim, job_embedding = score_job(job.description_text)
                logger.info("Embedding score for '%s' @ %s: %.3f", job.title, job.company, sim)
            except Exception as exc:
                logger.warning("Embedding failed for %s, falling through to AI: %s", job.job_id, exc)
                sim, job_embedding = 1.0, None

            if sim < EMBEDDING_THRESHOLD:
                update_stage(job.job_id, "embedding_fail")
                logger.info("Skipping '%s' @ %s - embedding %.3f below threshold", job.title, job.company, sim)
                continue

            embedding_candidates.append((job, sim, job_embedding))

    # Phase 2: rerank if we have more candidates than the configured top_n
    final_candidates, reranked_out = rerank_candidates(embedding_candidates)

    for job in reranked_out:
        update_stage(job.job_id, "rerank_fail")
        logger.info("Reranked out '%s' @ %s", job.title, job.company)

    if reranked_out:
        logger.info(
            "Reranking: kept %d/%d candidates for evaluation",
            len(final_candidates), len(embedding_candidates),
        )

    # Phase 3: evaluate final candidates
    for job, sim, job_embedding in final_candidates:
        try:
            result, usage = evaluate(job)
            total_evaluated += 1
            logger.info(
                "Evaluated '%s' @ %s: score=%d verdict=%s",
                job.title, job.company, result.fit_score, result.verdict,
            )
        except Exception as exc:
            logger.error("Error evaluating job %s: %s", job.job_id, exc)
            continue

        try:
            save_trace(job, result, usage, evaluator.MODEL, sim)
        except Exception as exc:
            logger.warning("Failed to save trace for %s: %s", job.job_id, exc)

        if result.verdict in ("apply", "borderline"):
            try:
                notify(job, result)
                total_notified += 1
                logger.info("Notified for %s @ %s", job.title, job.company)
            except Exception as exc:
                logger.error("Error sending Slack notification for %s: %s", job.job_id, exc)

        save_evaluation(job, result, sim, job_embedding)

    summary = {
        "fetched": total_fetched,
        "new": total_new,
        "evaluated": total_evaluated,
        "notified": total_notified,
    }
    logger.info("Run complete: %s", summary)
    cost_tracker.log_summary(logger)
    return summary
