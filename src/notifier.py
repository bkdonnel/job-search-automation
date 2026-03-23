from __future__ import annotations

import os
from datetime import datetime, timezone

import requests

from .models import Job, AIEvaluation

_WEBHOOK_URL: str | None = None


def _get_webhook_url() -> str:
    global _WEBHOOK_URL
    if _WEBHOOK_URL is None:
        _WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]
    return _WEBHOOK_URL


def _time_ago(posted_at: datetime | None) -> str:
    if not posted_at:
        return "recently"
    now = datetime.now(tz=timezone.utc)
    delta = now - posted_at
    hours = int(delta.total_seconds() / 3600)
    if hours < 1:
        minutes = int(delta.total_seconds() / 60)
        return f"{minutes} min ago"
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"


def notify(job: Job, evaluation: AIEvaluation) -> None:
    """Send a Slack Block Kit message for a matching job."""
    score = evaluation.fit_score
    verdict_emoji = "🎯" if evaluation.verdict == "apply" else "🔶"
    verdict_label = "New Job Match" if evaluation.verdict == "apply" else "Borderline Match"

    reasons_text = "\n".join(f"• {r}" for r in evaluation.match_reasons) or "—"
    concerns_text = "\n".join(f"• {c}" for c in evaluation.concerns) or "None"
    location_str = f"{'Remote' if job.is_remote else job.location}"
    time_str = _time_ago(job.posted_at)

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{verdict_emoji} {verdict_label} — Score {score}/10",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*{job.title}* @ {job.company}\n📍 {location_str} | Posted: {time_str}",
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*✅ Why it matches:*\n{reasons_text}"},
                {"type": "mrkdwn", "text": f"*⚠️ Concerns:*\n{concerns_text}"},
            ],
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "👉 View Job"},
                    "url": job.url,
                    "style": "primary",
                }
            ],
        },
        {"type": "divider"},
    ]

    webhook_url = _get_webhook_url()
    resp = requests.post(webhook_url, json={"blocks": blocks}, timeout=10)
    resp.raise_for_status()
