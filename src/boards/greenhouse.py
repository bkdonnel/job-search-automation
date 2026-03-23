from __future__ import annotations

import re
from html.parser import HTMLParser

from ..models import Job
from .base import BoardClient

_API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"


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
    # collapse whitespace
    return re.sub(r"\s+", " ", text).strip()


class GreenhouseClient(BoardClient):
    def fetch_jobs(self) -> list[Job]:
        url = _API.format(token=self.board_token)
        data = self._get(url).json()

        jobs: list[Job] = []
        for item in data.get("jobs", []):
            location_obj = item.get("location") or {}
            location_name = location_obj.get("name", "")
            is_remote = "remote" in location_name.lower()

            description_html = item.get("content", "") or ""
            description_text = _strip_html(description_html)

            job = Job(
                job_id=f"greenhouse:{self.board_token}:{item['id']}",
                board="greenhouse",
                company=self.company_name,
                company_token=self.board_token,
                title=item.get("title", ""),
                location=location_name,
                is_remote=is_remote,
                url=item.get("absolute_url", ""),
                description_text=description_text,
                posted_at=None,  # Greenhouse doesn't expose posted_at in this endpoint
            )
            jobs.append(job)

        return jobs
