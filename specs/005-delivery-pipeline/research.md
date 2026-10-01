# Research: 005 Delivery Pipeline

## Decision: Keyless Workload Identity Federation, not a service-account key

**Rationale**: A JSON key in GitHub secrets would be a long-lived credential in a public repository's settings, valid from anywhere until someone rotates it. With Workload Identity Federation the `deploy` job asks GitHub for an OIDC token, and Google exchanges it for a short-lived token of `onto-kb-deployer` only when the token's claims match the provider condition. Nothing that grants access is stored. The job needs `id-token: write`, and only the `deploy` job has it.

**Alternatives considered**: A service-account key in a GitHub secret (long-lived, leaks through logs or a compromised action, needs rotation — rejected). Running deploys only by hand (works, but needs owner rights on a laptop each time and skips CI's checks — kept as the fallback, not the main path).

## Decision: Deploy automatically once `test` and `image` pass; the environment `production` limits it to `main`

**Rationale**: The owner decided on 2026-10-01: "auto-approve on behalf of me if both test & image steps are passed as green", and removed the required reviewer from `production`. The owner is the only person with write access, so every commit on `main` is already the owner's decision, and a second click per deploy added delay without new information. The environment still allows only `main`, and its name appears in the OIDC token, so Google can require it (next decision). Run 15's first attempt waited for the reviewer that was set then; run 15's re-run, run 16 and run 17 started at once, and run 17 deployed.

**Trade-off accepted**: Deployed code runs as the runtime account with the server's secrets, including the owner's Drive credential, and no automatic check can tell a malicious change from a good one. Without a click, a compromised dependency the owner merges goes live without a second look. Mitigations: CI blocks known advisories and broken images, Dependabot pull requests need the owner's merge, the deploy job's actions are pinned by commit SHA so a moved tag cannot reach the deploy identity (T021), and a branch ruleset (T017) would stop failing merges. A required reviewer can be added back in Settings → Environments → `production` with no code change.

**Alternatives considered**: A required reviewer on `production`, so each deploy waits for one click (the first design; the owner declined it as a step that adds nothing while they are the only committer). A manual `workflow_dispatch` trigger (anyone with write access can start it, and it does not tie the deploy to the commit that just passed CI — rejected). Branch protection alone (controls merges, not deploys).

## Decision: The provider condition checks the numeric repository id, the ref and the environment

**Rationale**: `assertion.repository_id=='1369539999' && assertion.ref=='refs/heads/main' && assertion.environment=='production'`. The numeric id survives a rename and is never reused, unlike `owner/name`, which a new repository could take after a rename or deletion. Checking `ref` stops other branches; checking `environment` stops any job outside the `production` environment and its `main`-only rule. Only the principal set for that repository id holds `roles/iam.workloadIdentityUser` on the deploy account. Forks have other ids. Pull request runs have other refs and no environment.

**Alternatives considered**: Condition on `assertion.repository` (name-based; reusable — rejected). Only the repository id (any branch or pull request job of this repository could deploy — rejected). Binding `google.subject` to one exact `sub` string (works, but the `sub` format changes with GitHub settings; the three attributes say the same thing more plainly).

## Decision: `ONE_TIME_SETUP` splits what only an owner may run

**Rationale**: The deploy script used to enable APIs, grant the runtime account access to secrets, grant build roles, create `MCP_PRINCIPAL_ID` and set up the telemetry dashboard on every run. Those need IAM admin and Service Usage admin rights. Giving them to the deploy account would let a pipeline job grant itself or anyone else anything in the project. With `ONE_TIME_SETUP=0` the script skips all of them and stops when `MCP_PRINCIPAL_ID` is missing instead of creating it. The owner runs them once, by a manual deploy (default `ONE_TIME_SETUP=1`) and `scripts/setup-github-deploy.sh`. The `deploy` job also sets `SKIP_TESTS=1`, because the `test` job already ran the same tests on the same commit.

**Alternatives considered**: Give the deploy account project IAM admin (rejected: it could escalate). Split the deploy script into two scripts (two places to keep the refusals and `kb` guard in step — rejected).

**Consequence**: A secret added after the last operator deploy is bound by the CI deploy but not granted to the runtime account, so the new revision does not start until the owner runs one manual deploy or grants access to that secret.

## Decision: `run.admin` on the service, not the project

**Rationale**: The deploy must create revisions, set traffic, set the service's invoker policy (`--allow-unauthenticated`) and delete revisions of `onto-kb`. A project-level `roles/run.admin` would also cover every other Cloud Run service and job in the project. A service-level binding covers only `onto-kb`. Listing revisions and reading the service need project `roles/run.viewer`, which is read-only. The other grants are also scoped to one resource where Google allows it: the source bucket, the image repository, the `DRIVE_ALLOWED_FOLDER_ID` secret, and `actAs` on the runtime account only.

**Two project-wide permissions** (6fa3143): `gcloud run deploy --source` lists the project's buckets (`storage.buckets.list`) to check that its source bucket belongs to the project, and the bucket-level grant does not cover that; run 16 failed there. A service-level binding may not cover deleting revisions (`run.revisions.delete`). Both go in one project custom role, `ontoKbDeployExtras`, with only those two permissions. Listing gives bucket names, not objects. Cloud Run refuses to delete a revision that serves traffic, so the delete permission reaches only idle revisions, of any service in the project. Run 17's deploy, including the upload and the cleanup, succeeded with it (T016).

**Alternatives considered**: Project `roles/run.admin` (every service — rejected). `roles/run.developer` at project level (still project-wide, and cannot set the invoker policy). A predefined project role for the two permissions (no narrow predefined role grants only these, per the setup script — rejected).

## Decision: Build and check the image in CI before any deploy

**Rationale**: Cloud Build builds the deployed image only once the `deploy` job runs. A Dockerfile mistake, a missing module, an image that runs as root or a server that starts without its allow-list would then show up only in production's deploy, possibly as a failing revision. With deploys automatic, the `image` job is also the last check before production. The `image` job builds the same `Dockerfile` from the same commit and `uv.lock`, checks uid 10001, imports the server, and checks that the container started without configuration exits non-zero naming `DRIVE_ALLOWED_FOLDER_ID` (fail closed, and proof that the start command runs the app). The `deploy` job needs it. Nothing is pushed, so CI needs no registry rights.

**Limits**: The CI image is not the deployed image. `python:3.12-slim` is a moving tag, so the two builds may differ by a Python patch release or Debian update. The CI container cannot start fully: the server checks the `kb` folder in Drive at startup and CI has no Drive credential.

**Alternatives considered**: Push the CI image to Artifact Registry and deploy that digest (one build, but CI would need write rights to the registry and the manual deploy path would differ — deferred). Only the Dockerfile unit test (reads text; does not prove the image builds or runs).

## Decision: Keep project identifiers in Actions secrets because the logs are public

**Rationale**: The repository is public, so anyone can read its Actions logs. The project id and number name the Google Cloud project and appear in resource names, bucket names and the provider path; the deploy account email contains the project id. None of them grants access, but they do not belong in public logs. GitHub masks Actions secrets in every log line. Repository variables are not masked, and a mask added by a step comes too late for that step's own header: GitHub prints each step's script with `${{ }}` values filled in before running it. Runs 15 and 16 read the identifiers from variables, and the mask step's header published the project id. Since 6fa3143 the job reads `GCP_PROJECT_ID`, `GCP_PROJECT_NUMBER`, `GCP_WIF_PROVIDER` and `GCP_DEPLOY_SA` from secrets (variables of the same names remain a fallback), and its first step still adds a mask for each, for anything gcloud prints. Secrets cannot be used in a job's `if`, so the variable `GCP_REGION`, which is not sensitive, turns the job on. The `test` and `image` jobs never read them. The deploy script never prints secret values or the `kb` folder id.

**Limits**: A value left as a variable is still shown once, in the mask step's header; runs 15 to 19 showed them that way until the owner moved them to secrets, and their logs were deleted (T015). The service URL may appear in the deploy output; it is already public.

**Alternatives considered**: Repository variables plus a mask step (the original design, 58e11d5; leaked through the mask step's header — replaced). Leave them unmasked (publishes the project id — rejected).

## Decision: Dependabot weekly, with patch-only updates for the Python base image

**Rationale**: Three ecosystems weekly: `uv` (the lockfile), `docker` (the `uv` image, pinned by version and digest, and the Python base), and `github-actions`. CI and `uv.lock` target Python 3.12 (`setup-uv` installs 3.12; Ruff targets `py312`). Dependabot opened a pull request for `python:3.14-slim`; a move to a new Python is a decision with its own testing, not a weekly bot update. The ignore rule drops minor and major `python` updates (37a27df). The base image tag `3.12-slim` already floats to the newest 3.12 patch at each build (`docker build --pull` in CI; Cloud Build pulls it too).

**Alternatives considered**: Pin the base image by digest and let Dependabot bump it (reproducible, more pull requests — possible later). No Docker updates (the `uv` pin would go stale — rejected). Allow all Python updates (the 3.14 pull request — rejected).

## Decision: Delete old revisions; roll back by redeploying

**Rationale**: A Cloud Run revision keeps its own code and environment. Revisions from before the `kb` lockdown carry no allow-list, and a traffic rollback to one would serve the whole Drive (002 T064, T076). So every deploy checks that the newest revision carries the pinned `kb` id, sends all traffic to the latest revision (`--to-latest`, so the next deploy's revision takes traffic), clears traffic tags and deletes every other revision. A rollback is a new deploy of an older commit: a revert on `main` through the pipeline, or a manual deploy from that commit. That rebuilds the code but always applies the current secrets, the `kb` pin and the paywall.

**Limits**: A rollback takes a full build and deploy, not a traffic switch. A manual deploy runs that commit's own deploy script: commits before b367728 do not refuse to deploy without the paywall, and commits before 11eccc9 pin a `kb` folder id written in the script instead of reading Secret Manager. For code older than 11eccc9, revert on `main` instead.

**Alternatives considered**: Keep old revisions and roll back by traffic (fast, but may serve without the allow-list — rejected). Keep only revisions that carry the pin (still lets a rollback skip the paywall or other later fixes — rejected).

## Decision: Cloud Build from source, the same path as a manual deploy

**Rationale**: `gcloud run deploy --source` uploads the checked-out tree, minus what `.gcloudignore` excludes (`.git`, `.github`, everything git-ignored, and the sign-in credentials file `gha-creds-*.json`, e436ea0), builds it with the repository `Dockerfile` on Cloud Build, and deploys the result. The pipeline and a manual deploy then share one script and one build path. The deploy account needs storage rights on the source bucket, `storage.buckets.list` in the project (gcloud lists the buckets before uploading) and read access to the image repository; the build runs as the runtime account, which holds the registry write role from the one-time setup.

**Alternatives considered**: Build and push in GitHub Actions, then deploy by digest (see the image decision — deferred).
