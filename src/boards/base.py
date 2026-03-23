from __future__ import annotations

from abc import ABC, abstractmethod

import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from ..models import Job

# Shared session with a reasonable timeout
_session = requests.Session()
_session.headers["User-Agent"] = "job-search-automation/1.0"

REQUEST_TIMEOUT = 15  # seconds


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _get(url: str, **kwargs) -> requests.Response:
    resp = _session.get(url, timeout=REQUEST_TIMEOUT, **kwargs)
    resp.raise_for_status()
    return resp


class BoardClient(ABC):
    def __init__(self, company_name: str, board_token: str) -> None:
        self.company_name = company_name
        self.board_token = board_token

    @abstractmethod
    def fetch_jobs(self) -> list[Job]:
        """Return all currently open jobs for this company."""
        ...

    def _get(self, url: str, **kwargs) -> requests.Response:
        return _get(url, **kwargs)
