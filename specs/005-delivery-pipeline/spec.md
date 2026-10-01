# Feature Specification: Delivery Pipeline (CI and Deploy to Cloud Run)

**Branch**: `main`

**Spec directory**: `specs/005-delivery-pipeline`

**Created**: 2026-10-01

**Status**: Implemented. The `test` and `image` jobs run on every push and pull request. The first pipeline deploy completed in run 17 (6fa3143): upload, build, deploy, `kb` guard, revision cleanup and smoke test passed. Runs 15 and 16 had stopped at the clean-tree preflight (fixed in e436ea0, T014) and at the source upload (fixed in 6fa3143, T023). Deploys start without an approval click, by the owner's decision of 2026-10-01 (Clarifications, FR-005). Open: T015 (run 17 still read the project identifiers from variables, so its log showed them until it was deleted).

**Input**: User description: "yes, create specs/005 and add the docker build step". The docker build step is the CI `image` job (commit ab35799). This spec describes the delivery pipeline as it exists in the repository on 2026-10-01. It moves the build, CI and deploy work recorded as 001 T052 and T053 into its own packet.

**Constitution**: Ratified v1.0.0. **PATCH** (Article XIV): build, test and deploy tooling only. No server behavior, tool, authorization rule or invariant changes. Every deploy made with the current deploy script, by pipeline or by hand, still pins the `kb` allow-list from Secret Manager (002 T064, T076, T077) and refuses to run without the paywall (004 FR-009). The deploy account is a Google Cloud identity for deploys only: it has no Drive access of its own, and the server still reads Drive as the one Google identity of v1 scope. The constitution is not amended.

**Bounded Context**: Delivery (outside the running server; ships the code that Access Control, Retrieval Core, Connect Counter and Paid Subscription define, and does not change what they do)

## Clarifications

### Session 2026-10-01

- Q: Should a push to `main` go live without a person? → A: Yes, by the owner's decision (2026-10-01): "auto-approve on behalf of me if both test & image steps are passed as green". The `deploy` job starts as soon as `test` and `image` pass on a push to `main`. The GitHub environment `production` has no required reviewer; it still allows only `main`, and Google still requires it in the token. The first draft of this spec required an approval click; the owner chose otherwise. Adding a required reviewer back needs no code change. Code that the pipeline deploys runs as the Cloud Run runtime account, with the server's secrets, so what reaches `main` is what goes live.
- Q: May GitHub hold a Google Cloud key? → A: No. The deploy job gets a short-lived token through Workload Identity Federation. No service-account key exists for deploys.
- Q: Who may deploy? → A: Only jobs of this repository (numeric id 1369539999), on `refs/heads/main`, in the environment `production`. Forks, other branches, pull requests, other repositories and Dependabot cannot.
- Q: Keep old Cloud Run revisions for a quick rollback? → A: No. Older revisions may lack the `kb` pin, so every deploy deletes them. Roll back by redeploying an older commit.
- Q: Should Dependabot move the image to a new Python? → A: No. CI and `uv.lock` target Python 3.12. The Python base image gets patch updates only; a move to 3.13 or 3.14 is a deliberate change.
- Q: Does 005 change the Drive credential? → A: No. The owner accepted keeping their own gcloud login as the server's Drive credential (`.specify/memory/project-status.md`). That is outside 005, but it is why control over what reaches `main` matters.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ship a change by pushing to `main` (Priority: P1)

The owner pushes to `main`. Tests, lint, the lockfile check, the dependency audit and an image build run automatically. When they pass, the deploy starts by itself: it builds on Cloud Build, deploys to Cloud Run, keeps only the new revision, and checks the live service answers.

**Why this priority**: Deploying by hand from a laptop needs owner rights and a clean local tree. A pipeline makes each deploy the same, from a tested commit, with no local command.

**Independent Test**: With the deploy secrets and the `GCP_REGION` variable set, push a commit to `main`. The `test` and `image` jobs pass. The `deploy` job starts without waiting for review, deploys, deletes older revisions, and the smoke test passes. `/subscribe` on the service answers. (Run 17, 6fa3143.)

**Acceptance Scenarios**:

1. **Given** the deploy settings are in place, **When** a push to `main` passes the `test` and `image` jobs, **Then** the `deploy` job starts without waiting for a review.
2. **Given** the `deploy` job runs, **When** the deploy script finishes, **Then** Cloud Build builds that commit, Cloud Run gets a new revision with the pinned `kb` folder id and the paywall on, all traffic goes to it, every older revision is deleted, and the smoke test passes.
3. **Given** the owner adds a required reviewer back to `production` (optional, not the current setting), **When** a push to `main` passes CI, **Then** the `deploy` job waits for that review, runs no step before it, and a rejection deploys nothing.
4. **Given** the `GCP_REGION` variable is not set yet, **When** a push to `main` passes CI, **Then** the `deploy` job is skipped and the run is green.

---

### User Story 2 - A broken change is stopped before production (Priority: P1)

A change with failing tests, real lint errors, a stale lockfile, a known-vulnerable dependency, or an image that does not build or does not fail closed never starts a deploy. A deploy that starts still refuses to go live without the `kb` pin or the paywall. A revision that does not start never takes traffic. A revision that starts but fails the smoke test fails the run at once, so the owner can roll back.

**Why this priority**: The server holds the owner's Drive credential and takes payments. A broken or unguarded build in production is worse than no deploy.

**Independent Test**: Push branches that each carry one defect: a failing test, an unused import, a `pyproject.toml` change without `uv lock`, a dependency pinned to a version with a known advisory, a Dockerfile that runs as root. CI fails on each. On `main`, the `deploy` job of such a commit is skipped.

**Acceptance Scenarios**:

1. **Given** a failing test, a Ruff `F` or `E9` error, a lockfile that does not match `pyproject.toml`, or a locked runtime dependency with a known vulnerability, **When** it is pushed, **Then** the `test` job fails and the `deploy` job does not run.
2. **Given** an image that does not build, runs as root, cannot import the server, or starts without `DRIVE_ALLOWED_FOLDER_ID`, **When** it is pushed, **Then** the `image` job fails and the `deploy` job does not run.
3. **Given** a deploy that starts and a project without the Stripe key and price, the `kb` folder-id secret, `MCP_AUTH_TOKEN`, `MCP_PRINCIPAL_ID` or a Google credential, **When** the deploy script runs, **Then** it stops before any build, names what is missing, and the job fails.
4. **Given** a deploy whose new revision does not start, **When** Cloud Run deploys it, **Then** the deploy fails, the previous revision keeps all traffic, and no revision is deleted.
5. **Given** a newest revision that does not carry the pinned `kb` folder id, **When** the guard runs, **Then** the script stops before traffic tags are cleared and before any revision is deleted, and the job fails.
6. **Given** a deploy that went live but whose `/subscribe` or protected-resource metadata does not answer, **When** the smoke test runs, **Then** the job fails in the same run and the owner rolls back (User Story 5).

---

### User Story 3 - Only this repository's `main` can deploy, without a stored key (Priority: P1)

Google Cloud accepts the deploy job's identity only for this repository, the `main` branch and the `production` environment. No key is stored anywhere. The deploy identity holds only what one deploy of the `onto-kb` service needs. The public Actions logs do not show the project id, project number, provider path or deploy account.

**Why this priority**: The repository is public. Anyone can fork it, open pull requests and read the Actions logs. A deploy path that trusts more than this repository's `main` jobs in `production` would let others run code as the runtime account.

**Independent Test**: Read the provider's attribute condition and the deploy account's role bindings. Open a pull request from a branch and from a fork: the `deploy` job is skipped. List the deploy account's user-managed keys: there are none. Read a deploy run's log: the identifiers show as `***`, also in the mask step's own header (T015).

**Acceptance Scenarios**:

1. **Given** a pull request from this repository or from a fork, **When** CI runs, **Then** the `deploy` job does not run.
2. **Given** a push to any branch other than `main`, **When** CI runs, **Then** the `deploy` job is skipped; if a branch edits the workflow to remove that condition, the `production` environment refuses the branch and Google refuses the token's `ref`.
3. **Given** a job in any other repository, including a fork or a new repository with the same name, **When** it asks Google for a token, **Then** Google refuses it, because the numeric repository id does not match.
4. **Given** a Dependabot pull request, **When** CI runs, **Then** the `test` and `image` jobs run and the `deploy` job does not.
5. **Given** the deploy identity, **When** it is used with its own permissions, **Then** it can deploy, update and clean up the `onto-kb` service only (its project-wide extras are listing bucket names and deleting revisions that serve no traffic); it cannot enable APIs, change project IAM, read any secret value except the `kb` folder id, or touch Drive. Code it builds or deploys runs as the runtime account and is not limited this way (Assumptions).
6. **Given** the public log of a deploy run, **When** anyone reads it, **Then** the project id, project number, provider path and deploy account email are masked, including in the mask step's header.

---

### User Story 4 - Dependencies stay patched without surprise upgrades (Priority: P2)

Dependabot proposes weekly updates for the Python lockfile, the Docker images and the GitHub Actions. The Python base image gets patch updates only. Every proposal goes through the same CI, and nothing reaches production until the owner merges it. A merge to `main` that passes CI deploys at once, so the merge is the decision.

**Why this priority**: The audit catches known vulnerabilities, but fixes still need to arrive. A bot that moves the runtime to a new Python minor version would change the platform without a decision.

**Independent Test**: Read `.github/dependabot.yml`: three ecosystems, weekly, and an ignore rule for `python` minor and major updates. Open Dependabot pull requests run the `test` and `image` jobs.

**Acceptance Scenarios**:

1. **Given** a week has passed, **When** Dependabot runs, **Then** it may open pull requests for `uv.lock`, for the `uv` and Python images in the `Dockerfile`, and for actions in the workflow.
2. **Given** a new Python minor or major image (for example `3.14-slim`), **When** Dependabot runs after commit 37a27df, **Then** it does not propose it.
3. **Given** a Dependabot pull request, **When** CI runs, **Then** the lockfile check, tests, lint, audit and image build all run on it.
4. **Given** a merged update on `main`, **When** CI passes, **Then** it deploys without a further click.

---

### User Story 5 - Deploy by hand and recover (Priority: P2)

The owner can still deploy from a clean checkout with their own gcloud login. That path also runs the one-time setup (APIs, IAM grants for the runtime account, the telemetry dashboard). A rollback is a deploy of an older commit. When old revisions cannot be deleted, the script says which ones.

**Why this priority**: The pipeline needs a first manual deploy (the service, bucket, image repository and secrets must exist), and the owner needs a way out if the pipeline is down or a deploy is bad.

**Independent Test**: In a clean checkout run `bash scripts/deploy-cloud-run.sh` with an owner login: the tests run, the deploy completes and prints `LIVE_MCP_URL=…/mcp`. Add an untracked file and run it again: it refuses before any project gcloud call.

**Acceptance Scenarios**:

1. **Given** a clean checkout and an owner gcloud login, **When** the owner runs the deploy script, **Then** it runs the tests, the one-time setup, the deploy, the `kb` guard and the cleanup, then ensures the telemetry dashboard.
2. **Given** uncommitted or untracked files that are not git-ignored, **When** the script starts, **Then** it refuses before any project gcloud call unless `ALLOW_DIRTY=1`.
3. **Given** a bad deploy, **When** the owner reverts the change on `main`, or deploys an older commit by hand, **Then** a new revision runs that code and older revisions are deleted.
4. **Given** a revision that cannot be deleted, **When** cleanup runs, **Then** the script exits non-zero and names each revision left, so the owner can remove its traffic and delete it by hand.
5. **Given** `ONE_TIME_SETUP=0`, **When** the owner runs the script by hand, **Then** it behaves as the CI deploy does, except that it still runs the tests unless `SKIP_TESTS=1`.

---

### Edge Cases

- **No required reviewer** (the current setting, FR-005): the `deploy` job starts as soon as `test` and `image` pass. Run 15's first attempt still had a reviewer and waited; it ended after about five minutes without running a step when the owner changed the environment. Run 15's re-run, run 16 and run 17 started within seconds of being queued, and run 17 went live that way.
- **Required reviewer added back** (optional): the `deploy` job waits for review and runs no step before it. A rejection, or GitHub's wait limit (30 days at the time of writing), ends it with nothing deployed. The job's 30-minute timeout starts when it runs.
- **Malicious or mistaken change on `main`**: with no approval click, a commit on `main` that passes CI goes live within minutes. CI catches failing tests, real lint errors, a stale lockfile, known vulnerabilities and a broken image, not malicious code. The owner's review before pushing or merging (including Dependabot pull requests) is the control (Assumptions).
- **Newer push while a deploy waits or runs**: deploys share the concurrency group `deploy-production` and a running deploy is never cancelled. GitHub keeps at most one more deploy pending in the group, and a newer one replaces an older pending one, which is then cancelled without deploying. Two deploys never run at once. With a required reviewer added back, a deploy waiting for review may hold the group (GitHub's documented behavior, not observed here); rejecting it lets the newest pending commit come up instead.
- **Cloud Build fails**: `gcloud run deploy` fails, no revision is created, the previous revision keeps serving, and nothing is deleted.
- **New revision fails to start** (bad configuration, a secret it cannot read, Drive startup check fails): Cloud Run does not send traffic to it, `gcloud run deploy` fails, nothing is deleted.
- **A secret added after the last operator deploy** (for example `IDENTITY_TOOLKIT_API_KEY`): the CI deploy binds it, but CI mode does not grant the runtime account access to it, so the revision does not start. Run one manual deploy with `ONE_TIME_SETUP=1`, or grant `roles/secretmanager.secretAccessor` on that secret to the runtime account.
- **Smoke test fails**: the new revision already serves and older revisions are already deleted. The job fails. The owner rolls back by redeploying a good commit.
- **Source upload denied**: `gcloud run deploy --source` lists the project's buckets (`storage.buckets.list`) before it uploads, and the bucket-level `storage.admin` grant does not cover that. Run 16 failed there, before any build, and production was unchanged. The custom role `ontoKbDeployExtras` adds that permission (6fa3143, T023); run 17's upload passed.
- **Revision deletion denied**: the deploy account deletes old revisions with `run.revisions.delete` from the custom role `ontoKbDeployExtras` (6fa3143, T023); run 17's cleanup succeeded with it (T016). If deletion is ever refused, the script exits non-zero after routing all traffic to the newest revision and names the revisions it could not delete.
- **Deploy settings missing**: without the `GCP_REGION` variable the `deploy` job is skipped. With it set but without `GCP_WIF_PROVIDER` or `GCP_DEPLOY_SA` (as a secret or a variable), the sign-in step fails. Without `GCP_PROJECT_ID` the deploy script falls back to the gcloud configuration's project and the project id is not masked. `GCP_PROJECT_NUMBER` is used only for masking.
- **Provider condition mismatch** (wrong repository id, branch or environment): Google refuses the token exchange and the sign-in step fails before any gcloud call.
- **Dependabot pull requests**: they run CI with a read-only token. They never deploy. Dependabot's own branch pushes also run CI and skip the deploy.
- **Secrets missing in CI mode**: the deploy script stops with a message naming the missing secret. It never creates `MCP_PRINCIPAL_ID` in CI mode.
- **Public logs**: the repository and its Actions logs are public. Since 6fa3143 the deploy job reads the project id, project number, provider path and deploy account from Actions secrets, which GitHub masks in every log line, and its first step also adds a mask for each. A value that still comes from a repository variable is shown once, in the mask step's own header, because GitHub prints a step's script with `${{ }}` values filled in before the step runs. That is how runs 15 and 16 published the project id (T015). The script never prints secret values or the `kb` folder id. The service URL may appear in the log; it is already public (the business page links to `/subscribe` on it).
- **Credentials file in the workspace**: `google-github-actions/auth` writes a credentials file (`gha-creds-*.json`) into the checkout by default. Before e436ea0 it was not git-ignored, and the clean-tree preflight refused the first pipeline deploy that ran (run 15) before any project gcloud call. Since e436ea0, `.gitignore` lists it (the preflight passes), `.gcloudignore` keeps it out of the `--source` upload, and `.dockerignore` keeps it out of any image (T014). `ALLOW_DIRTY=1` was never the fix: without the ignore rules `--source` would have uploaded that file.
- **Base image moves between builds**: the `image` job and Cloud Build build the same commit separately. `python:3.12-slim` is a moving tag, so the two builds may use different 3.12 patch releases.
- **Vulnerability published between pushes**: the audit runs on push and pull request only. A new advisory for a locked dependency fails CI at the next push or Dependabot pull request, not before.
- **Rollback to an old commit**: a manual deploy runs the deploy script of that commit. Commits before b367728 do not refuse to deploy without the paywall (004 T022), and commits before 11eccc9 (002 T077) pin a `kb` folder id written in the script (not read from Secret Manager) and default to a project id written in it. Roll back by hand only to commits from 11eccc9 on; for older code, revert on `main` instead, which deploys with the current script.
- **Workflow edited on a branch**: it runs for that branch, but the environment and the provider condition still refuse anything but `main`. A workflow change runs as soon as it reaches `main`, so the owner reviews workflow changes before merging.
- **Actions referenced by tag**: workflow actions are pinned by major version, not commit SHA. A compromised tag of an action in the deploy job would run with the deploy identity on the next push to `main`, with no click to stop it (T021).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Every push (any branch or tag) and every pull request MUST run the `test` job on Python 3.12: check that `uv.lock` matches `pyproject.toml`, install exactly from the lockfile, run every test except the live suite in `tests/e2e`, check `src` and `tests` for real errors (Ruff `F`, `E9`; style is not gated), and audit the runtime dependencies as locked, with hashes. Any failing step MUST fail the job. Time limit: 15 minutes.
- **FR-002**: Every push and pull request MUST run the `image` job: build the production image from the repository `Dockerfile` with fresh base images, then fail unless the container runs as uid 10001, imports the server, and, started with no configuration, exits non-zero with output naming `DRIVE_ALLOWED_FOLDER_ID`. The image MUST NOT be pushed anywhere. Time limit: 15 minutes.
- **FR-003**: The production image MUST install only what `uv.lock` pins (hashes checked, no dev group, no project build) with a `uv` binary pinned by version and digest, MUST run as the non-root uid 10001, and MUST start `python -m google_drive_mcp`. Test tools (`pytest`, `pytest-asyncio`, `ruff`) MUST stay in the dev group, out of the image. `mcp` MUST be bounded `>=2.2,<3`.
- **FR-004**: The `deploy` job MUST run only for a push to `refs/heads/main`, only after both the `test` and `image` jobs pass on that commit, and only when the repository variable `GCP_REGION` is set. Otherwise it MUST be skipped, not failed. Time limit: 30 minutes from the start of the job.
- **FR-005**: The `deploy` job MUST run in the GitHub environment `production`, which allows only `main`. By the owner's decision (2026-10-01) the environment has no required reviewer, so the job starts as soon as `test` and `image` pass. The workflow MUST keep working unchanged if the owner adds a required reviewer back; the job then MUST NOT run any step before approval.
- **FR-006**: At most one deploy MUST run at a time (concurrency group `deploy-production`). A newer push MUST NOT cancel a running deploy.
- **FR-007**: The `deploy` job MUST sign in to Google Cloud without a stored key: GitHub's OIDC token is exchanged through Workload Identity Federation for short-lived credentials of the deploy account `onto-kb-deployer`. Only the `deploy` job MUST have `id-token: write`; the workflow default MUST be `contents: read`. Each checkout MUST set `persist-credentials: false`, so no GitHub token stays in the checkout.
- **FR-008**: The provider MUST accept a token only when `repository_id` is 1369539999, `ref` is `refs/heads/main` and `environment` is `production`. Only principals of that repository id MAY impersonate the deploy account.
- **FR-009**: The deploy account MUST hold only: `roles/run.admin` on the `onto-kb` service; project `roles/run.viewer`, `roles/cloudbuild.builds.editor`, `roles/serviceusage.serviceUsageConsumer`, `roles/secretmanager.viewer`; the project custom role `ontoKbDeployExtras` with only `storage.buckets.list` and `run.revisions.delete`; `roles/iam.serviceAccountUser` on the runtime account; `roles/storage.admin` on the `run-sources-<project-id>-<region>` bucket; `roles/artifactregistry.reader` on the `cloud-run-source-deploy` repository; `roles/secretmanager.secretAccessor` on the `DRIVE_ALLOWED_FOLDER_ID` secret. It MUST NOT have a user-managed key.
- **FR-010**: The project id, project number, provider path and deploy account email MUST NOT appear unmasked in the public log. The `deploy` job MUST read them from Actions secrets, and its first step MUST add a mask for each. The deploy script MUST NOT print secret values or the `kb` folder id.
- **FR-011**: With `ONE_TIME_SETUP=0` (the `deploy` job), the deploy script MUST NOT enable APIs, grant IAM, describe the project, create secrets or set up the telemetry metrics and dashboard. It MUST stop when `MCP_PRINCIPAL_ID` is missing instead of creating it. The job sets `SKIP_TESTS=1` because the `test` job already passed on that commit.
- **FR-012**: Before any gcloud call that reaches the project (only `gcloud config get-value project` may run first, when `GCP_PROJECT` is unset) the deploy script MUST refuse a working tree with uncommitted or untracked files that are not git-ignored (unless `ALLOW_DIRTY=1`) and, when `uv` is on `PATH`, MUST run `uv run --locked pytest -q --ignore=tests/e2e` and stop when it fails (unless `SKIP_TESTS=1`). The sign-in credentials file `gha-creds-*.json` MUST be git-ignored (`.gitignore`), MUST NOT be uploaded by `--source` (`.gcloudignore`, which also excludes `.git`, `.github` and everything git-ignored) and MUST NOT enter an image (`.dockerignore`).
- **FR-013**: The deploy script MUST refuse to deploy, before any build, without `MCP_AUTH_TOKEN`; without a Google credential (`GOOGLE_AUTHORIZED_USER_JSON`, or `GOOGLE_REFRESH_TOKEN` with `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`); without a well-formed `DRIVE_ALLOWED_FOLDER_ID` secret; and without `STRIPE_SECRET_KEY` and `STRIPE_PRICE_ID` (004 FR-009). It MUST bind the optional secrets that exist (`STRIPE_WEBHOOK_SECRET`, `IDENTITY_TOOLKIT_API_KEY`, the individual Google OAuth secrets).
- **FR-014**: The deploy MUST replace the service's environment with: `MCP_PUBLIC_URL` (the operator's `MCP_PUBLIC_URL` when set, else the existing service URL; realigned to the service's real URL whenever the two differ, as on a first deploy), `DRIVE_ALLOWED_FOLDER_ID` from the Secret Manager secret (never from the operator's shell or the repository), `MCP_OAUTH_AUTO_APPROVE=true` (ignored while the paywall is on), `GOOGLE_CLOUD_PROJECT`, `MCP_STATS_FROM_LOGS=true` and `MCP_SUBSCRIPTION_REQUIRED=true`.
- **FR-015**: The deploy MUST set 1 GiB memory, a 60-second request timeout, concurrency `CLOUD_RUN_CONCURRENCY` (default 10) and at most `CLOUD_RUN_MAX_INSTANCES` instances (default 3). The CI deploy uses the defaults. Cloud Run MUST allow unauthenticated requests; the server enforces its own OAuth and paywall.
- **FR-016**: After the deploy, the script MUST check that the newest ready revision carries the pinned `kb` folder id and stop if it does not. It MUST then send all traffic to the latest revision, clear traffic tags, and delete every other revision. It MUST exit non-zero when the revision list does not include the newest revision, and when any deletion fails, naming the revisions left.
- **FR-017**: After the deploy script succeeds, the `deploy` job MUST request `/subscribe` and `/.well-known/oauth-protected-resource` on the live service URL and fail on an HTTP error or no answer. The smoke test MUST NOT change the service.
- **FR-018**: Dependabot MUST check `uv`, `docker` and `github-actions` weekly and MUST NOT propose minor or major updates of the `python` base image.
- **FR-019**: `scripts/setup-github-deploy.sh` MUST be safe to re-run. It MUST enable the IAM, IAM Credentials and STS APIs; create the deploy account and the pool `onto-kb-github` when missing; create the OIDC provider `github` (issuer `https://token.actions.githubusercontent.com`) or update its attribute mapping and condition; create or update the custom role `ontoKbDeployExtras`; bind `roles/iam.workloadIdentityUser` for the repository's principal set; grant the roles in FR-009; and print the GitHub steps, the four Actions secrets and the `GCP_REGION` variable. It MUST NOT print secret values.
- **FR-020**: A manual deploy (`ONE_TIME_SETUP` unset or `1`) MUST also enable the required APIs, grant the runtime account access to each bound secret, grant the Cloud Build and runtime accounts their build roles, create `MCP_PRINCIPAL_ID` when missing, and ensure the connect-counter log metrics and dashboard (`scripts/ensure-connect-telemetry-gcp.sh`). It MUST apply the same preflight, refusals, `kb` guard and cleanup as the CI deploy.
- **FR-021**: A rollback MUST be a deploy of an older commit (a revert on `main` through the pipeline, or a manual deploy from that commit). Older revisions are not kept for traffic rollback.
- **FR-022**: Unit tests MUST pin the build and pipeline settings: image from the lockfile as non-root with the expected start command; bounded runtime dependencies and dev-only test tools; lockfile in step with `pyproject.toml`; the CI test steps; the three Dependabot ecosystems weekly; the `image` job checks; and a `deploy` job that needs `test` and `image`, uses `production`, runs only on `main` and sets `ONE_TIME_SETUP: "0"`. They MUST also prove the preflight: a dirty tree and failing tests stop before gcloud, the overrides work, CI mode never enables APIs or grants IAM, operator mode still does, and a git-ignored `gha-creds-*.json` does not block a deploy. They MUST pin the ignore rules for that file in `.gitignore`, `.gcloudignore` (with `#!include:.gitignore`) and `.dockerignore`.

### Key Entities

- **Pipeline run**: One run of the `CI` workflow for one commit and event. Jobs `test`, `image`, `deploy`.
- **Production environment**: The GitHub environment `production`. Allows only `main`. No required reviewer (owner decision, FR-005); one can be added back without a code change.
- **Approval**: Not used while `production` has no required reviewer. With one added back: the owner's decision on one waiting `deploy` job; approve runs it, reject fails it.
- **Deploy settings**: Actions secrets `GCP_PROJECT_ID`, `GCP_PROJECT_NUMBER`, `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA` (none grants access; secrets because GitHub masks them in every log line), and the repository variable `GCP_REGION`, which turns the `deploy` job on. Variables of the four secret names still work as a fallback, but the mask step's header shows them.
- **Workload identity pool and provider**: `onto-kb-github` / `github`. Turns a GitHub OIDC token that meets the condition into a Google token.
- **Deploy account**: `onto-kb-deployer@<project-id>.iam.gserviceaccount.com`. Least-privilege identity of the `deploy` job. Not a Drive identity.
- **Runtime account**: The default compute account the service runs as. It holds the server's secrets, including the owner's Drive credential. Cloud Build source deploys also build as it.
- **Production image**: Built from the `Dockerfile` and `uv.lock`. CI builds it as a check; Cloud Build builds the deployed copy from the same commit.
- **Revision**: One Cloud Run revision of `onto-kb`. After a successful deploy only the newest exists.
- **`kb` pin**: The Secret Manager secret `DRIVE_ALLOWED_FOLDER_ID`. The deploy reads it and sets it on the revision.
- **Dependency update**: A Dependabot pull request for `uv`, `docker` or `github-actions`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From a push to `main` that passes CI, the owner takes 0 further actions to put the commit live. No local command is needed.
- **SC-002**: 100% of pipeline deploys are of commits whose `test` and `image` jobs passed in the same run.
- **SC-003**: Zero user-managed keys exist for the deploy account, and zero Google Cloud keys are stored in GitHub.
- **SC-004**: A token from any other repository, branch or environment is refused by Google in 100% of attempts.
- **SC-005**: After each successful deploy, the service has exactly one revision, it serves 100% of traffic, and it carries the pinned `kb` folder id.
- **SC-006**: In the public logs of every deploy run, the project id, project number, provider path and deploy account email appear 0 times unmasked.
- **SC-007**: A commit that fails any CI check produces 0 deploys.
- **SC-008**: A deploy that goes live but fails the smoke test shows as a failed run within the job's 30-minute limit.
- **SC-009**: After commit 37a27df, Dependabot opens 0 pull requests for a new Python minor or major image.
- **SC-010**: The owner can replace a bad deploy with a known good commit in one deploy run (under 30 minutes after pushing the revert).
- **SC-011**: A pipeline deploy makes 0 changes to project-level IAM and 0 API enablements.

## Assumptions

- The owner is the only person with write access, so only the owner can put a commit on `main`, and every commit on `main` that passes CI goes live. The environment's branch rule (and a required reviewer, should the owner add one back) is set in the GitHub UI; `scripts/setup-github-deploy.sh` prints the steps but cannot set them.
- At least one manual deploy has run before the pipeline is used: the service, the source bucket, the image repository and all secrets exist, and the runtime account can read the secrets.
- Cloud Run source deploys build with the runtime (default compute) account, so the deploy account needs `actAs` on it. That also means the deploy identity can run code as the runtime account. Least privilege limits what the deploy account can do directly, not what deployed code can do. With deploys automatic, the control for that is the owner's review of what reaches `main`: their own pushes and the pull requests they merge, Dependabot's included.
- The owner's own gcloud login stays the server's Drive credential (accepted risk in `.specify/memory/project-status.md`). It reaches every revision through Secret Manager; a malicious change that reaches `main` could read it.
- The CI image check and the deployed image are separate builds of the same commit. Nothing built in CI is pushed or deployed.
- `main` is not yet protected by a ruleset that requires the CI checks (T017). The deploy job still needs both checks, so this only matters for merges, not for deploys.
- The live end-to-end suite (`tests/e2e/test_live_mcp.py`) is not part of CI; it needs `LIVE_MCP_URL` and `MCP_AUTH_TOKEN` and is run by hand. As written it finishes OAuth with the consent password, which a deployment with the paywall on does not offer (an unpaid `/authorize` goes to `/subscribe`), so it cannot get a token from production (T019).
- The first pipeline deploy completed in run 17 (6fa3143), so the deploy account's roles are enough end to end (T016). Run 15 had stopped at the clean-tree preflight before any project gcloud call (fixed in e436ea0, T014), and run 16 at the source upload, before any build (fixed in 6fa3143, T023).
