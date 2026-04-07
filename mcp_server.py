"""Project management MCP server for job-search-automation.

Tools exposed to Claude Code:
  - add_company      — validate board token + append to companies.yaml
  - list_jobs        — query DynamoDB with optional filters
  - get_job_details  — full job record including JD text (for resume tailoring)
  - get_stats        — pipeline counts by stage and verdict
  - trigger_scan     — invoke the Lambda scanner immediately
  - read_drive_file  — read a file from the Google Drive job search folder
  - create_drive_doc — create a new Google Doc in the Drive folder
  - send_email       — send an email to donnelly.bryand@gmail.com via Gmail SMTP
"""
from __future__ import annotations

import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

import boto3
import requests
from mcp.server.fastmcp import FastMCP

REPO_ROOT = Path(__file__).parent
COMPANIES_FILE = REPO_ROOT / "config" / "companies.yaml"
CREDENTIALS_FILE = REPO_ROOT / "credentials.json"
TOKEN_FILE = REPO_ROOT / "token.json"
TABLE_NAME = "jobs"
REGION = "us-east-1"
FUNCTION_NAME = "job-search-automation"
DRIVE_FOLDER_ID = "1CCY1NFNnoeylWDtEBQ3rv2UCofcoCKIh"
EMAIL_ADDRESS = "donnelly.bryand@gmail.com"
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]

BOARD_URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
    "lever": "https://api.lever.co/v0/postings/{token}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{token}",
}

mcp = FastMCP("job-search")


def _table():
    return boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)


@mcp.tool()
def add_company(name: str, board_type: str, board_token: str) -> str:
    """Validate a job board token and add the company to companies.yaml.

    board_type must be one of: greenhouse, lever, ashby.
    After adding, remind the user to run `make deploy`.
    """
    if board_type not in BOARD_URLS:
        return f"Invalid board_type '{board_type}'. Must be: greenhouse, lever, or ashby."

    url = BOARD_URLS[board_type].format(token=board_token)
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return f"Token validation failed — {url} returned HTTP {resp.status_code}. Check the token and try again."
    except Exception as exc:
        return f"Token validation error: {exc}"

    with open(COMPANIES_FILE, "a") as f:
        f.write(f"\n  - name: {name}\n    board_type: {board_type}\n    board_token: {board_token}\n")

    return f"✓ Token valid. Added {name} ({board_type}/{board_token}) to companies.yaml. Run `make deploy` to push the change."


@mcp.tool()
def list_jobs(
    limit: int = 20,
    verdict: Optional[str] = None,
    company: Optional[str] = None,
    stage: Optional[str] = None,
) -> str:
    """List jobs from DynamoDB, most recently seen first.

    verdict: filter by ai_verdict — apply, borderline, or skip
    company: filter by company name (exact match)
    stage:   filter by pipeline stage — seen, keyword_pass, keyword_fail, notified, skipped
    limit:   max results (default 20)
    """
    from boto3.dynamodb.conditions import Attr

    filter_expr = None

    def _and(expr, new):
        return new if expr is None else expr & new

    if verdict:
        filter_expr = _and(filter_expr, Attr("ai_verdict").eq(verdict))
    if company:
        filter_expr = _and(filter_expr, Attr("company").eq(company))
    if stage:
        filter_expr = _and(filter_expr, Attr("stage").eq(stage))

    kwargs: dict = {
        "ProjectionExpression": (
            "job_id, company, title, #loc, ai_verdict, ai_score, "
            "stage, first_seen_at, #u"
        ),
        "ExpressionAttributeNames": {"#u": "url", "#loc": "location"},
    }
    if filter_expr:
        kwargs["FilterExpression"] = filter_expr

    items: list = []
    table = _table()
    resp = table.scan(**kwargs)
    items.extend(resp.get("Items", []))
    while "LastEvaluatedKey" in resp and len(items) < limit * 3:
        resp = table.scan(ExclusiveStartKey=resp["LastEvaluatedKey"], **kwargs)
        items.extend(resp.get("Items", []))

    items.sort(key=lambda x: x.get("first_seen_at", ""), reverse=True)
    items = items[:limit]

    if not items:
        return "No jobs found matching the criteria."

    return json.dumps(items, default=str, indent=2)


@mcp.tool()
def get_job_details(company: str, title: str) -> str:
    """Get the full DynamoDB record for a job, including description_text.

    Used before resume tailoring. Partial title match is supported.
    Returns the most recently seen match if multiple exist.
    """
    from boto3.dynamodb.conditions import Attr

    table = _table()
    resp = table.scan(
        FilterExpression=Attr("company").eq(company) & Attr("title").contains(title)
    )
    items = resp.get("Items", [])

    if not items:
        return f"No job found for company='{company}' with title containing '{title}'."

    items.sort(key=lambda x: x.get("first_seen_at", ""), reverse=True)
    return json.dumps(items[0], default=str, indent=2)


@mcp.tool()
def get_stats() -> str:
    """Return pipeline stats: total jobs, counts by stage, and counts by AI verdict."""
    table = _table()
    resp = table.scan(ProjectionExpression="stage, ai_verdict")
    items = resp.get("Items", [])
    while "LastEvaluatedKey" in resp:
        resp = table.scan(
            ExclusiveStartKey=resp["LastEvaluatedKey"],
            ProjectionExpression="stage, ai_verdict",
        )
        items.extend(resp.get("Items", []))

    stage_counts: dict[str, int] = {}
    verdict_counts: dict[str, int] = {}
    for item in items:
        s = item.get("stage", "unknown")
        stage_counts[s] = stage_counts.get(s, 0) + 1
        v = item.get("ai_verdict")
        if v:
            verdict_counts[v] = verdict_counts.get(v, 0) + 1

    return json.dumps(
        {
            "total_jobs_tracked": len(items),
            "by_stage": stage_counts,
            "by_ai_verdict": verdict_counts,
        },
        indent=2,
    )


@mcp.tool()
def trigger_scan() -> str:
    """Trigger the Lambda job scanner immediately (fires async).

    Check results with `make tail-logs` after ~30 seconds.
    """
    client = boto3.client("lambda", region_name=REGION)
    client.invoke(
        FunctionName=FUNCTION_NAME,
        InvocationType="Event",
        Payload=b"{}",
    )
    return "Lambda triggered. Run `make tail-logs` to watch the output."


# ── Google Drive ──────────────────────────────────────────────────────────────

def _drive_service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if not TOKEN_FILE.exists():
        raise RuntimeError(
            "token.json not found. Run `python scripts/auth_google.py` first."
        )
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), DRIVE_SCOPES)
    return build("drive", "v3", credentials=creds)


@mcp.tool()
def read_drive_file(file_name: str) -> str:
    """Read a file from the Google Drive job search folder by name.

    Google Docs are exported as plain text. Use this to read the master resume.
    """
    service = _drive_service()
    results = service.files().list(
        q=f"name='{file_name}' and '{DRIVE_FOLDER_ID}' in parents and trashed=false",
        fields="files(id, name, mimeType)",
    ).execute()
    files = results.get("files", [])
    if not files:
        return f"File '{file_name}' not found in Drive folder."

    file_id = files[0]["id"]
    mime_type = files[0]["mimeType"]

    if mime_type == "application/vnd.google-apps.document":
        content = service.files().export(fileId=file_id, mimeType="text/plain").execute()
    else:
        content = service.files().get_media(fileId=file_id).execute()

    return content.decode("utf-8")


@mcp.tool()
def create_drive_doc(title: str, content: str) -> str:
    """Create a new Google Doc in the Drive job search folder.

    Returns the URL of the created document.
    Used to save tailored resumes and cover letters.
    """
    from googleapiclient.http import MediaInMemoryUpload

    service = _drive_service()
    file_metadata = {
        "name": title,
        "mimeType": "application/vnd.google-apps.document",
        "parents": [DRIVE_FOLDER_ID],
    }
    media = MediaInMemoryUpload(
        content.encode("utf-8"),
        mimetype="text/plain",
        resumable=False,
    )
    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink",
    ).execute()
    return file.get("webViewLink", "Doc created but no link returned.")


# ── Gmail ─────────────────────────────────────────────────────────────────────

def _gmail_app_password() -> str:
    ssm = boto3.client("ssm", region_name=REGION)
    resp = ssm.get_parameter(Name="/jobsearch/gmail_password", WithDecryption=True)
    return resp["Parameter"]["Value"]


@mcp.tool()
def send_email(subject: str, body: str) -> str:
    """Send a plain-text email to donnelly.bryand@gmail.com via Gmail SMTP.

    Used to notify about newly tailored resumes. Requires the Gmail App Password
    to be stored in SSM at /jobsearch/gmail_password.
    """
    password = _gmail_app_password()
    msg = MIMEMultipart()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_ADDRESS
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_ADDRESS, password)
        server.send_message(msg)

    return f"Email sent: {subject}"


if __name__ == "__main__":
    mcp.run()
