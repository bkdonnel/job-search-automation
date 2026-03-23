from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser

from ..models import Job
from .base import BoardClient

_API = "https://api.ashbyhq.com/posting-api/job-board/{token}"


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


class AshbyClient(BoardClient):
    def fetch_jobs(self) -> list[Job]:
        url = _API.format(token=self.board_token)
        data = self._get(url).json()

        jobs: list[Job] = []
        for item in data.get("jobPostings", []):
            location_obj = item.get("location") or {}
            location_name = location_obj if isinstance(location_obj, str) else location_obj.get("name", "")
            is_remote = item.get("isRemote", False) or "remote" in location_name.lower()

            description_html = item.get("descriptionHtml", "") or ""
            description_text = _strip_html(description_html)

            # publishedDate is ISO string
            published = item.get("publishedDate")
            posted_at = None
            if published:
                try:
                    posted_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
                except ValueError:
                    pass

            job_id_raw = item.get("id", item.get("jobId", ""))
            job = Job(
                job_id=f"ashby:{self.board_token}:{job_id_raw}",
                board="ashby",
                company=self.company_name,
                company_token=self.board_token,
                title=item.get("title", ""),
                location=location_name,
                is_remote=is_remote,
                url=item.get("jobUrl", ""),
                description_text=description_text,
                posted_at=posted_at,
            )
            jobs.append(job)

        return jobs
