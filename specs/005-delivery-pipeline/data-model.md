# Data Model: 005 Delivery Pipeline

Placeholders: `<project-id>`, `<project-number>`, `<region>` (default `us-central1`). Real values live only in the Google Cloud project and the GitHub repository settings.

## Deploy settings (GitHub, Settings → Secrets and variables → Actions)

| Name | Kind (since 6fa3143) | Value | Used by |
| --- | --- | --- | --- |
| `GCP_PROJECT_ID` | secret | `<project-id>` | deploy and smoke test (`GCP_PROJECT`); masked |
| `GCP_PROJECT_NUMBER` | secret | `<project-number>` | masked only |
| `GCP_WIF_PROVIDER` | secret | `projects/<project-number>/locations/global/workloadIdentityPools/onto-kb-github/providers/github` | sign-in |
| `GCP_DEPLOY_SA` | secret | `onto-kb-deployer@<project-id>.iam.gserviceaccount.com` | sign-in; masked |
| `GCP_REGION` | variable | `<region>` | turns the `deploy` job on (skipped when empty); deploy and smoke test |

None of them grants access. The four identifiers are secrets because GitHub masks secrets in every log line, while a variable shows once in the mask step's header (T015). The workflow still falls back to a variable of the same name when the secret is missing; delete such variables once the secrets exist.

## Production environment (GitHub)

- Name: `production`
- Required reviewer: none, by the owner's decision of 2026-10-01 (FR-005). One can be added back without a code change.
- Deployment branches: `main` only
- Environment secrets and variables: none needed (the job reads repository secrets and variables)

## OIDC token claims used by Google

| Claim | Mapped to | Required value |
| --- | --- | --- |
| `sub` | `google.subject` | any (not checked) |
| `repository_id` | `attribute.repository_id` | `1369539999` |
| `ref` | `attribute.ref` | `refs/heads/main` |
| `environment` | `attribute.environment` | `production` |

Pool `onto-kb-github`, provider `github`, issuer `https://token.actions.githubusercontent.com`, state ACTIVE. Impersonation: `principalSet://iam.googleapis.com/projects/<project-number>/locations/global/workloadIdentityPools/onto-kb-github/attribute.repository_id/1369539999` holds `roles/iam.workloadIdentityUser` on the deploy account, and no other principal does.

## Deploy account role bindings

`onto-kb-deployer@<project-id>.iam.gserviceaccount.com`

| Role | Scope | For |
| --- | --- | --- |
| `roles/run.admin` | service `onto-kb` | deploy, update, traffic, invoker policy |
| `roles/run.viewer` | project | describe the service, list and describe revisions |
| `roles/cloudbuild.builds.editor` | project | submit the source build |
| `roles/serviceusage.serviceUsageConsumer` | project | call the enabled APIs |
| `roles/secretmanager.viewer` | project | check which secrets exist (no values) |
| custom `ontoKbDeployExtras` (`storage.buckets.list`, `run.revisions.delete`; 6fa3143) | project | list bucket names before the source upload; delete revisions that serve no traffic (T016) |
| `roles/iam.serviceAccountUser` | runtime account `<project-number>-compute@developer.gserviceaccount.com` | deploy and build as it |
| `roles/storage.admin` | bucket `run-sources-<project-id>-<region>` | upload the source |
| `roles/artifactregistry.reader` | repository `cloud-run-source-deploy` | read the image repository |
| `roles/secretmanager.secretAccessor` | secret `DRIVE_ALLOWED_FOLDER_ID` | read the `kb` folder id |

No user-managed key.

## Runtime account (granted by a manual deploy, `ONE_TIME_SETUP=1`)

- `roles/secretmanager.secretAccessor` on each bound secret
- Project `roles/storage.objectViewer`, `roles/artifactregistry.writer`, `roles/logging.logWriter`, `roles/logging.viewer`, `roles/cloudbuild.builds.builder`
- The Cloud Build account `<project-number>@cloudbuild.gserviceaccount.com` gets project `roles/run.admin` (best effort)

## Deploy job states

```text
queued ──(test or image failed)──────────────▶ skipped
queued ──(not a push to main, or no GCP_REGION)──▶ skipped
queued ──(test and image passed, another deploy holds deploy-production)──▶ pending
pending ──(a newer deploy becomes pending)──▶ cancelled, nothing deployed
queued or pending ──(group free; no required reviewer, the current setting)──▶ running
queued or pending ──(group free; required reviewer added back)──▶ waiting for review
waiting for review ──(owner rejects, or GitHub's wait limit)──▶ failed, nothing deployed
waiting for review ──(owner approves)──▶ running
running ──(sign-in, preflight, refusal, source upload, build, start, kb guard or cleanup fails)──▶ failed
running ──(deploy script and smoke test pass)──▶ succeeded
```

The `pending` and `cancelled` transitions are GitHub's documented concurrency behavior, not yet observed here. The `waiting for review` states apply only if a required reviewer is added back.

## Revision lifecycle in one deploy

```text
upload the source ──fail──▶ stop; previous revision keeps traffic (run 16)
build (Cloud Build) ──fail──▶ stop; previous revision keeps traffic
deploy new revision ──does not become ready──▶ stop; previous revision keeps traffic
MCP_PUBLIC_URL differs from the service URL (first deploy, or an operator override)? ──yes──▶ align it (one more revision)
newest ready revision carries pinned kb id? ──no──▶ stop before the traffic change and cleanup
all traffic to latest, clear tags
delete every other revision ──any refused──▶ stop, name them
smoke test ──fail──▶ job fails; the new revision is the only one
```

## Secrets read or bound by the deploy (names only)

| Secret | Required | How |
| --- | --- | --- |
| `MCP_AUTH_TOKEN` | yes | bound |
| `MCP_PRINCIPAL_ID` | yes (created by a manual deploy when missing) | bound |
| `GOOGLE_AUTHORIZED_USER_JSON`, or `GOOGLE_REFRESH_TOKEN` + `GOOGLE_CLIENT_ID` + `GOOGLE_CLIENT_SECRET` | one of the two | bound |
| `DRIVE_ALLOWED_FOLDER_ID` | yes; must match `^[A-Za-z0-9_-]{10,128}$` | read by the deploy, set as an environment variable |
| `STRIPE_SECRET_KEY`, `STRIPE_PRICE_ID` | yes (paywall) | bound |
| `STRIPE_WEBHOOK_SECRET`, `IDENTITY_TOOLKIT_API_KEY` | no | bound when present |

## Relationships

Push to `main` → run → `test` + `image` pass → `deploy` starts → GitHub OIDC token (repository id, ref, environment) → Google STS checks the provider condition → short-lived deploy account token → deploy script → Cloud Build (as the runtime account) → Cloud Run revision (runs as the runtime account, reads the bound secrets) → `kb` guard and cleanup → smoke test.
