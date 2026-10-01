# Contract: CI Workflow (`.github/workflows/ci.yml`)

Workflow name `CI`. Pinned by `tests/unit/test_build_config.py`.

## Triggers

- `push`: every branch and tag, no path filter.
- `pull_request`: default activity types (opened, synchronize, reopened), from this repository or a fork.

## Permissions

- Workflow default: `contents: read`. No other scope.
- `deploy` job: `contents: read`, `id-token: write`. No other job can request an OIDC token.
- Every `actions/checkout` step runs with `persist-credentials: false`, so no GitHub token is left in `.git/config`.

## Jobs

| Job | Runs on | Time limit | Needs | Runs when |
| --- | --- | --- | --- | --- |
| `test` | `ubuntu-latest` | 15 min | — | every trigger |
| `image` | `ubuntu-latest` | 15 min | — | every trigger |
| `deploy` | `ubuntu-latest` | 30 min | `test`, `image` | `github.event_name == 'push' && github.ref == 'refs/heads/main' && vars.GCP_REGION != ''` |

`test` and `image` run in parallel. When either fails, `deploy` is skipped. When its `if` is false, `deploy` is skipped and the run can still be green.

### `test`

| Step | Command | Fails when |
| --- | --- | --- |
| Checkout | `actions/checkout@v7` | — |
| Set up uv | `astral-sh/setup-uv@v7`, `python-version: "3.12"` | — |
| Lockfile matches pyproject.toml | `uv lock --check` | `pyproject.toml` changed without `uv lock` |
| Install from the lockfile | `uv sync --frozen` | the lockfile cannot be installed as is |
| Tests | `uv run pytest -q --ignore=tests/e2e` | any test fails |
| Ruff | `uv run ruff check --select F,E9 src tests` | undefined names, unused imports, syntax errors (style is not gated) |
| Dependency audit | `uv export --frozen --no-dev --no-emit-project --format requirements-txt > requirements-audit.txt`; `uvx pip-audit --disable-pip --require-hashes -r requirements-audit.txt` | a locked runtime dependency has a known vulnerability, or a hash is missing |

### `image`

| Step | Command | Fails when |
| --- | --- | --- |
| Checkout | `actions/checkout@v7` | — |
| Build the production image | `docker build --pull --tag onto-kb:ci .` | the image does not build |
| Runs as the non-root user and imports the server | `docker run --rm onto-kb:ci id -u` must print `10001`; `docker run --rm onto-kb:ci python -c "import google_drive_mcp.mcp.server"` | wrong user, or the server module does not import |
| Refuses to start without configuration | `docker run --rm onto-kb:ci` must exit non-zero and its output must contain `DRIVE_ALLOWED_FOLDER_ID` | the server starts without its allow-list, or fails for another reason |

Nothing is pushed. The image is a check only; Cloud Build builds the deployed image.

### `deploy`

- `environment: production`: allows only `main`, and its name is in the OIDC token that Google checks. No required reviewer (owner decision, FR-005), so the job starts once `test` and `image` pass; with a reviewer added back, GitHub would hold it until approval.
- `concurrency: { group: deploy-production, cancel-in-progress: false }`: one deploy runs at a time; a newer pending deploy replaces an older pending one.
- Every action is pinned by full commit SHA with its release in a trailing comment (FR-007, T021). Dependabot updates both.

| Step | Detail | Fails when |
| --- | --- | --- |
| Mask project identifiers | `::add-mask::` for `secrets.X \|\| vars.X` with X = `GCP_PROJECT_ID`, `GCP_PROJECT_NUMBER`, `GCP_DEPLOY_SA` | — (a value from a variable shows in this step's header, T015) |
| Checkout | `actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1` (v7.0.1), `persist-credentials: false` | — |
| Sign in | `google-github-actions/auth@7c6bc770dae815cd3e89ee6cdf493a5fab2cc093` (v3.0.0) with `workload_identity_provider` and `service_account` from `GCP_WIF_PROVIDER` and `GCP_DEPLOY_SA` (secret, else variable) | the token does not meet the provider condition, or the account cannot be impersonated |
| Set up gcloud | `google-github-actions/setup-gcloud@aa5489c8933f4cc7a4f7d45035b3b1440c9c10db` (v3.0.1) | — |
| Deploy to Cloud Run | `bash scripts/deploy-cloud-run.sh` with `GCP_PROJECT` from `GCP_PROJECT_ID` (secret, else variable), `GCP_REGION=vars.GCP_REGION` (the `\|\| 'us-central1'` default cannot apply, because the job runs only when it is set), `ONE_TIME_SETUP=0`, `SKIP_TESTS=1`, `CLOUDSDK_CORE_DISABLE_PROMPTS=1` | any refusal or failure in [deploy-scripts.md](./deploy-scripts.md) |
| Smoke test | `gcloud run services describe onto-kb … --format='value(status.url)'`, then `curl -fsS -o /dev/null` on `/subscribe` and `/.well-known/oauth-protected-resource` | either URL answers an HTTP error (400 or above) or not at all |

The sign-in step writes a credentials file into the checkout by default (`gha-creds-*.json`) and removes it at the end of the job. Since e436ea0 it is git-ignored, so the deploy script's clean-tree check passes, and `.gcloudignore` keeps it out of the `--source` upload (T014). Before that fix the check refused the first pipeline deploy that ran (run 15).

## Secrets and variables

Actions secrets `GCP_PROJECT_ID`, `GCP_PROJECT_NUMBER`, `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA`, each with a fallback to a repository variable of the same name, and the variable `GCP_REGION` (see [data-model.md](../data-model.md)). Only the `deploy` job reads them. None is a credential: the job holds no Google Cloud key.

## Outputs

- Job status per job (the only signal other tools read).
- Deploy log lines: `Deploying onto-kb to Cloud Run (<region>)...`, `Routing all traffic to <revision> and clearing traffic tags...`, `deleting <revision>`, `LIVE_MCP_URL=<service-url>/mcp`, `Deploy complete…`, and the smoke test's `Live: /subscribe and protected-resource metadata answer.`
- No artifacts or images are uploaded. (`astral-sh/setup-uv` may keep its uv cache in the GitHub Actions cache; it holds packages, not credentials.)

## Failure behaviour

- A failed `test` or `image` job: the `deploy` job is skipped, nothing deployed.
- A failed `deploy` before `gcloud run deploy` (or a rejected one, with a reviewer added back): production unchanged.
- A failed build or a revision that does not start: the previous revision keeps all traffic; nothing deleted.
- A failure after the new revision is live (the `kb` guard, cleanup, smoke test): the job fails; the owner checks the service and rolls back by redeploying if needed. The workflow never rolls back by itself.
