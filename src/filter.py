from __future__ import annotations

import yaml
from pathlib import Path
from typing import Any

from .models import Job

_settings: dict[str, Any] | None = None


def _get_settings() -> dict[str, Any]:
    global _settings
    if _settings is None:
        settings_path = Path(__file__).parent.parent / "config" / "settings.yaml"
        with open(settings_path) as f:
            _settings = yaml.safe_load(f)
    return _settings


def keyword_filter(jobs: list[Job]) -> list[Job]:
    """Stage 1 pre-filter: title keywords + location. Free, in-memory."""
    settings = _get_settings()
    filtering = settings["filtering"]

    target_titles: list[str] = [t.lower() for t in filtering.get("target_titles", [])]
    excluded_titles: list[str] = [t.lower() for t in filtering.get("excluded_titles", [])]
    target_locations: list[str] = [l.lower() for l in filtering.get("target_locations", [])]
    require_remote: bool = filtering.get("require_remote", False)

    passed = []
    for job in jobs:
        title_lower = job.title.lower()

        # Must match at least one target title keyword
        if target_titles and not any(kw in title_lower for kw in target_titles):
            continue

        # Must not contain any excluded title keyword
        if any(kw in title_lower for kw in excluded_titles):
            continue

        # Location filter: pass if remote OR location matches
        if job.is_remote:
            passed.append(job)
            continue

        if require_remote:
            continue

        if target_locations and any(loc in job.location.lower() for loc in target_locations):
            passed.append(job)
            continue

        # If no target locations configured, pass everything that cleared title filter
        if not target_locations:
            passed.append(job)

    return passed
