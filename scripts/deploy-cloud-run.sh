#!/usr/bin/env bash
# Build this repo on Cloud Build and deploy Streamable HTTP MCP to Cloud Run.
# Does not print secret values.
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-84207120-95a7-43ac-95e}"
REGION="${GCP_REGION:-us-central1}"
SERVICE="${CLOUD_RUN_SERVICE:-google-drive-mcp}"
AR_REPO="${ARTIFACT_REPO:-cloud-run-source-deploy}"

need_gcloud() {
  if ! command -v gcloud >/dev/null 2>&1; then
    echo "gcloud is not on PATH. Install the Google Cloud SDK and authenticate." >&2
    exit 1
  fi
  if ! gcloud auth print-access-token >/dev/null 2>&1; then
    echo "No GCP credentials in this environment." >&2
    echo "Authenticate a deploy identity (not an OAuth refresh token) then retry." >&2
    exit 1
  fi
}

secret_exists() {
  gcloud secrets describe "$1" --project="$PROJECT" >/dev/null 2>&1
}

need_gcloud
gcloud config set project "$PROJECT" >/dev/null

echo "Enabling APIs on ${PROJECT}..."
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  drive.googleapis.com \
  --project="$PROJECT"

for name in GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET GOOGLE_REFRESH_TOKEN MCP_AUTH_TOKEN; do
  if ! secret_exists "$name"; then
    echo "Missing Secret Manager secret: ${name}" >&2
    echo "Create it (value never belongs in git or chat) and retry." >&2
    exit 1
  fi
done

if ! secret_exists MCP_PRINCIPAL_ID; then
  printf '%s' "${MCP_PRINCIPAL_ID:-throwaway-drive}" | gcloud secrets create MCP_PRINCIPAL_ID \
    --project="$PROJECT" --data-file=-
fi

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
CLOUDBUILD_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"

echo "Granting runtime SA Secret Manager access..."
for name in GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET GOOGLE_REFRESH_TOKEN MCP_AUTH_TOKEN MCP_PRINCIPAL_ID; do
  gcloud secrets add-iam-policy-binding "$name" \
    --project="$PROJECT" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet >/dev/null
done

gcloud projects add-iam-policy-binding "$PROJECT" \
  --member="serviceAccount:${CLOUDBUILD_SA}" \
  --role="roles/run.admin" \
  --quiet >/dev/null || true

echo "Deploying ${SERVICE} to Cloud Run (${REGION})..."
gcloud run deploy "$SERVICE" \
  --project="$PROJECT" \
  --region="$REGION" \
  --source="$(cd "$(dirname "$0")/.." && pwd)" \
  --allow-unauthenticated \
  --set-secrets="GOOGLE_CLIENT_ID=GOOGLE_CLIENT_ID:latest,GOOGLE_CLIENT_SECRET=GOOGLE_CLIENT_SECRET:latest,GOOGLE_REFRESH_TOKEN=GOOGLE_REFRESH_TOKEN:latest,MCP_AUTH_TOKEN=MCP_AUTH_TOKEN:latest,MCP_PRINCIPAL_ID=MCP_PRINCIPAL_ID:latest" \
  --memory=512Mi \
  --timeout=60 \
  --quiet

URL="$(gcloud run services describe "$SERVICE" --project="$PROJECT" --region="$REGION" --format='value(status.url)')"
echo "LIVE_MCP_URL=${URL}/mcp"
echo "Deploy complete. Run live E2E with LIVE_MCP_URL and MCP_AUTH_TOKEN (from Secret Manager, not chat)."
