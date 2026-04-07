# Job Search Automation — Project Context

## What this is
An automated job search tool that monitors company job boards every 10 minutes and sends Slack notifications for matching roles. Runs on AWS independently of the user's laptop. Uses OpenAI gpt-4o-mini to evaluate job fit. A local MCP server enables managing the system and triggering resume tailoring directly from Claude Code.

## Architecture

```
EventBridge Scheduler (every 10 min)
         │
         ▼
   Lambda Function
         │
    ┌────┴────────────────────────────┐
    │  For each company in config:    │
    │  1. Fetch jobs from ATS API     │
    │  2. Check DynamoDB (dedup)      │
    │  3. Keyword pre-filter          │
    │  4. gpt-4o-mini evaluation      │
    │  5. Slack notification          │
    └─────────────────────────────────┘
         │
         ▼
      DynamoDB (job tracking)

Claude Code (local, on demand)
         │
    ┌────┴────────────────────────────────────┐
    │  MCP Server (mcp_server.py)             │
    │  - Query DynamoDB                       │
    │  - Manage companies.yaml                │
    │  - Trigger Lambda                       │
    │  - Read/write Google Drive              │
    │  - Send email via Gmail SMTP            │
    └─────────────────────────────────────────┘
```

## AWS Services
- **Lambda** — runs the Python code on a schedule
- **EventBridge Scheduler** — triggers Lambda every 10 minutes
- **DynamoDB** — tracks seen jobs for deduplication (90-day TTL)
- **SSM Parameter Store** — stores secrets (OpenAI key, Slack webhook, Gmail app password, Exa key)
- **CloudWatch Logs** — Lambda output for debugging (30-day retention)

## Job Boards
All use fully public REST APIs — no auth, no scraping:

| Board | API | Companies |
|---|---|---|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | Stripe, Airbnb, Pandadoc, Splash Financial, Calm, Octave Health, Rockstar Games, Anduril Industries, and others |
| Lever | `api.lever.co/v0/postings/{token}?mode=json` | Included Health, Bluesight, and others |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{token}` | Acorns, Hims & Hers, Freshpaint, Whatnot, and others |

## Two-Stage Filtering Pipeline
- **Stage 1 (free):** Keyword filter on title and location — eliminates ~80-95% of jobs
- **Stage 2 (paid):** gpt-4o-mini evaluates remaining jobs against `config/profile.txt`
  - ~$0.0002 per evaluation
  - Returns `{fit_score: 1-10, match_reasons, concerns, verdict: "apply"|"borderline"|"skip"}`
  - Notifies for `apply` and `borderline`; silently skips `skip`

## Filtering Rules (config/settings.yaml)
**Target titles (substring match):**
- `data analyst`, `analytics engineer`, `data engineer`, `business intelligence engineer`
- Covers: Data Analyst, Senior Data Analyst, Analytics Engineer, Senior Analytics Engineer, Data Engineer

**Excluded titles:** VP, Director, Principal, Staff, Intern, Internship, Manager, Head of

**Locations:**
- Remote (anywhere in US)
- Onsite/hybrid within ~25 miles of Irvine, CA (Orange County cities)
- Onsite/hybrid in broader San Diego area

## Key Files

```
src/
  handler.py       # Lambda entry point — wires all stages together
  models.py        # Pydantic: Job, AIEvaluation
  filter.py        # Stage 1 keyword pre-filter
  evaluator.py     # Stage 2 gpt-4o-mini evaluation
  database.py      # DynamoDB read/write (stores description_text for resume tailoring)
  notifier.py      # Slack Block Kit webhook
  boards/
    base.py        # Abstract BoardClient with tenacity retry
    greenhouse.py
    lever.py
    ashby.py
config/
  companies.yaml      # Watchlist — edit to add/remove companies
  settings.yaml       # Filter rules, AI thresholds
  profile.txt         # Candidate profile for AI evaluation (Bryan's resume/background)
  resume_workflow.md  # 7-step autonomous resume tailoring workflow
infrastructure/
  template.yaml    # AWS SAM template
scripts/
  auth_google.py   # One-time Google Drive OAuth (generates token.json)
mcp_server.py      # Local MCP server for Claude Code
Makefile           # deploy, invoke, logs, secrets setup
requirements.txt
.env.example
credentials.json   # Google OAuth credentials (gitignored)
token.json         # Google OAuth token (gitignored)
```

## DynamoDB Schema
Table name: `jobs`
- PK: `job_id` — `"{board}:{company_token}:{raw_id}"`
- Attributes: `board`, `company`, `company_token`, `title`, `location`, `url`, `description_text`, `first_seen_at`, `stage`, `ai_score`, `ai_verdict`, `ai_reasons`, `ai_concerns`, `notified_at`, `ttl`
- `stage` values: `seen` → `keyword_pass` / `keyword_fail` → `notified` / `skipped`
- Note: `description_text` and `company_token` were added — jobs seen before this change won't have these fields

## Secrets (stored in SSM Parameter Store)
- `/jobsearch/openai_key` → `OPENAI_API_KEY`
- `/jobsearch/slack_webhook` → `SLACK_WEBHOOK_URL`
- `/jobsearch/exa_key` → `EXA_API_KEY` (Exa web search, for future enrichment)
- `/jobsearch/gmail_password` → Gmail App Password for SMTP sending

## Common Commands
```bash
make deploy             # build + deploy to AWS via SAM
make invoke             # trigger Lambda immediately on AWS
make tail-logs          # stream CloudWatch logs live
make logs               # last 1 hour of logs
make scan-table         # inspect DynamoDB records
make invoke-local       # run locally (requires .env)
make add-openai-key     # add OpenAI key to SSM
make add-slack-webhook  # add Slack webhook to SSM
make add-exa-key        # add Exa API key to SSM
make add-gmail-password # add Gmail App Password to SSM
make auth-google        # one-time Google Drive OAuth (generates token.json)
make destroy            # tear down all AWS resources
```

## MCP Server (Local)
`mcp_server.py` is registered in `.mcp.json` and runs automatically when Claude Code opens this project. It exposes these tools:

- `add_company(name, board_type, board_token)` — validate token + append to `companies.yaml`. Always run this instead of editing the file manually.
- `list_jobs(limit, verdict, company, stage)` — query DynamoDB with optional filters
- `get_job_details(company, title)` — full job record including JD text, used before resume tailoring
- `get_stats()` — pipeline counts by stage and AI verdict
- `trigger_scan()` — invoke Lambda immediately (async, check logs after ~30s)
- `read_drive_file(file_name)` — read a file from the Google Drive job search folder
- `create_drive_doc(title, content)` — create a Google Doc in the Drive folder
- `send_email(subject, body)` — send email to donnelly.bryand@gmail.com via Gmail SMTP

An Exa web search MCP is also configured in `.mcp.json` for company research. Requires `EXA_API_KEY` exported in the shell (`~/.zshrc`).

## To Add a Company
Use the `add_company` MCP tool — it validates the token and updates `companies.yaml` automatically. Then run `make deploy`.

Manual validation: `curl -s -o /dev/null -w "%{http_code}" "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"`

## Resume Tailoring
When asked to tailor a resume for a job (e.g. "tailor my resume for the Freshpaint Analytics Engineer job"):

1. Call `get_job_details` to retrieve the full job record from DynamoDB (company, title, JD text, URL, AI score)
2. Call `read_drive_file("Donnelly_Bryan_Resume_master")` to read the master resume from Google Drive (folder ID: `1CCY1NFNnoeylWDtEBQ3rv2UCofcoCKIh`)
3. Follow the full 7-step workflow in `config/resume_workflow.md` — apply all changes automatically, no approval needed
4. Call `create_drive_doc` to save the output titled `[COMPANY_NAME] — [JOB_TITLE] — Tailored Resume` in the same Drive folder
5. Call `send_email` to notify donnelly.bryand@gmail.com with subject `Tailored Resume Ready — [JOB_TITLE] at [COMPANY_NAME]`, including job details (title, company, AI score, AI verdict, match reasons) and the Drive doc link

## Dependencies
**Lambda (deployed):** `boto3`, `openai`, `pydantic`, `PyYAML`, `requests`, `tenacity`
**Local only:** `mcp[cli]`, `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2`
Runtime: Python 3.12

## Setup Checklist (one-time)
- [x] Personalize `config/profile.txt`
- [x] Tune `config/companies.yaml` and `config/settings.yaml`
- [x] `brew install awscli aws-sam-cli`
- [x] `aws configure` — region: `us-east-1`, output format: leave blank (default json)
- [x] `make add-openai-key`
- [x] `make add-slack-webhook`
- [x] `make add-exa-key`
- [x] `make add-gmail-password`
- [x] `make auth-google` — one-time Google Drive OAuth
- [x] `pip install mcp google-api-python-client google-auth-oauthlib google-auth-httplib2`
- [x] Add `export EXA_API_KEY=...` to `~/.zshrc`
- [x] `make deploy`
- [x] `make invoke && make tail-logs` to verify

## Deployment Notes
- `sam deploy` must NOT include `--template` flag — it should use `.aws-sam/build/template.yaml` (the built artifact with installed packages). Passing `--template infrastructure/template.yaml` skips the pip-installed dependencies and causes `No module named 'yaml'` errors in Lambda.
- The Makefile `deploy` target is correct: `sam build --template infrastructure/template.yaml` then `sam deploy` without a template flag.
- The local-only dependencies (`mcp`, Google packages) are in `requirements.txt` but are not installed in Lambda — SAM builds from requirements.txt but the Lambda environment doesn't use them. This is fine; they're lightweight and don't conflict.

## Cost Notes
- **OpenAI:** ~$0.0002/evaluation, realistically < $5/month. Use a personal API key with auto-recharge off and a spending cap set on platform.openai.com.
- **AWS:** ~$1.20/month outside free tier (dominated by Lambda execution time). DynamoDB on PAY_PER_REQUEST, CloudWatch logs with 30-day retention.
- **Exa:** Free tier — 1,000 searches/month.

## Known Issues
- **Linear, Vercel (Ashby)** — returning 0 jobs. APIs respond with 200 but no postings. Tokens are valid; these companies may simply not have open roles at the moment.
- **Notion, Rippling, Figma** — removed from watchlist. Were returning 404s (stale board tokens). If re-adding, find updated tokens from their careers page URLs.
- **description_text in DynamoDB** — only populated for jobs seen after the database.py update. Older records won't have JD text available for resume tailoring.

## AWS Console — Where to Find Things
- **Lambda** → Functions → `job-search-automation`
- **EventBridge** → Schedules → `job-search-every-10-min` (rate: 10 minutes, state: Enabled)
- **DynamoDB** → Tables → `jobs` → Explore items
- **CloudWatch** → Log groups → `/aws/lambda/job-search-automation` (30-day retention)
- **Systems Manager** → Parameter Store → `/jobsearch/openai_key`, `/jobsearch/slack_webhook`, `/jobsearch/exa_key`, `/jobsearch/gmail_password`
- Always confirm region is **us-east-1** (top-right of console)
