# Job Search Automation

Monitors company job boards every 10 minutes and sends Slack notifications for matching roles, evaluated by GPT-4o-mini.

**Cost: ~$0/month** (AWS free tier + ~$0.02/day OpenAI at moderate volume)

## How it works

```
EventBridge (every 10 min) → Lambda → fetch jobs → DynamoDB dedup
→ keyword filter → gpt-4o-mini evaluation → Slack notification
```

Boards supported: Greenhouse, Lever, Ashby (all public REST APIs — no scraping).

## Quick start

### 1. Prerequisites

```bash
brew install awscli aws-sam-cli
aws configure          # IAM user with programmatic access
```

### 2. Add secrets to SSM

```bash
make add-openai-key    # prompts for your OpenAI API key
make add-slack-webhook # prompts for your Slack Incoming Webhook URL
```

To create a Slack webhook: https://api.slack.com/messaging/webhooks

### 3. Configure your watchlist

Edit `config/companies.yaml` — add companies with their ATS board token.

To find a board token:
- **Greenhouse**: visit `boards.greenhouse.io/{token}` (shown in job URLs)
- **Lever**: visit `jobs.lever.co/{token}`
- **Ashby**: visit `jobs.ashbyhq.com/{token}`

### 4. Update your profile

Edit `config/profile.txt` — 200–300 words describing your skills, experience, and what you're looking for. The AI uses this to evaluate fit.

### 5. Tune filters

Edit `config/settings.yaml` — adjust `target_titles`, `excluded_titles`, and `target_locations` to your search.

### 6. Deploy

```bash
make deploy
```

This builds the Lambda package and deploys the full stack (Lambda + DynamoDB + EventBridge schedule) via AWS SAM.

### 7. Test

```bash
make invoke       # trigger Lambda immediately on AWS, see response
make tail-logs    # stream CloudWatch logs live
make scan-table   # inspect DynamoDB records
```

## Local testing

```bash
cp .env.example .env
# fill in OPENAI_API_KEY and SLACK_WEBHOOK_URL
make invoke-local
```

Requires a DynamoDB table reachable via `AWS_ENDPOINT_URL` (e.g. local Docker) or real AWS credentials.

## Adding a company

1. Add an entry to `config/companies.yaml`
2. `make deploy`

## Directory structure

```
src/
  handler.py       # Lambda entry point
  models.py        # Job, AIEvaluation pydantic models
  filter.py        # Stage 1 keyword pre-filter
  evaluator.py     # Stage 2 gpt-4o-mini evaluation
  database.py      # DynamoDB read/write
  notifier.py      # Slack Block Kit notifications
  boards/
    greenhouse.py
    lever.py
    ashby.py
config/
  companies.yaml   # your watchlist
  settings.yaml    # filter rules, AI thresholds
  profile.txt      # your candidate profile for AI evaluation
infrastructure/
  template.yaml    # AWS SAM template
Makefile           # deploy, invoke, logs, etc.
```

## Teardown

```bash
make destroy       # deletes all AWS resources
```
