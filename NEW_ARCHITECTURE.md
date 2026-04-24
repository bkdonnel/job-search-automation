# Remote MCP Server — Browser Access via Claude.ai

## Overview

Move `mcp_server.py` from a local Claude Code process to a hosted EC2 server so the job search tools (DynamoDB queries, resume tailoring, company management) are accessible from Claude.ai in any browser.

## Architecture

```
Browser (claude.ai)
       |
       | HTTPS + Bearer token
       |
  EC2 t4g.nano (us-east-1)
    ├── Caddy (reverse proxy + auto HTTPS)
    ├── mcp_server.py (SSE transport, port 8000)
    └── systemd (keeps it running)
       |
       ├── DynamoDB ──── query jobs
       ├── Lambda ─────── trigger scan
       ├── SSM ─────────── secrets + token.json
       └── Google Drive/Gmail
```

---

## Code Changes to mcp_server.py

### 1. Switch from stdio to SSE transport

```python
# Current (stdio — works with Claude Code only)
mcp.run()

# New (SSE — works with Claude.ai browser)
mcp.run(transport="sse", host="0.0.0.0", port=8000)
```

### 2. Add bearer token auth

```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        token = request.headers.get("Authorization", "")
        if token != f"Bearer {os.environ['MCP_SECRET']}":
            return Response("Unauthorized", status_code=401)
        return await call_next(request)

mcp.app.add_middleware(AuthMiddleware)
```

### 3. Load `token.json` from SSM instead of local file

```python
def _get_token_json():
    ssm = boto3.client("ssm", region_name="us-east-1")
    value = ssm.get_parameter(Name="/jobsearch/google_token", WithDecryption=True)
    return json.loads(value["Parameter"]["Value"])

def _save_token_json(creds):
    ssm = boto3.client("ssm", region_name="us-east-1")
    ssm.put_parameter(
        Name="/jobsearch/google_token",
        Value=creds.to_json(),
        Type="SecureString",
        Overwrite=True,
    )
```

---

## EC2 Setup (one-time)

### Launch instance

- Type: `t4g.nano` (us-east-1)
- Attach an IAM instance profile with:
  - `DynamoDB`: GetItem, Query, Scan on `jobs` table
  - `Lambda`: InvokeFunction on `job-search-automation`
  - `SSM`: GetParameter, PutParameter on `/jobsearch/*`

### Install dependencies

```bash
sudo apt install python3-pip caddy -y
pip install mcp[cli] google-api-python-client google-auth-oauthlib boto3 requests pyyaml
```

### Upload files

```bash
scp mcp_server.py config/companies.yaml ec2-user@<ip>:~/job-search/
```

### Store Google OAuth token in SSM (run once from laptop)

```bash
aws ssm put-parameter \
  --name /jobsearch/google_token \
  --value "$(cat token.json)" \
  --type SecureString
```

### Caddyfile (auto HTTPS)

```
your-domain.com {
    reverse_proxy localhost:8000
}
```

### systemd service

Create `/etc/systemd/system/mcp.service`:

```ini
[Unit]
Description=Job Search MCP Server
After=network.target

[Service]
WorkingDirectory=/home/ec2-user/job-search
ExecStart=python3 mcp_server.py
Restart=always
Environment=MCP_SECRET=your-secret-token

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable mcp && sudo systemctl start mcp
```

---

## Claude.ai Configuration

In Claude.ai → Settings → Integrations → Add MCP Server:

```
URL:    https://your-domain.com/sse
Header: Authorization: Bearer your-secret-token
```

---

## The One Tricky Part: `companies.yaml`

Currently `add_company` edits a local file and requires `make deploy` to push changes to Lambda. On EC2 the file lives on the instance, disconnected from the git repo. Options:

| Approach | Effort | Notes |
|----------|--------|-------|
| Edit file on EC2, SSH in to deploy | Low | Manual, not ideal |
| Store in S3, Lambda + MCP server both read from it | Medium | Recommended — no deploy needed to add companies |
| Commit to GitHub, trigger SAM deploy via CodePipeline | High | Fully automated but significant new infrastructure |

**Recommended:** S3 approach. `add_company` writes to S3, Lambda reads from S3 on each invocation instead of the bundled file.

---

## Effort Estimate

| Task | Effort |
|------|--------|
| mcp_server.py changes (SSE + auth + SSM token) | ~1-2 hours |
| EC2 launch + IAM role | ~30 min |
| Caddy + systemd setup | ~30 min |
| Domain setup | ~15 min |
| Move `companies.yaml` to S3 (recommended) | ~1-2 hours |
