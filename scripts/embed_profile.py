# Run via: make embed-profile

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import boto3
from openai import OpenAI

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMS = 256
SSM_PARAM = "/jobsearch/profile_embedding"
REGION = "us-east-1"


def main() -> None:
    profile_path = Path(__file__).parent.parent / "config" / "profile.txt"
    if not profile_path.exists():
        print(f"ERROR: {profile_path} not found", file=sys.stderr)
        sys.exit(1)

    profile_text = profile_path.read_text().strip()
    print(f"Loaded profile ({len(profile_text)} chars)")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY not set in environment", file=sys.stderr)
        sys.exit(1)

    client = OpenAI(api_key=api_key)
    resp = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=profile_text,
        dimensions=EMBEDDING_DIMS,
    )
    embedding = [round(x, 6) for x in resp.data[0].embedding]
    payload = json.dumps(embedding)

    print(f"Generated {len(embedding)}-dim embedding ({len(payload)} bytes)")

    if len(payload.encode()) > 4096:
        print("Error: Payload exceeds SSM 4KB limit", file=sys.stderr)
        sys.exit(1)

    ssm = boto3.client("ssm", region_name=REGION)
    ssm.put_parameter(
        Name=SSM_PARAM,
        Value=payload,
        Type="String",
        Overwrite=True,
    )
    print(f"Stored in SSM: {SSM_PARAM}")


if __name__ == "__main__":
    main()