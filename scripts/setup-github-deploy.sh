#!/usr/bin/env bash
# One-time setup so GitHub Actions can deploy onto-kb to Cloud Run without a key.
# Run it yourself (for example in Cloud Shell) as a project owner. Safe to re-run.
#
# It creates:
# - service account onto-kb-deployer, with only what scripts/deploy-cloud-run.sh
#   needs when ONE_TIME_SETUP=0: run.admin on the onto-kb service alone, read-only
#   Cloud Run and secret metadata in the project, Cloud Build, the source bucket,
#   the image repository, the kb folder-id secret, and actAs on the runtime account;
# - Workload Identity Federation pool onto-kb-github, whose provider accepts only
#   this repository (by numeric id, which survives renames and cannot be reused),
#   the main branch, and jobs in the GitHub environment "production".
# It prints the GitHub variables to add. Does not print secret values.
set -euo pipefail

PROJECT="${GCP_PROJECT:-$(gcloud config get-value project 2>/dev/null || true)}"
if [[ -z "$PROJECT" ]]; then
  echo "Set GCP_PROJECT or run: gcloud config set project <project-id>" >&2
  exit 1
fi
REGION="${GCP_REGION:-us-central1}"
SERVICE="${CLOUD_RUN_SERVICE:-onto-kb}"
AR_REPO="${ARTIFACT_REPO:-cloud-run-source-deploy}"
# github.com/wildfly8/google-drive-mcp (public repository id).
REPO_ID="${GITHUB_REPOSITORY_ID:-1369539999}"
POOL="onto-kb-github"
PROVIDER="github"
SA_NAME="onto-kb-deployer"

NUMBER="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')"
SA="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
RUNTIME_SA="${NUMBER}-compute@developer.gserviceaccount.com"

gcloud services enable iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com \
  --project="$PROJECT"

if ! gcloud iam service-accounts describe "$SA" --project="$PROJECT" >/dev/null 2>&1; then
  gcloud iam service-accounts create "$SA_NAME" --project="$PROJECT" \
    --display-name="onto-kb GitHub deploy (main, production environment)"
fi

if ! gcloud iam workload-identity-pools describe "$POOL" --project="$PROJECT" \
  --location=global >/dev/null 2>&1; then
  gcloud iam workload-identity-pools create "$POOL" --project="$PROJECT" --location=global \
    --display-name="onto-kb GitHub Actions"
fi
CONDITION="assertion.repository_id=='${REPO_ID}' && assertion.ref=='refs/heads/main' && assertion.environment=='production'"
MAPPING="google.subject=assertion.sub,attribute.repository_id=assertion.repository_id,attribute.ref=assertion.ref,attribute.environment=assertion.environment"
if gcloud iam workload-identity-pools providers describe "$PROVIDER" --project="$PROJECT" \
  --location=global --workload-identity-pool="$POOL" >/dev/null 2>&1; then
  gcloud iam workload-identity-pools providers update-oidc "$PROVIDER" --project="$PROJECT" \
    --location=global --workload-identity-pool="$POOL" \
    --attribute-mapping="$MAPPING" --attribute-condition="$CONDITION"
else
  gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" --project="$PROJECT" \
    --location=global --workload-identity-pool="$POOL" \
    --display-name="onto-kb GitHub (main, prod)" \
    --issuer-uri="https://token.actions.githubusercontent.com" \
    --attribute-mapping="$MAPPING" --attribute-condition="$CONDITION"
fi

echo "Letting only that repository's production jobs act as ${SA_NAME}..."
gcloud iam service-accounts add-iam-policy-binding "$SA" --project="$PROJECT" \
  --role=roles/iam.workloadIdentityUser \
  --member="principalSet://iam.googleapis.com/projects/${NUMBER}/locations/global/workloadIdentityPools/${POOL}/attribute.repository_id/${REPO_ID}" \
  --quiet >/dev/null

echo "Granting the deploy account what a deploy needs, and no more..."
# Deploy, update, traffic and revision clean-up of this one service.
gcloud run services add-iam-policy-binding "$SERVICE" --project="$PROJECT" --region="$REGION" \
  --member="serviceAccount:${SA}" --role=roles/run.admin --quiet >/dev/null
# Read-only project roles: list revisions, submit the build, use APIs, see secret names.
for role in roles/run.viewer roles/cloudbuild.builds.editor \
  roles/serviceusage.serviceUsageConsumer roles/secretmanager.viewer; do
  gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:${SA}" \
    --role="$role" --condition=None --quiet >/dev/null
done
# Deploy as, and build as, the runtime account (Cloud Run source deploys build with it).
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" --project="$PROJECT" \
  --member="serviceAccount:${SA}" --role=roles/iam.serviceAccountUser --quiet >/dev/null
# Upload the source and read the image repository.
gcloud storage buckets add-iam-policy-binding "gs://run-sources-${PROJECT}-${REGION}" \
  --member="serviceAccount:${SA}" --role=roles/storage.admin --quiet >/dev/null
gcloud artifacts repositories add-iam-policy-binding "$AR_REPO" --project="$PROJECT" \
  --location="$REGION" --member="serviceAccount:${SA}" --role=roles/artifactregistry.reader \
  --quiet >/dev/null
# The deploy pins the kb folder id from this one secret.
gcloud secrets add-iam-policy-binding DRIVE_ALLOWED_FOLDER_ID --project="$PROJECT" \
  --member="serviceAccount:${SA}" --role=roles/secretmanager.secretAccessor --quiet >/dev/null

cat <<EOF

Done. In GitHub, repository Settings:
1. Environments -> New environment "production":
   - Required reviewers: yourself (each deploy then waits for your approval).
   - Deployment branches and tags: Selected branches -> main.
2. Secrets and variables -> Actions -> Variables -> New repository variable:
   GCP_PROJECT_ID      ${PROJECT}
   GCP_PROJECT_NUMBER  ${NUMBER}
   GCP_REGION          ${REGION}
   GCP_WIF_PROVIDER    projects/${NUMBER}/locations/global/workloadIdentityPools/${POOL}/providers/${PROVIDER}
   GCP_DEPLOY_SA       ${SA}
The next push to main runs CI, then the deploy job waits for your approval.
EOF
