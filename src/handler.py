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
from .evaluator import evaluate
from .filter import keyword_filter
from .models import Job
from .notifier import notify

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_CLIENTS = {
    "greenhouse": GreenhouseClient,
    "lever": LeverClient,
    "ashby": AshbyClient,
}

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
    _load_secrets()
    companies = _load_companies()

    total_fetched = 0
    total_new = 0
    total_evaluated = 0
    total_notified = 0

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

        # Dedup: keep only jobs we haven't seen before
        new_jobs: list[Job] = []
        for job in jobs:
            if not is_seen(job.job_id):
                save_job(job)
                new_jobs.append(job)

        total_new += len(new_jobs)
        logger.info("%d new jobs for %s", len(new_jobs), name)

        if not new_jobs:
            continue

        # Stage 1: keyword pre-filter
        candidates = keyword_filter(new_jobs)
        logger.info("%d/%d passed keyword filter for %s", len(candidates), len(new_jobs), name)

        for job in new_jobs:
            if job not in candidates:
                update_stage(job.job_id, "keyword_fail")

        # Stage 2: AI evaluation
        for job in candidates:
            update_stage(job.job_id, "keyword_pass")
            try:
                result = evaluate(job)
                total_evaluated += 1
                logger.info(
                    "Evaluated '%s' @ %s: score=%d verdict=%s",
                    job.title, job.company, result.fit_score, result.verdict,
                )
            except Exception as exc:
                logger.error("Error evaluating job %s: %s", job.job_id, exc)
                continue

            if result.verdict in ("apply", "borderline"):
                try:
                    notify(job, result)
                    total_notified += 1
                    logger.info("Notified for %s @ %s", job.title, job.company)
                except Exception as exc:
                    logger.error("Error sending Slack notification for %s: %s", job.job_id, exc)

            save_evaluation(job, result)

    summary = {
        "fetched": total_fetched,
        "new": total_new,
        "evaluated": total_evaluated,
        "notified": total_notified,
    }
    logger.info("Run complete: %s", summary)
    return summary
