from __future__ import annotations

import json
import math
import os

import boto3
from openai import OpenAI

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMS = 256
SSM_PARAM = "/jobsearch/profile_embedding"

_client: OpenAI | None = None
_profile_embedding: list[float] | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    return _client


def _get_profile_embedding() -> list[float]:
    global _profile_embedding
    if _profile_embedding is None:
        ssm = boto3.client("ssm")
        resp = ssm.get_parameter(Name=SSM_PARAM, WithDecryption=False)
        _profile_embedding = json.loads(resp["Parameter"]["Value"])
    return _profile_embedding


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(x * x for x in b))
    return dot / mag if mag else 0.0


def score_job(description_text: str) -> float:
    """Return cosine similarity between job description and profile. Range: 0.0-1.0."""
    client = _get_client()
    resp = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=description_text[:8000],
        dimensions=EMBEDDING_DIMS,
    )
    job_embedding = resp.data[0].embedding
    return _cosine(_get_profile_embedding(), job_embedding)
