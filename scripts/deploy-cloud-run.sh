#!/usr/bin/env bash
# Build this repo on Cloud Build and deploy Streamable HTTP MCP to Cloud Run.
# Does not print secret values.
set -euo pipefail

PROJECT="${GCP_PROJECT:-project-84207120-95a7-43ac-95e}"
REGION="${GCP_REGION:-us-central1}"
SERVICE="${CLOUD_RUN_SERVICE:-onto-kb}"
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
  logging.googleapis.com \
  monitoring.googleapis.com \
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
  roles/logging.viewer \
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
ALLOWED_FOLDER="${DRIVE_ALLOWED_FOLDER_ID:-1qod47BRgPlRnXVboaJsElSNj1WkofLRQ}"
# Prefer an already-deployed origin so OAuth issuer == the URL hosts paste.
EXISTING_URL="$(gcloud run services describe "$SERVICE" --project="$PROJECT" --region="$REGION" --format='value(status.url)' 2>/dev/null || true)"
DEFAULT_PUBLIC_URL="${EXISTING_URL:-https://${SERVICE}-kxjtmypvfa-uc.a.run.app}"
CANONICAL_PUBLIC="${MCP_PUBLIC_URL:-${DEFAULT_PUBLIC_URL}}"
CANONICAL_PUBLIC="${CANONICAL_PUBLIC%/}"
DEPLOY_ENV="MCP_PUBLIC_URL=${CANONICAL_PUBLIC}"
DEPLOY_ENV="${DEPLOY_ENV},DRIVE_ALLOWED_FOLDER_ID=${ALLOWED_FOLDER}"
DEPLOY_ENV="${DEPLOY_ENV},MCP_OAUTH_AUTO_APPROVE=true"
DEPLOY_ENV="${DEPLOY_ENV},GOOGLE_CLOUD_PROJECT=${PROJECT}"
DEPLOY_ENV="${DEPLOY_ENV},MCP_STATS_FROM_LOGS=true"
DEPLOY_ARGS+=(--set-env-vars="${DEPLOY_ENV}")

echo "Deploying ${SERVICE} to Cloud Run (${REGION})..."
gcloud "${DEPLOY_ARGS[@]}"

URL="$(gcloud run services describe "$SERVICE" --project="$PROJECT" --region="$REGION" --format='value(status.url)')"
URL="${URL%/}"
if [[ "$CANONICAL_PUBLIC" != "$URL" ]]; then
  echo "Aligning MCP_PUBLIC_URL to ${URL}..."
  gcloud run services update "$SERVICE" \
    --project="$PROJECT" \
    --region="$REGION" \
    --update-env-vars="MCP_PUBLIC_URL=${URL}" \
    --quiet
fi
echo "LIVE_MCP_URL=${URL}/mcp"
echo "Ensuring connect-counter log metrics and Monitoring dashboard..."
bash "$(cd "$(dirname "$0")" && pwd)/ensure-connect-telemetry-gcp.sh"
echo "Deploy complete. Hosts use MCP OAuth 2.1 against this origin."
echo "Set LIVE_MCP_URL and MCP_AUTH_TOKEN (consent password from Secret Manager, not chat) for live E2E."
