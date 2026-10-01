# Implementation Plan: Delivery Pipeline

**Branch**: `main` | **Date**: 2026-10-01 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-delivery-pipeline/spec.md`

**Upstream**: Build and CI were planned in `specs/001-access-control/plan.md` ("Build and CI", "Deploy pipeline (2026-10-01)") as 001 T052 and T053. This packet owns them now.

## Summary

One GitHub Actions workflow (`.github/workflows/ci.yml`) runs three jobs. `test` checks the lockfile, installs from it, runs the tests, lints for real errors and audits the runtime dependencies. `image` builds the production image and checks it runs as non-root and fails closed. `deploy` runs only for `main`, after both, in the environment `production`, without an approval click (the owner's decision, FR-005). It signs in to Google Cloud through Workload Identity Federation as a least-privilege account and runs `scripts/deploy-cloud-run.sh` with `ONE_TIME_SETUP=0`. The script builds the commit on Cloud Build, deploys it to Cloud Run with the `kb` pin and the paywall, keeps only the new revision, and a smoke test checks two public URLs. Dependabot proposes weekly updates. `scripts/setup-github-deploy.sh` is the owner's one-time setup. Manual deploys and rollbacks use the same deploy script.

## Technical Context

**Language/Version**: GitHub Actions YAML, Bash, Dockerfile. The application and its tests: Python 3.12.

**Primary Dependencies**: in the `deploy` job, `actions/checkout` v7.0.1, `google-github-actions/auth` v3.0.0 and `google-github-actions/setup-gcloud` v3.0.1, pinned by commit SHA (T021); in `test` and `image`, `actions/checkout@v7` and `astral-sh/setup-uv@v7` by major tag; `uv` (`ghcr.io/astral-sh/uv:0.12.21`, pinned by digest in the image); `pip-audit` (run with `uvx`, latest release); Ruff; pytest; Docker on the GitHub runner; gcloud; Cloud Build; Artifact Registry repository `cloud-run-source-deploy`; Cloud Run service `onto-kb`; Secret Manager; IAM Workload Identity Federation.

**Storage**: Nothing new in the running service. Outside it: Cloud Run source deploys keep source archives in `gs://run-sources-<project-id>-<region>` and images in `cloud-run-source-deploy`; Cloud Build keeps build logs; GitHub keeps the public Actions logs, `setup-uv`'s package cache and the four Actions secrets (project identifiers, no credentials). None of these hold Drive content.

**Testing**: `tests/unit/test_build_config.py` reads `Dockerfile`, `pyproject.toml`, `uv.lock`, `ci.yml`, `dependabot.yml`, `.gitignore`, `.gcloudignore` and `.dockerignore` (8 tests, one of them `test_deploy_actions_are_pinned_by_commit_sha`, which requires every `deploy` job action to be pinned by commit SHA). `tests/unit/test_deploy_preflight.py` copies the deploy script into a temporary git repository and runs it with fake `gcloud` and `uv` on `PATH`, recording their arguments (8 tests, one of them with the repository `.gitignore` and a `gha-creds-*.json` file). The pipeline itself is exercised by real runs on GitHub; the first pipeline deploy completed in run 17 (runs 15 and 16 had stopped at the clean-tree preflight and at the source upload, fixed in e436ea0 and 6fa3143). No unit test pins the Actions secrets or the custom role from 6fa3143.

**Target Platform**: GitHub-hosted `ubuntu-latest` runners; Cloud Run in `GCP_REGION` (default `us-central1`).

**Project Type**: Delivery tooling for the web service (no change to the service).

**Performance Goals**: Job time limits: `test` 15 minutes, `image` 15 minutes, `deploy` 30 minutes.

**Constraints**: The repository and its Actions logs are public, so the project identifiers are Actions secrets. No Google Cloud key may be stored. The deploy identity cannot change project IAM or enable APIs, so those steps are operator-only (`ONE_TIME_SETUP=1`). Cloud Run: 1 GiB, concurrency 10, at most 3 instances, 60-second timeout (overridable by `CLOUD_RUN_CONCURRENCY` and `CLOUD_RUN_MAX_INSTANCES`). The `kb` folder id comes only from Secret Manager. The deploy refuses to run without the paywall.

**Scale/Scope**: One repository, one service, one person with write access (the owner).

### Threat model

Code the pipeline deploys runs as the runtime account, with every bound secret, including the owner's Drive credential (accepted risk, `.specify/memory/project-status.md`). The deploy account can also act as the runtime account through Cloud Build. Least privilege keeps the deploy account from changing project IAM, enabling APIs, reading other secrets or deploying other services; its only project-wide extras are listing bucket names and deleting revisions that serve no traffic (`ontoKbDeployExtras`). It does not limit what deployed code can do. The owner chose deploys without an approval click (2026-10-01), so the control for that is the owner's write access to `main`, as the only collaborator, and their review of each push and merge, Dependabot's included. CI stops broken and known-vulnerable code, not malicious code. The provider condition and the environment rule make sure only `main` jobs of this repository reach the deploy account. Residual risk the owner accepts with this choice: a compromised dependency the owner merges goes live without a click. CI does not catch it, and a branch ruleset (T017) only stops failing commits from being merged (they never deploy anyway). The deploy job's actions are pinned by commit SHA (T021), so a moved tag cannot reach the deploy identity. Adding a required reviewer back restores a per-deploy click without a code change.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Article | Applies | Gate |
| --- | --- | --- |
| Preamble: v1 scope | Yes | PASS: still one Google identity for Drive, read-only. The deploy account is a Google Cloud identity for deploys only and has no Drive access of its own. |
| I. Source of Truth | No | PASS: the pipeline reads no Drive content and keeps no copy of it. |
| II. No Mandatory RAG | No | PASS: no index is built or shipped. |
| III. Ephemeral Computation | Yes | PASS: the service stays stateless. The state outside it is explicit and documented here (Storage): source archives, images, build logs, Actions logs and the uv cache hold code and build output, not documents. Deleting old revisions removes stale configurations rather than adding state. |
| IV. Agent Owns the Loop | No | PASS: no tool behavior changes. |
| V. Minimal, Read-Only Capability Surface | Yes | PASS: the image ships the same four read-only tools; the build checks (002 T040 write-method scan) run in the `test` job. The deploy identity has no Drive access of its own. |
| VI. Documents Are Data | No | PASS: unchanged. |
| VII. Authorization Is Independent of Reasoning | Yes | PASS: every deploy re-applies the `kb` allow-list from Secret Manager, checks the newest revision carries it, deletes revisions that might not, and refuses to deploy without the paywall (004 FR-009). The `image` job proves the server refuses to start without the allow-list. |
| VIII–XI | No | PASS: evidence, search, completeness and error semantics are unchanged. |
| XII. Domain Is Not the API | Yes | PASS: CI, Cloud Build and Cloud Run are infrastructure; swapping them changes no domain promise. |
| XIII. Model and Client Agnosticism | No | PASS: unchanged. |
| XIV. Change Control | Yes | PASS: **PATCH**. No behavior or invariant of the server changes and no capability is added to it. Not MINOR (no new server capability) and not MAJOR (no invariant, security boundary, source-of-truth model or evidence semantic changes). The deploy identity is new, but the server's request-time boundary (the Article VII chain, the `kb` allow-list, the paywall) is unchanged, and the owner still decides what goes live: by the owner's decision deploys need no approval click (FR-005), and only the owner can put a commit on `main`. The owner is still the only one who can ship code, so PATCH stands. Precedence holds: security invariants (the `kb` pin, the paywall) stop a deploy rather than yield to it. |
| XV. Constitutional Fitness | Yes | PASS: every fitness line is unchanged; the pipeline only ships code that must already conform. |

No amendment is needed under Governance: the constitution text does not change and stays v1.0.0.

**Post-design re-check**: Still PASS. T014 (e436ea0), T016 and T022–T023 (6fa3143, run 17), the closed T024 (owner decision: no approval click), T021 (SHA pins), T015 (identifiers as secrets) and the open tasks (T017–T020) change delivery settings only.

## Project Structure

### Documentation (this feature)

```text
specs/005-delivery-pipeline/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── ci-workflow.md
│   └── deploy-scripts.md
├── checklists/
│   └── requirements.md
└── tasks.md
```

### Source Code (repository root)

```text
.github/
├── workflows/ci.yml              # test, image, deploy jobs
└── dependabot.yml                # weekly uv, docker, github-actions; python patch only
Dockerfile                        # uv-pinned builder from uv.lock; slim runtime as uid 10001
.gitignore                        # includes gha-creds-*.json (sign-in credentials file)
.gcloudignore                     # what `gcloud run deploy --source` uploads: not .git, .github, git-ignored files
.dockerignore                     # also excludes gha-creds-*.json
pyproject.toml                    # bounded runtime deps; dev group for test tools
uv.lock                           # the only source of installed versions (CI and image)
scripts/
├── deploy-cloud-run.sh           # preflight, refusals, Cloud Build + Cloud Run, kb guard, cleanup
├── setup-github-deploy.sh        # one-time: deploy account, custom role, WIF pool and provider, grants
└── ensure-connect-telemetry-gcp.sh  # operator step (ONE_TIME_SETUP=1): log metrics, dashboard
tests/unit/
├── test_build_config.py
└── test_deploy_preflight.py
```

**Structure Decision**: One workflow file with three jobs, so the `deploy` job can name `test` and `image` in `needs`. One deploy script for the pipeline and for manual deploys, so both apply the same refusals, `kb` guard and cleanup; `ONE_TIME_SETUP` separates what only an owner may run.

## Complexity Tracking

> No constitution violations requiring justification.
