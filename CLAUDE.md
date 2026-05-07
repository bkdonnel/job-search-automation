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
  embedder.py      # Embedding similarity — returns (score, vector) tuple; vector persisted to DynamoDB
  database.py      # DynamoDB read/write (stores description_text, job_embedding for search)
  cost_tracker.py  # Tracks OpenAI token usage and cost per Lambda run; logs COST_SUMMARY to CloudWatch
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
mcp_server.py      # Local MCP server for Claude Code (9 tools)
Makefile           # deploy, invoke, logs, secrets setup
requirements.txt
.env.example
credentials.json   # Google OAuth credentials (gitignored)
token.json         # Google OAuth token (gitignored)
```

## DynamoDB Schema
Table name: `jobs`
- PK: `job_id` — `"{board}:{company_token}:{raw_id}"`
- Attributes: `board`, `company`, `company_token`, `title`, `location`, `url`, `description_text`, `first_seen_at`, `stage`, `ai_score`, `ai_verdict`, `ai_reasons`, `ai_concerns`, `embedding_score`, `job_embedding`, `notified_at`, `ttl`
- `stage` values: `seen` → `keyword_pass` / `keyword_fail` / `embedding_fail` → `notified` / `skipped`
- `job_embedding` — 256-dim vector stored as JSON string; only present on jobs that passed the embedding threshold and were fully evaluated. Used by `search_jobs` MCP tool.
- Note: `description_text`, `company_token`, and `job_embedding` were added incrementally — older records won't have these fields

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
- `search_jobs(query, limit)` — semantic similarity search across stored job embeddings (e.g. "find jobs like the Stripe analytics engineer role")
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

## Potential Improvements (from ai-application-october-2025 repo)

Prioritized by effort vs. value. Ideas sourced from cross-referencing with the ai-application-october-2025 recruiting platform repo.

### 1. Cost Analytics Middleware — LOW EFFORT / HIGH VALUE
**Status: done**
`src/cost_tracker.py` — module-level accumulator with `reset()`, `record(model, usage)`, and `log_summary(logger)`. Called in `evaluator.py` and `embedder.py` after every OpenAI response. `handler.py` resets at the start of each invocation and emits a `COST_SUMMARY` CloudWatch log line at the end with per-model token counts and dollar cost.

**Why:** The $0.02/day estimate is unverified. Real visibility into per-invocation spend surfaces drift before it becomes a bill surprise.

### 2. Semantic Job Search MCP Tool — LOW EFFORT / HIGH VALUE
**Status: done**
`embedder.py` now returns `(similarity, embedding)` tuple. The embedding is persisted to DynamoDB as a JSON string in the `job_embedding` attribute via `save_evaluation()`. `mcp_server.py` has a new `search_jobs(query, limit=10)` tool that embeds the query, scans DynamoDB for jobs with stored embeddings, ranks by cosine similarity, and returns the top N. Only jobs processed after deploy will have embeddings.

**Why:** `list_jobs` only supports exact field filtering. Semantic search enables queries like "find jobs similar to the Stripe Analytics Engineer role."

### 3. Tracing / Structured Decision Logging — LOW EFFORT / MEDIUM VALUE
**Status: not started**
Log each AI decision to DynamoDB with full context: job_id, model used, tokens consumed, input prompt snapshot, verdict, score. Modeled after `middleware_tracing.py` in ai-application-october-2025. CloudWatch logs are ephemeral and hard to query; DynamoDB records are queryable and persistent.

**Why:** Makes it easy to audit why specific jobs were scored the way they were and catch evaluator drift over time.

### 4. GPT Reranking Before Full Evaluation — LOW EFFORT / MEDIUM VALUE
**Status: not started**
After the embedding similarity step, batch the surviving candidates per Lambda run and ask GPT to rank them by fit against the profile before running full gpt-4o-mini evaluations. Only evaluate the top N. Modeled after `rerank_results_gpt()` in `main.py` of ai-application-october-2025.

**Why:** On high-volume days, reranking is cheaper than running full evaluations on every embedding-passing job.

### 5. Evaluation Framework — MEDIUM EFFORT / HIGH VALUE
**Status: not started**
Export 50-100 past DynamoDB records that have been manually reviewed as ground-truth labels. Build a test harness (modeled after `evaluate_database_agent.py`) that runs the evaluator against this dataset and measures accuracy. Use results to tune `apply_threshold` and `borderline_threshold` in `settings.yaml` with data rather than intuition.

**Why:** Current thresholds (7 for apply, 5 for borderline) are hand-tuned with no measurement of false positive/negative rates.

### 6. DSPy Prompt Optimization — MEDIUM EFFORT / HIGH VALUE
**Status: not started**
Use the labeled dataset from Idea 5 as training data for DSPy's BootstrapFewShot or MIPROv2 to auto-optimize the evaluator system prompt in `evaluator.py`. Modeled after `optimize_database_agent_prompt.py` in ai-application-october-2025.

**Why:** Hand-written prompts leave accuracy on the table. DSPy can find phrasings and few-shot examples that measurably improve verdict quality without manual iteration.

### 7. Upgrade Evaluator to Claude — LOW EFFORT / MEDIUM VALUE
**Status: not started**
Swap `gpt-4o-mini` in `evaluator.py` for `claude-haiku-4-5-20251001`. Similar price point, but Claude tends to follow structured JSON output instructions more reliably — which matters for the verdict format.

**Why:** The current evaluator occasionally returns malformed JSON or ignores the score-to-verdict normalization. Worth A/B testing once the evaluation framework (Idea 5) is in place to measure the difference objectively.

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



# Coding Standards & Conventions

## General Python
- Use functional, declarative programming — avoid classes where possible
- Prefer iteration and modularization over code duplication
- Use descriptive variable names with auxiliary verbs (e.g., `is_active`, `has_permission`)
- Use lowercase with underscores for directories and files (e.g., `routers/user_routes.py`)
- Favor named exports for routes and utility functions
- Use the Receive an Object, Return an Object (RORO) pattern
- Use `def` for pure/synchronous functions and `async def` for asynchronous operations
- Type hints required on all function signatures
- Prefer Pydantic `BaseModel` over raw dictionaries for input validation
- No emojis or symbols in any Python files

## Code Style
- Avoid unnecessary curly braces in conditional statements
- Omit curly braces for single-line conditionals
- Use concise one-line syntax for simple conditionals (e.g., `if condition: do_something()`)

## File Structure
Each module should follow this order:
1. Exported router
2. Sub-routes
3. Utilities
4. Static content
5. Types (models, schemas)

## FastAPI
- Use functional components (plain functions) and Pydantic models for validation and response schemas
- Use declarative route definitions with explicit return type annotations
- Prefer lifespan context managers over `@app.on_event("startup")` / `@app.on_event("shutdown")`
- Use middleware for logging, error monitoring, and performance optimization
- Use `HTTPException` for expected errors modeled as specific HTTP responses
- Use middleware for unexpected errors, logging, and error monitoring
- Refer to FastAPI docs for Data Models, Path Operations, and Middleware best practices

## Database & Async
- Use async functions for all I/O-bound tasks (database calls, external API requests)
- Minimize blocking I/O operations — async required for all DB and external requests
- Preferred async DB libraries: `asyncpg` or `aiomysql`
- Use SQLAlchemy 2.0 for ORM features when needed

## Performance
- Implement caching for static and frequently accessed data (Redis or in-memory)
- Use lazy loading for large datasets and substantial API responses
- Optimize data serialization/deserialization with Pydantic