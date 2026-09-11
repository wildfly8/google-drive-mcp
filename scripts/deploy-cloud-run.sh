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

if ! secret_exists MCP_AUTH_TOKEN; then
  echo "Missing Secret Manager secret: MCP_AUTH_TOKEN" >&2
  exit 1
fi
if secret_exists GOOGLE_AUTHORIZED_USER_JSON; then
  :
elif secret_exists GOOGLE_REFRESH_TOKEN && secret_exists GOOGLE_CLIENT_ID && secret_exists GOOGLE_CLIENT_SECRET; then
  :
else
  echo "Need GOOGLE_AUTHORIZED_USER_JSON, or GOOGLE_REFRESH_TOKEN plus OAuth client secrets." >&2
  exit 1
fi

if ! secret_exists MCP_PRINCIPAL_ID; then
  printf '%s' "${MCP_PRINCIPAL_ID:-throwaway-drive}" | gcloud secrets create MCP_PRINCIPAL_ID \
    --project="$PROJECT" --data-file=-
fi

PROJECT_NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
CLOUDBUILD_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"

SECRET_BIND="MCP_AUTH_TOKEN=MCP_AUTH_TOKEN:latest,MCP_PRINCIPAL_ID=MCP_PRINCIPAL_ID:latest"
GRANT_SECRETS=(MCP_AUTH_TOKEN MCP_PRINCIPAL_ID)
if secret_exists GOOGLE_AUTHORIZED_USER_JSON; then
  SECRET_BIND="${SECRET_BIND},GOOGLE_AUTHORIZED_USER_JSON=GOOGLE_AUTHORIZED_USER_JSON:latest"
  GRANT_SECRETS+=(GOOGLE_AUTHORIZED_USER_JSON)
fi
if secret_exists GOOGLE_CLIENT_ID; then
  SECRET_BIND="${SECRET_BIND},GOOGLE_CLIENT_ID=GOOGLE_CLIENT_ID:latest"
  GRANT_SECRETS+=(GOOGLE_CLIENT_ID)
fi
if secret_exists GOOGLE_CLIENT_SECRET; then
  SECRET_BIND="${SECRET_BIND},GOOGLE_CLIENT_SECRET=GOOGLE_CLIENT_SECRET:latest"
  GRANT_SECRETS+=(GOOGLE_CLIENT_SECRET)
fi
if secret_exists GOOGLE_REFRESH_TOKEN; then
  SECRET_BIND="${SECRET_BIND},GOOGLE_REFRESH_TOKEN=GOOGLE_REFRESH_TOKEN:latest"
  GRANT_SECRETS+=(GOOGLE_REFRESH_TOKEN)
fi

echo "Granting runtime SA Secret Manager access..."
for name in "${GRANT_SECRETS[@]}"; do
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

echo "Granting Cloud Build compute SA storage and Artifact Registry access..."
for role in \
  roles/storage.objectViewer \
  roles/artifactregistry.writer \
  roles/logging.logWriter \
  roles/cloudbuild.builds.builder; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="$role" \
    --quiet >/dev/null || true
done

DEPLOY_ARGS=(
  run deploy "$SERVICE"
  --project="$PROJECT"
  --region="$REGION"
  --source="$(cd "$(dirname "$0")/.." && pwd)"
  --allow-unauthenticated
  --set-secrets="${SECRET_BIND}"
  --memory=512Mi
  --timeout=60
  --quiet
)
if [[ -n "${DRIVE_ALLOWED_FOLDER_ID:-}" ]]; then
  DEPLOY_ARGS+=(--set-env-vars="DRIVE_ALLOWED_FOLDER_ID=${DRIVE_ALLOWED_FOLDER_ID}")
fi

echo "Deploying ${SERVICE} to Cloud Run (${REGION})..."
gcloud "${DEPLOY_ARGS[@]}"

URL="$(gcloud run services describe "$SERVICE" --project="$PROJECT" --region="$REGION" --format='value(status.url)')"
echo "LIVE_MCP_URL=${URL}/mcp"
echo "Deploy complete. Run live E2E with LIVE_MCP_URL and MCP_AUTH_TOKEN (from Secret Manager, not chat)."
