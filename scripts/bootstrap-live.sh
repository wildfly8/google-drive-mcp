#!/usr/bin/env bash
# Completes Cloud Run deploy + live E2E after `gcloud auth login`.
# Creates missing MCP bearer; reads OAuth client secrets already in Secret Manager.
# Never prints secret values.
set -euo pipefail

export PATH="/tmp/google-cloud-sdk/bin:${HOME}/.local/bin:${PATH}"
PROJECT="${GCP_PROJECT:-project-84207120-95a7-43ac-95e}"
REGION="${GCP_REGION:-us-central1}"
SERVICE="${CLOUD_RUN_SERVICE:-google-drive-mcp}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! gcloud auth print-access-token >/dev/null 2>&1; then
  echo "Not signed into Google Cloud yet." >&2
  exit 2
fi

gcloud config set project "$PROJECT" >/dev/null
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  drive.googleapis.com \
  --project="$PROJECT"

secret_exists() {
  gcloud secrets describe "$1" --project="$PROJECT" >/dev/null 2>&1
}

put_secret() {
  local name="$1"
  if secret_exists "$name"; then
    gcloud secrets versions add "$name" --project="$PROJECT" --data-file=- >/dev/null
  else
    gcloud secrets create "$name" --project="$PROJECT" --data-file=- >/dev/null
  fi
}

if ! secret_exists GOOGLE_CLIENT_ID || ! secret_exists GOOGLE_CLIENT_SECRET; then
  echo "Expected GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in Secret Manager." >&2
  exit 1
fi

if ! secret_exists MCP_AUTH_TOKEN; then
  openssl rand -base64 32 | tr -d '\n' | put_secret MCP_AUTH_TOKEN
fi
if ! secret_exists MCP_PRINCIPAL_ID; then
  printf '%s' "throwaway-drive" | put_secret MCP_PRINCIPAL_ID
fi

if ! secret_exists GOOGLE_REFRESH_TOKEN; then
  echo "A one-time Drive consent URL will print next. Open it, click Allow, paste the code."
  # google-auth-oauthlib is not a runtime dep; install into the project venv.
  .venv/bin/pip install -q google-auth-oauthlib
  export OAUTH_CONSOLE=1
  export GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET
  GOOGLE_CLIENT_ID="$(gcloud secrets versions access latest --secret=GOOGLE_CLIENT_ID --project="$PROJECT")"
  GOOGLE_CLIENT_SECRET="$(gcloud secrets versions access latest --secret=GOOGLE_CLIENT_SECRET --project="$PROJECT")"
  TOKEN="$("$ROOT/.venv/bin/python" "$ROOT/scripts/mint-google-refresh-token.py")"
  printf '%s' "$TOKEN" | put_secret GOOGLE_REFRESH_TOKEN
  unset TOKEN GOOGLE_CLIENT_SECRET GOOGLE_CLIENT_ID
fi

bash "$ROOT/scripts/deploy-cloud-run.sh"

URL="$(gcloud run services describe "$SERVICE" --project="$PROJECT" --region="$REGION" --format='value(status.url)')"
export LIVE_MCP_URL="${URL}/mcp"
export MCP_AUTH_TOKEN
MCP_AUTH_TOKEN="$(gcloud secrets versions access latest --secret=MCP_AUTH_TOKEN --project="$PROJECT")"
echo "LIVE_MCP_URL=${LIVE_MCP_URL}"
.venv/bin/python -m pytest -q tests/e2e/test_live_mcp.py --tb=short
unset MCP_AUTH_TOKEN
