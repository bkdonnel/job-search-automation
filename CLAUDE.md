# Job Search Automation — Project Context

## What this is
An automated job search tool that monitors company job boards every 10 minutes and sends Slack notifications for matching roles. Runs on AWS independently of the user's laptop. Uses OpenAI gpt-4o-mini to evaluate job fit.

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
```

## AWS Services
- **Lambda** — runs the Python code on a schedule
- **EventBridge Scheduler** — triggers Lambda every 10 minutes
- **DynamoDB** — tracks seen jobs for deduplication (90-day TTL)
- **SSM Parameter Store** — stores secrets (OpenAI key, Slack webhook)
- **CloudWatch Logs** — Lambda output for debugging (30-day retention)

## Job Boards
All use fully public REST APIs — no auth, no scraping:

| Board | API | Companies |
|---|---|---|
| Greenhouse | `boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true` | Stripe, Airbnb, Pandadoc, Splash Financial, Calm, Octave Health, Rockstar Games, Anduril Industries |
| Lever | `api.lever.co/v0/postings/{token}?mode=json` | Included Health, Bluesight |
| Ashby | `api.ashbyhq.com/posting-api/job-board/{token}` | Acorns, Hims & Hers, Linear, Vercel, Bestow, Sardine |

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
  database.py      # DynamoDB read/write
  notifier.py      # Slack Block Kit webhook
  boards/
    base.py        # Abstract BoardClient with tenacity retry
    greenhouse.py
    lever.py
    ashby.py
config/
  companies.yaml   # Watchlist — edit to add/remove companies
  settings.yaml    # Filter rules, AI thresholds
  profile.txt      # Candidate profile for AI evaluation (Bryan's resume/background)
infrastructure/
  template.yaml    # AWS SAM template
Makefile           # deploy, invoke, logs, secrets setup
requirements.txt
.env.example
```

## DynamoDB Schema
Table name: `jobs`
- PK: `job_id` — `"{board}:{company_token}:{raw_id}"`
- Attributes: `board`, `company`, `title`, `location`, `url`, `first_seen_at`, `stage`, `ai_score`, `ai_verdict`, `ai_reasons`, `ai_concerns`, `notified_at`, `ttl`
- `stage` values: `seen` → `keyword_pass` / `keyword_fail` → `notified` / `skipped`

## Secrets (stored in SSM Parameter Store)
- `/jobsearch/openai_key` → `OPENAI_API_KEY`
- `/jobsearch/slack_webhook` → `SLACK_WEBHOOK_URL`

## Common Commands
```bash
make deploy          # build + deploy to AWS via SAM
make invoke          # trigger Lambda immediately on AWS
make tail-logs       # stream CloudWatch logs live
make logs            # last 1 hour of logs
make scan-table      # inspect DynamoDB records
make invoke-local    # run locally (requires .env)
make add-openai-key  # add OpenAI key to SSM
make add-slack-webhook  # add Slack webhook to SSM
make destroy         # tear down all AWS resources
```

## To Add a Company
1. Find the board token (visible in job listing URLs)
2. Verify the token responds with 200: `curl -s -o /dev/null -w "%{http_code}" "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"`
3. Add entry to `config/companies.yaml`
4. `make deploy`

## Dependencies
`boto3`, `openai`, `pydantic`, `PyYAML`, `requests`, `tenacity`
Runtime: Python 3.12

## Setup Checklist (one-time)
- [x] Personalize `config/profile.txt`
- [x] Tune `config/companies.yaml` and `config/settings.yaml`
- [x] `brew install awscli aws-sam-cli`
- [x] `aws configure` — region: `us-east-1`, output format: leave blank (default json)
- [x] `make add-openai-key`
- [x] `make add-slack-webhook`
- [x] `make deploy`
- [x] `make invoke && make tail-logs` to verify

## Deployment Notes
- `sam deploy` must NOT include `--template` flag — it should use `.aws-sam/build/template.yaml` (the built artifact with installed packages). Passing `--template infrastructure/template.yaml` skips the pip-installed dependencies and causes `No module named 'yaml'` errors in Lambda.
- The Makefile `deploy` target is correct: `sam build --template infrastructure/template.yaml` then `sam deploy` without a template flag.

## Cost Notes
- **OpenAI:** ~$0.0002/evaluation, realistically < $5/month. Use a personal API key with auto-recharge off and a spending cap set on platform.openai.com.
- **AWS:** ~$1.20/month outside free tier (dominated by Lambda execution time). DynamoDB on PAY_PER_REQUEST, CloudWatch logs with 30-day retention.

## Known Issues
- **Linear, Vercel (Ashby)** — returning 0 jobs. APIs respond with 200 but no postings. Tokens are valid; these companies may simply not have open roles at the moment.
- **Notion, Rippling, Figma** — removed from watchlist. Were returning 404s (stale board tokens). If re-adding, find updated tokens from their careers page URLs.

## AWS Console — Where to Find Things
- **Lambda** → Functions → `job-search-automation`
- **EventBridge** → Schedules → `job-search-every-10-min` (rate: 10 minutes, state: Enabled)
- **DynamoDB** → Tables → `jobs` → Explore items
- **CloudWatch** → Log groups → `/aws/lambda/job-search-automation` (30-day retention)
- **Systems Manager** → Parameter Store → `/jobsearch/openai_key`, `/jobsearch/slack_webhook`
- Always confirm region is **us-east-1** (top-right of console)
