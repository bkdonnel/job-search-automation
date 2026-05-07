from __future__ import annotations

import json
import os
from pathlib import Path

from openai import OpenAI

from .models import Job, AIEvaluation
from . import cost_tracker

_client: OpenAI | None = None
_profile: str | None = None

JD_MAX_WORDS = 800
MODEL = "gpt-4o-mini"


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


def _truncate(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " [truncated]"


_SYSTEM_PROMPT = """\
You are a job-fit evaluator. Given a candidate profile and a job description, \
return a JSON object with exactly these fields:
- fit_score (integer 1-10, where 10 = perfect match)
- match_reasons (list of strings, up to 4 bullet points)
- concerns (list of strings, up to 3 bullet points)
- verdict (string: "apply", "borderline", or "skip")

Rules:
- "apply" if fit_score >= 7
- "borderline" if fit_score >= 5
- "skip" if fit_score < 5
Return ONLY valid JSON, no markdown fences."""


def evaluate(job: Job) -> AIEvaluation:
    """Run gpt-4o-mini fit evaluation for a single job."""
    profile = _get_profile()
    jd_truncated = _truncate(job.description_text, JD_MAX_WORDS)

    user_content = f"""## Candidate Profile
{profile}

## Job: {job.title} at {job.company}
Location: {job.location} {'(Remote)' if job.is_remote else ''}

{jd_truncated}"""

    client = _get_client()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0,
        max_tokens=256,
        response_format={"type": "json_object"},
    )

    cost_tracker.record(MODEL, response.usage)

    raw = response.choices[0].message.content
    data = json.loads(raw)

    # Normalise verdict based on score if model drifts
    score = int(data.get("fit_score", 5))
    if score >= 7:
        verdict = "apply"
    elif score >= 5:
        verdict = "borderline"
    else:
        verdict = "skip"

    return AIEvaluation(
        fit_score=score,
        match_reasons=data.get("match_reasons", []),
        concerns=data.get("concerns", []),
        verdict=verdict,
    )
