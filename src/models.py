from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, HttpUrl


class Job(BaseModel):
    job_id: str          # "{board}:{company_token}:{raw_id}"
    board: Literal["greenhouse", "lever", "ashby"]
    company: str         # human-readable name, e.g. "Stripe"
    company_token: str   # board token, e.g. "stripe"
    title: str
    location: str
    is_remote: bool
    url: str
    description_text: str  # HTML-stripped, may be truncated
    posted_at: Optional[datetime] = None


class AIEvaluation(BaseModel):
    fit_score: int                    # 1-10
    match_reasons: list[str]
    concerns: list[str]
    verdict: Literal["apply", "borderline", "skip"]
