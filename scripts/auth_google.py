"""One-time Google Drive OAuth authorization.

Reads credentials.json from the repo root, opens a browser for you to approve
access, then saves token.json. Only needs to be run once.

Usage:
    python scripts/auth_google.py
"""
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/drive"]
REPO_ROOT = Path(__file__).parent.parent

credentials_path = REPO_ROOT / "credentials.json"
token_path = REPO_ROOT / "token.json"

if not credentials_path.exists():
    raise FileNotFoundError(
        "credentials.json not found in repo root. "
        "Download it from Google Cloud Console → APIs & Services → Credentials."
    )

flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
creds = flow.run_local_server(port=0)

token_path.write_text(creds.to_json())
print(f"Authorization complete. Token saved to {token_path}")
