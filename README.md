# Job Search Automation

A personal job search pipeline that runs entirely on AWS, monitors 50+ company job boards every 10 minutes, and uses AI to evaluate fit — then automatically tailors a resume and notifies via Slack and email when a strong match is found.

**Monthly cost: ~$1.20** (AWS outside free tier + ~$0.02/day OpenAI)

---

## What it does

1. **Monitors job boards continuously** — polls Greenhouse, Lever, and Ashby ATS boards every 10 minutes via public REST APIs. No scraping.
2. **Deduplicates** — tracks every seen job in DynamoDB so you're never notified twice.
3. **Filters by title and location** — fast keyword pre-filter eliminates ~90% of irrelevant postings before any AI is invoked.
4. **Evaluates fit with GPT-4o-mini** — scores remaining jobs 1-10 against a candidate profile. Returns match reasons, concerns, and a verdict (`apply` / `borderline` / `skip`).
5. **Sends Slack notifications** — formatted card with job title, company, score, reasons, and a direct link for `apply` and `borderline` verdicts.
6. **Tailors the resume on demand** — when you see a Slack notification you want to act on, tell Claude Code to tailor your resume. It runs a 7-step workflow: JD analysis, resume audit, ATS keyword extraction and insertion, bullet refinement, professional summary, cover letter, and final proofread. The output is saved to Google Drive and emailed automatically.

---

## Architecture

```
EventBridge Scheduler (every 10 min)
         │
         ▼
   AWS Lambda (Python 3.12)
         │
    ┌────┴──────────────────────────────┐
    │  For each company in watchlist:   │
    │  1. Fetch jobs from ATS API       │
    │  2. DynamoDB dedup check          │
    │  3. Keyword pre-filter (free)     │
    │  4. GPT-4o-mini evaluation        │
    │  5. Slack notification            │
    └───────────────────────────────────┘
         │
         ▼
      DynamoDB (90-day TTL)

Claude Code (local, on demand)
         │
    ┌────┴──────────────────────────────┐
    │  MCP Server                       │
    │  - Query jobs / stats             │
    │  - Manage watchlist               │
    │  - Trigger Lambda                 │
    │  - Read/write Google Drive        │
    │  - Send email via Gmail           │
    └───────────────────────────────────┘
```

### AWS services used
| Service | Purpose |
|---|---|
| Lambda | Runs the scanner on a schedule |
| EventBridge Scheduler | Triggers Lambda every 10 minutes |
| DynamoDB | Job tracking and deduplication |
| SSM Parameter Store | Secrets (API keys, webhooks) |
| CloudWatch Logs | Lambda output, 30-day retention |

---

## Tech stack

- **Python 3.12** — Lambda runtime and local MCP server
- **AWS SAM** — infrastructure as code, single-command deploy
- **OpenAI GPT-4o-mini** — job fit evaluation (~$0.0002/evaluation)
- **Pydantic** — data models and validation
- **Tenacity** — retry logic for ATS API calls
- **Model Context Protocol (MCP)** — local server that lets Claude Code query DynamoDB, manage the watchlist, and orchestrate the resume tailoring workflow
- **Google Drive API** — stores master resume, saves tailored output docs
- **Gmail SMTP** — sends notification emails

---

## Key design decisions

**Two-stage filtering** keeps AI costs near zero. A fast keyword filter runs first and typically eliminates 90%+ of jobs. GPT-4o-mini only sees the small remainder that passed title and location checks.

**Public APIs only** — Greenhouse, Lever, and Ashby all expose public job board REST APIs. No scraping, no authentication, no brittle DOM parsing.

**MCP server as a local control plane** — rather than logging into the AWS console to inspect results or add companies, a local MCP server exposes the system as Claude Code tools. Adding a company, checking stats, or triggering a scan is a one-sentence conversation.

**Resume tailoring as an agent workflow** — the 7-step tailoring process (documented in `config/resume_workflow.md`) runs as an autonomous Claude Code workflow. It reads the master resume from Drive, applies all edits, and delivers a finished draft without manual steps.

---

## Project structure

```
src/
  handler.py            # Lambda entry point
  models.py             # Pydantic models: Job, AIEvaluation
  filter.py             # Stage 1 keyword pre-filter
  evaluator.py          # Stage 2 GPT-4o-mini evaluation
  database.py           # DynamoDB read/write
  notifier.py           # Slack Block Kit notifications
  boards/
    base.py             # Abstract BoardClient with retry logic
    greenhouse.py
    lever.py
    ashby.py
config/
  companies.yaml        # Watchlist of 50+ companies with ATS tokens
  settings.yaml         # Filter rules and AI thresholds
  profile.txt           # Candidate profile used for AI evaluation
  resume_workflow.md    # 7-step autonomous resume tailoring workflow
infrastructure/
  template.yaml         # AWS SAM template
scripts/
  auth_google.py        # One-time Google Drive OAuth setup
mcp_server.py           # Local MCP server for Claude Code
Makefile                # All operational commands
```

---

## Setup

### Prerequisites
```bash
brew install awscli aws-sam-cli
aws configure           # IAM user with programmatic access, region us-east-1
```

### Secrets
```bash
make add-openai-key       # OpenAI API key
make add-slack-webhook    # Slack Incoming Webhook URL
make add-gmail-password   # Gmail App Password (for email notifications)
```

### Configure your search
- `config/companies.yaml` — add companies with their ATS board token
- `config/profile.txt` — 200-300 words describing your background and target role
- `config/settings.yaml` — target titles, excluded titles, and target locations

### Deploy
```bash
make deploy
```

Builds the Lambda package and deploys the full stack via AWS SAM.

### Verify
```bash
make invoke       # trigger Lambda immediately
make tail-logs    # stream CloudWatch logs
```

### Set up local MCP tools (one-time)
```bash
pip install mcp google-api-python-client google-auth-oauthlib google-auth-httplib2
make auth-google  # opens browser for Google Drive OAuth
```

Add your Exa API key to `~/.zshrc`:
```bash
export EXA_API_KEY=your-key-here
```

---

## Usage

Once deployed, the scanner runs automatically. When you get a Slack notification for a job you want to pursue, open Claude Code and say:

> "Tailor my resume for the [Company] [Title] job"

Claude reads the job from DynamoDB, fetches your master resume from Drive, runs the full tailoring workflow, saves the output doc to Drive, and emails you a link.

Other things you can ask Claude Code:
- "Show me all jobs with verdict apply from this week"
- "What are my pipeline stats?"
- "Add Notion to the watchlist — they use Greenhouse"
- "Trigger a scan now"

---

## Teardown

```bash
make destroy    # deletes all AWS resources
```
