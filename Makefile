.PHONY: deploy invoke-local logs tail-logs scan-table add-company build clean

STACK_NAME   := job-search-automation
REGION       := us-east-1
FUNCTION     := job-search-automation
TABLE        := jobs
SAM_TEMPLATE := infrastructure/template.yaml

# ── Build + Deploy ────────────────────────────────────────────────────────

build:
	sam build --template $(SAM_TEMPLATE)

deploy: build
	sam deploy \
		--stack-name $(STACK_NAME) \
		--region $(REGION) \
		--capabilities CAPABILITY_IAM CAPABILITY_NAMED_IAM \
		--resolve-s3

# ── Invoke locally (requires .env) ───────────────────────────────────────

invoke-local:
	@set -a && source .env && set +a && \
	python -c "from src.handler import main; print(main({}, None))"

# ── CloudWatch Logs ───────────────────────────────────────────────────────

logs:
	aws logs tail /aws/lambda/$(FUNCTION) \
		--region $(REGION) \
		--since 1h \
		--format short

tail-logs:
	aws logs tail /aws/lambda/$(FUNCTION) \
		--region $(REGION) \
		--follow \
		--format short

# ── Invoke Lambda on AWS ──────────────────────────────────────────────────

invoke:
	aws lambda invoke \
		--function-name $(FUNCTION) \
		--region $(REGION) \
		--payload '{}' \
		--cli-binary-format raw-in-base64-out \
		/tmp/lambda-response.json && cat /tmp/lambda-response.json

# ── DynamoDB helpers ──────────────────────────────────────────────────────

scan-table:
	aws dynamodb scan \
		--table-name $(TABLE) \
		--region $(REGION) \
		--output json | python -m json.tool | head -100

# ── Secrets setup (one-time) ──────────────────────────────────────────────

add-openai-key:
	@read -p "OpenAI API key: " key && \
	aws ssm put-parameter \
		--name /jobsearch/openai_key \
		--value "$$key" \
		--type SecureString \
		--overwrite \
		--region $(REGION)

add-slack-webhook:
	@read -p "Slack Webhook URL: " url && \
	aws ssm put-parameter \
		--name /jobsearch/slack_webhook \
		--value "$$url" \
		--type SecureString \
		--overwrite \
		--region $(REGION)

# ── Add a company (reminder) ──────────────────────────────────────────────

add-company:
	@echo "Edit config/companies.yaml, then run: make deploy"

# ── Cleanup ───────────────────────────────────────────────────────────────

clean:
	sam delete --stack-name $(STACK_NAME) --region $(REGION) --no-prompts

destroy: clean
