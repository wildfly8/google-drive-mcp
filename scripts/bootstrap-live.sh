#!/usr/bin/env bash
# Completes Cloud Run deploy + live E2E after `gcloud auth login`.
# Reuses application-default credentials as GOOGLE_AUTHORIZED_USER_JSON
# so Drive consent is not requested a second time.
# Never prints secret values.
set -euo pipefail

export PATH="/tmp/google-cloud-sdk/bin:${HOME}/.local/bin:${PATH}"
PROJECT="${GCP_PROJECT:-project-84207120-95a7-43ac-95e}"
REGION="${GCP_REGION:-us-central1}"
SERVICE="${CLOUD_RUN_SERVICE:-google-drive-mcp}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ADC="${GOOGLE_APPLICATION_CREDENTIALS:-${HOME}/.config/gcloud/application_default_credentials.json}"
cd "$ROOT"

if ! gcloud auth print-access-token >/dev/null 2>&1; then
  echo "Not signed into Google Cloud yet." >&2
  exit 2
fi

gcloud config set project "$PROJECT" >/dev/null
gcloud auth application-default set-quota-project "$PROJECT" >/dev/null 2>&1 || true
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

put_secret_file() {
  local name="$1"
  local file="$2"
  if secret_exists "$name"; then
    gcloud secrets versions add "$name" --project="$PROJECT" --data-file="$file" >/dev/null
  else
    gcloud secrets create "$name" --project="$PROJECT" --data-file="$file" >/dev/null
  fi
}

if ! secret_exists MCP_AUTH_TOKEN; then
  openssl rand -base64 32 | tr -d '\n' | put_secret MCP_AUTH_TOKEN
fi
if ! secret_exists MCP_PRINCIPAL_ID; then
  printf '%s' "throwaway-drive" | put_secret MCP_PRINCIPAL_ID
fi

if [[ -f "$ADC" ]]; then
  put_secret_file GOOGLE_AUTHORIZED_USER_JSON "$ADC"
elif secret_exists GOOGLE_AUTHORIZED_USER_JSON || secret_exists GOOGLE_REFRESH_TOKEN; then
  :
else
  echo "No application-default credentials file and no Drive refresh secret." >&2
  exit 1
fi

bash "$ROOT/scripts/deploy-cloud-run.sh"

URL="$(gcloud run services describe "$SERVICE" --project="$PROJECT" --region="$REGION" --format='value(status.url)')"
export LIVE_MCP_URL="${URL}/mcp"
export MCP_AUTH_TOKEN
MCP_AUTH_TOKEN="$(gcloud secrets versions access latest --secret=MCP_AUTH_TOKEN --project="$PROJECT")"
echo "LIVE_MCP_URL=${LIVE_MCP_URL}"
.venv/bin/python -m pytest -q tests/e2e/test_live_mcp.py --tb=short
unset MCP_AUTH_TOKEN
