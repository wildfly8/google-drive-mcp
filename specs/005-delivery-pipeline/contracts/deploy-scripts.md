# Contract: Deploy Scripts

Both scripts run with `set -euo pipefail`: any failing command stops them with a non-zero exit. Neither prints a secret value.

## `scripts/deploy-cloud-run.sh`

Builds the repository on Cloud Build and deploys it to the Cloud Run service. Used by the CI `deploy` job and by the owner by hand. Pinned by `tests/unit/test_deploy_preflight.py`.

### Inputs (environment variables)

| Variable | Default | Meaning |
| --- | --- | --- |
| `GCP_PROJECT` | `gcloud config get-value project` | Project id. Stops when neither is set. |
| `GCP_REGION` | `us-central1` | Region of the service. |
| `CLOUD_RUN_SERVICE` | `onto-kb` | Service name. |
| `ARTIFACT_REPO` | `cloud-run-source-deploy` | Read but not used by this script (the setup script uses it). |
| `ONE_TIME_SETUP` | `1` | `0` skips everything only an owner may run (below). The CI deploy sets `0`. |
| `ALLOW_DIRTY` | `0` | `1` skips the clean-tree check. |
| `SKIP_TESTS` | `0` | `1` skips the test run. The CI deploy sets `1`. |
| `MCP_PUBLIC_URL` | the service's current URL | Public origin. Realigned to the service's real URL whenever the two differ (as on a first deploy). |
| `MCP_PRINCIPAL_ID` | `throwaway-drive` | Value for the secret when a manual deploy creates it. |
| `CLOUD_RUN_CONCURRENCY` | `10` | Requests per instance. |
| `CLOUD_RUN_MAX_INSTANCES` | `3` | Instance ceiling (the cost ceiling). |

`DRIVE_ALLOWED_FOLDER_ID` in the shell is ignored. The `kb` folder id comes only from the Secret Manager secret of that name.

### Steps, in order

1. **Preflight** (before any gcloud call that reaches the project; only `gcloud config get-value project` runs earlier, when `GCP_PROJECT` is unset):
   - Unless `ALLOW_DIRTY=1`: `git status --porcelain` of the repository root must be empty (no modified, staged or untracked files; git-ignored files such as `gha-creds-*.json` do not count). Otherwise: `Uncommitted changes in <root>. Commit them, or set ALLOW_DIRTY=1.` If git status cannot be read: stop too.
   - Unless `SKIP_TESTS=1`, and only when `uv` is on `PATH`: `uv run --locked pytest -q --ignore=tests/e2e`. A stale `uv.lock` or a failing test: `Tests failed. Not deploying.`
2. **gcloud ready**: `gcloud` on `PATH` and `gcloud auth print-access-token` works; otherwise stop. Sets the gcloud project.
3. **One-time setup, part 1** (`ONE_TIME_SETUP=1` only): enable Cloud Run, Artifact Registry, Cloud Build, Secret Manager, Drive, Logging and Monitoring APIs.
4. **Required secrets** (by name, `gcloud secrets describe`):
   - `MCP_AUTH_TOKEN`, else stop.
   - `GOOGLE_AUTHORIZED_USER_JSON`, or all of `GOOGLE_REFRESH_TOKEN`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, else stop.
   - `MCP_PRINCIPAL_ID`: with `ONE_TIME_SETUP=0`, stop (`Run one deploy with ONE_TIME_SETUP=1.`); otherwise create it.
5. **Bind secrets** as environment variables of the same name: the required ones, plus each of the Google OAuth secrets, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID` and `IDENTITY_TOOLKIT_API_KEY` that exists (`:latest`).
6. **One-time setup, part 2** (`ONE_TIME_SETUP=1` only): describe the project for its number; grant the runtime account `secretAccessor` on each bound secret; grant the Cloud Build account project `run.admin` and the runtime account project `storage.objectViewer`, `artifactregistry.writer`, `logging.logWriter`, `logging.viewer` and `cloudbuild.builds.builder` (these project grants are best effort; a failing secret grant stops the script).
7. **`kb` pin**: the secret `DRIVE_ALLOWED_FOLDER_ID` must exist and its latest value must match `^[A-Za-z0-9_-]{10,128}$`; otherwise stop. The value is not printed.
8. **Paywall**: both `STRIPE_SECRET_KEY` and `STRIPE_PRICE_ID` must exist; otherwise stop (`Refusing to deploy without the paywall.`).
9. **Deploy**: `gcloud run deploy <service> --source=<repository root> --allow-unauthenticated --set-secrets=… --memory=1Gi --concurrency=<CLOUD_RUN_CONCURRENCY> --max-instances=<CLOUD_RUN_MAX_INSTANCES> --timeout=60 --set-env-vars=MCP_PUBLIC_URL=…,DRIVE_ALLOWED_FOLDER_ID=<kb id>,MCP_OAUTH_AUTO_APPROVE=true,GOOGLE_CLOUD_PROJECT=<project>,MCP_STATS_FROM_LOGS=true,MCP_SUBSCRIPTION_REQUIRED=true --quiet`. `--set-env-vars` replaces the whole environment. The upload leaves out what `.gcloudignore` lists (`.git`, `.github`, git-ignored files, `gha-creds-*.json`).
10. **Align the URL**: when `MCP_PUBLIC_URL` differs from the service URL (a first deploy, or an operator's `MCP_PUBLIC_URL` override), update that one variable (one more revision).
11. **`kb` guard**: the service's `latestReadyRevisionName` must exist and its `DRIVE_ALLOWED_FOLDER_ID` must equal the pinned id; otherwise stop.
12. **Traffic**: `gcloud run services update-traffic --to-latest --clear-tags`.
13. **Cleanup**: list the service's revisions. If the list does not include the newest one, stop. Delete every other revision; collect the ones that fail. If any failed: print them, say to remove their traffic and delete them by hand, and exit non-zero.
14. Print `LIVE_MCP_URL=<service-url>/mcp`.
15. **One-time setup, part 3** (`ONE_TIME_SETUP=1` only): run `scripts/ensure-connect-telemetry-gcp.sh` (log-based metrics `onto_kb_oauth_connects`, `onto_kb_drive_first_uses` and the dashboard **onto-kb connect counter**).

### What `ONE_TIME_SETUP=0` skips

API enabling (step 3), creating `MCP_PRINCIPAL_ID` (step 4), the project lookup and every IAM grant (step 6), and the telemetry metrics and dashboard (step 15). Proven by `test_ci_mode_never_enables_apis_or_grants_iam`: no `services enable`, `add-iam-policy-binding` or `projects describe` call.

### Exit behaviour

- `0`: deployed, guarded, cleaned up.
- Non-zero with a message on stderr: any refusal above, any failing gcloud call, or a revision left behind. A refusal in steps 1–8 happens before the build, so production is unchanged. A failure in step 9 leaves the previous revision serving. A failure in steps 10–13 happens after the new revision is live.

## `scripts/setup-github-deploy.sh`

One-time setup so the CI `deploy` job can deploy without a key. Run by a project owner (for example in Cloud Shell). Safe to re-run.

### Inputs (environment variables)

| Variable | Default | Meaning |
| --- | --- | --- |
| `GCP_PROJECT` | `gcloud config get-value project` | Project id. Stops when neither is set. |
| `GCP_REGION` | `us-central1` | Region of the service, bucket and image repository. |
| `CLOUD_RUN_SERVICE` | `onto-kb` | Service the deploy account may administer. |
| `ARTIFACT_REPO` | `cloud-run-source-deploy` | Image repository the deploy account may read. |
| `GITHUB_REPOSITORY_ID` | `1369539999` | Numeric id of `wildfly8/google-drive-mcp`. |

### Prerequisites

A manual deploy has run, so the service, the bucket `run-sources-<project-id>-<region>`, the image repository and the secret `DRIVE_ALLOWED_FOLDER_ID` exist. Otherwise a grant fails and the script stops; re-run it after the deploy.

### What it creates or updates

1. Enables `iam`, `iamcredentials` and `sts` APIs.
2. Service account `onto-kb-deployer` (when missing).
3. Workload identity pool `onto-kb-github` (when missing).
4. OIDC provider `github` with issuer `https://token.actions.githubusercontent.com`, display name `onto-kb GitHub (main, prod)` (at most 32 characters, 3ec59e8), attribute mapping `google.subject=assertion.sub`, `attribute.repository_id`, `attribute.ref`, `attribute.environment`, and condition `assertion.repository_id=='<id>' && assertion.ref=='refs/heads/main' && assertion.environment=='production'`. When the provider exists, the mapping and condition are updated, so a re-run restores them.
5. Project custom role `ontoKbDeployExtras` with only `storage.buckets.list` and `run.revisions.delete` (6fa3143); when it exists, its permissions are reset to those two.

### What it grants

- `roles/iam.workloadIdentityUser` on the deploy account to `principalSet://…/workloadIdentityPools/onto-kb-github/attribute.repository_id/<id>`.
- The deploy account roles in [data-model.md](../data-model.md): `run.admin` on the service; project `run.viewer`, `cloudbuild.builds.editor`, `serviceusage.serviceUsageConsumer`, `secretmanager.viewer` and `ontoKbDeployExtras` (unconditional bindings); `iam.serviceAccountUser` on the runtime account; `storage.admin` on the source bucket; `artifactregistry.reader` on the image repository; `secretmanager.secretAccessor` on `DRIVE_ALLOWED_FOLDER_ID`.

It never removes a binding and never creates a key.

### Output

The GitHub steps and the values to enter, printed to the owner's own terminal: environment `production` with `main` as the only deployment branch; Actions secrets `GCP_PROJECT_ID`, `GCP_PROJECT_NUMBER`, `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA`; the variable `GCP_REGION`; and a reminder to delete variables of the four secret names. The values do not grant access but do not belong in the public repository or its logs.

Since 6fa3143 the output calls the required reviewer optional ("without one, a push to main deploys as soon as the test and image jobs pass"). That matches FR-005: the owner chose no reviewer.

### Exit behaviour

`0` when every step succeeded. Non-zero at the first failing gcloud call. Because each create is guarded and each grant is idempotent, re-running after a fix finishes the setup.

## `scripts/ensure-connect-telemetry-gcp.sh` (operator step)

Creates or updates the 003 log-based metrics and the Cloud Monitoring dashboard. Run by a manual deploy with `ONE_TIME_SETUP=1`, or by hand. The CI deploy never runs it: it enables APIs and writes monitoring configuration, which the deploy account may not do.
