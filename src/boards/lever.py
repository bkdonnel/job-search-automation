from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser

from ..models import Job
from .base import BoardClient

_API = "https://api.lever.co/v0/postings/{token}?mode=json"


class _HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join(self._parts)


def _strip_html(html: str) -> str:
    s = _HTMLStripper()
    s.feed(html or "")
    text = s.get_text()
    return re.sub(r"\s+", " ", text).strip()


class LeverClient(BoardClient):
    def fetch_jobs(self) -> list[Job]:
        url = _API.format(token=self.board_token)
        items = self._get(url).json()

        jobs: list[Job] = []
        for item in items:
            categories = item.get("categories") or {}
            location = categories.get("location", "")
            commitment = categories.get("commitment", "")
            is_remote = "remote" in location.lower() or "remote" in commitment.lower()

            # Description: list of {header, body} dicts
            description_parts = []
            for section in item.get("lists", []):
                description_parts.append(section.get("text", ""))
                description_parts.append(section.get("content", ""))
            description_parts.append(item.get("descriptionPlain", "") or "")
            description_text = re.sub(r"\s+", " ", " ".join(description_parts)).strip()

            # createdAt is epoch ms
            created_at_ms = item.get("createdAt")
            posted_at = None
            if created_at_ms:
                posted_at = datetime.fromtimestamp(created_at_ms / 1000, tz=timezone.utc)

            job = Job(
                job_id=f"lever:{self.board_token}:{item['id']}",
                board="lever",
                company=self.company_name,
                company_token=self.board_token,
                title=item.get("text", ""),
                location=location,
                is_remote=is_remote,
                url=item.get("hostedUrl", ""),
                description_text=description_text,
                posted_at=posted_at,
            )
            jobs.append(job)

        return jobs
