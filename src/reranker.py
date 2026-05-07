"""Reranks embedding-passing candidates before full AI evaluation."""
from __future__ import annotations

import json
import os
from pathlib import Path

from openai import OpenAI

from .models import Job
from . import cost_tracker

RERANK_MODEL = "gpt-4o-mini"
JD_PREVIEW_CHARS = 300

_client: OpenAI | None = None
_profile: str | None = None
_settings: dict | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _client


def _get_profile() -> str:
    global _profile
    if _profile is None:
        profile_path = Path(__file__).parent.parent / "config" / "profile.txt"
        _profile = profile_path.read_text().strip()
    return _profile


def _get_settings() -> dict:
    global _settings
    if _settings is None:
        import yaml
        settings_path = Path(__file__).parent.parent / "config" / "settings.yaml"
        with open(settings_path) as f:
            _settings = yaml.safe_load(f)
    return _settings


_SYSTEM_PROMPT = """\
You are a job relevance ranker. Given a candidate profile and a list of jobs, \
rank the jobs by how well they match the candidate. \
Return ONLY a JSON object with a "ranked_ids" array of job IDs ordered from best to worst match."""


def _call_rerank_api(
    candidates: list[tuple[Job, float, list[float] | None]],
    top_n: int,
) -> list[tuple[Job, float, list[float] | None]]:
    """Call GPT to rank candidates and return the top_n. Falls back to embedding order."""
    profile = _get_profile()

    job_summaries = [
        {
            "id": idx,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "preview": (job.description_text or "")[:JD_PREVIEW_CHARS],
        }
        for idx, (job, _, _) in enumerate(candidates)
    ]

    user_content = f"""## Candidate Profile
{profile}

## Jobs to Rank
{json.dumps(job_summaries, indent=2)}

Return format: {{"ranked_ids": [2, 0, 1, ...]}}"""

    try:
        response = _get_client().chat.completions.create(
            model=RERANK_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            temperature=0,
            max_tokens=256,
            response_format={"type": "json_object"},
        )
        cost_tracker.record(RERANK_MODEL, response.usage)

        ranked_ids = json.loads(response.choices[0].message.content).get("ranked_ids", [])

        seen: set[int] = set()
        reranked: list[tuple[Job, float, list[float] | None]] = []
        for idx in ranked_ids:
            if 0 <= idx < len(candidates) and idx not in seen:
                reranked.append(candidates[idx])
                seen.add(idx)
        for idx, candidate in enumerate(candidates):
            if idx not in seen:
                reranked.append(candidate)

        return reranked[:top_n]

    except Exception:
        return sorted(candidates, key=lambda x: x[1], reverse=True)[:top_n]


def rerank_candidates(
    candidates: list[tuple[Job, float, list[float] | None]],
) -> tuple[list[tuple[Job, float, list[float] | None]], list[Job]]:
    """Rerank candidates if count exceeds the min_candidates threshold.

    Returns (top_candidates, reranked_out_jobs).
    If reranking is disabled or not needed, returns (candidates, []).
    """
    cfg = _get_settings().get("rerank", {})

    if not cfg.get("enabled", True):
        return candidates, []

    top_n = cfg.get("top_n", 10)
    min_candidates = cfg.get("min_candidates", 4)

    if len(candidates) <= min_candidates:
        return candidates, []

    top = _call_rerank_api(candidates, top_n)
    top_ids = {job.job_id for job, _, _ in top}
    reranked_out = [job for job, _, _ in candidates if job.job_id not in top_ids]

    return top, reranked_out
