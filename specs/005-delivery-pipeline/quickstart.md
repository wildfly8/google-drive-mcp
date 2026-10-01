# Quickstart: 005 Delivery Pipeline

Placeholders: `<project-id>`, `<project-number>`, `<region>` (default `us-central1`). Never paste real values into the repository, an issue or a pull request.

## One-time owner setup

0. **First manual deploy.** The pipeline needs the service, the source bucket, the image repository and the secrets to exist. Follow `specs/004-paid-subscription/quickstart.md` for the secrets, then, from a clean checkout of `main` with your own gcloud login:

   ```bash
   GCP_PROJECT=<project-id> bash scripts/deploy-cloud-run.sh
   ```

   This also runs the one-time setup (APIs, runtime account grants, telemetry dashboard).

1. **Deploy identity.** In Cloud Shell, as a project owner:

   ```bash
   git clone https://github.com/wildfly8/google-drive-mcp.git
   cd google-drive-mcp
   GCP_PROJECT=<project-id> GCP_REGION=<region> bash scripts/setup-github-deploy.sh
   ```

   It creates `onto-kb-deployer`, the pool `onto-kb-github`, the provider `github` and the custom role `ontoKbDeployExtras`, grants the deploy roles, and prints what to add in GitHub. Safe to re-run. If you ran it before 6fa3143, run it again: the custom role is what lets the deploy upload the source and delete old revisions.

2. **GitHub environment.** Repository Settings → Environments → New environment `production`:
   - Deployment branches and tags: Selected branches → `main`.
   - Required reviewers: none (your decision of 2026-10-01, FR-005), so every push to `main` that passes CI goes live. Add yourself here at any time if you want each deploy to wait for a click; no code change is needed.

3. **GitHub secrets and variable.** Settings → Secrets and variables → Actions, with the values the script printed. Secrets tab (GitHub hides them in every log line):

   ```text
   GCP_PROJECT_ID      <project-id>
   GCP_PROJECT_NUMBER  <project-number>
   GCP_WIF_PROVIDER    projects/<project-number>/locations/global/workloadIdentityPools/onto-kb-github/providers/github
   GCP_DEPLOY_SA       onto-kb-deployer@<project-id>.iam.gserviceaccount.com
   ```

   Variables tab (turns the `deploy` job on):

   ```text
   GCP_REGION          <region>
   ```

   If the four identifiers also exist as variables, delete those variables: a variable is printed once in the mask step's header. Then delete the logs of any run that read them from variables: Actions → the run → ⋯ → Delete all logs (T015). From Cloud Shell, `gh secret set NAME -R wildfly8/google-drive-mcp -b VALUE` and `gh variable delete NAME -R wildfly8/google-drive-mcp` do the same as the Settings page.

4. **Optional, recommended**: a branch ruleset on `main` that requires the `test` and `image` checks (T017).

Check: the next push to `main` runs the `deploy` job right after `test` and `image`, and its "Mask project identifiers" step shows only `***`.

## Day to day

1. **Push.** Work on a branch or push to `main`. CI runs `test` and `image` on every push and pull request.
2. **Deploy.** A push to `main` that passes both deploys by itself. Review what you push or merge: there is no later click. (With a required reviewer added back: open the run → Review deployments → `production` → Approve and deploy, or Reject to skip that commit.)
3. **Verify.** The `deploy` job is green: the deploy script printed `Deploy complete` and the smoke test printed `Live: /subscribe and protected-resource metadata answer.` In the Cloud Run console the service has one revision with 100% of traffic. For a deeper check, Connect an AI chat app with your own subscription and call a `drive_*` tool. The live suite `tests/e2e/test_live_mcp.py` finishes OAuth with the consent password, which a paywalled deployment does not offer, so it cannot run against production as written (T019).

4. **Roll back.** Preferred: `git revert <bad-commit>` and push to `main`; it deploys once CI passes. Or deploy an older good commit by hand (from 11eccc9 on only: earlier deploy scripts pin a `kb` folder id written in the script instead of Secret Manager, and those before b367728 do not refuse to deploy without the paywall):

   ```bash
   git checkout <good-commit>
   GCP_PROJECT=<project-id> bash scripts/deploy-cloud-run.sh
   git checkout main
   ```

   Old revisions are deleted on every deploy, so there is no traffic switch back to them.

5. **Manual deploy.** From a clean checkout of `main` with your own login:

   ```bash
   GCP_PROJECT=<project-id> bash scripts/deploy-cloud-run.sh            # with the one-time setup
   ONE_TIME_SETUP=0 GCP_PROJECT=<project-id> bash scripts/deploy-cloud-run.sh   # as the CI deploy does
   ```

   It refuses uncommitted or untracked files that are not git-ignored (`ALLOW_DIRTY=1` overrides) and runs the tests first (`SKIP_TESTS=1` skips).

6. **After adding a secret** (for example `IDENTITY_TOOLKIT_API_KEY`): run one manual deploy with the one-time setup, so the runtime account can read it. A CI deploy alone binds it but cannot grant access, and the new revision would not start.

7. **Revisions left behind.** If the deploy says `Could not delete revisions: …`, move any traffic off them and delete them in the Cloud Run console or with `gcloud run revisions delete <revision> --region=<region>`.

8. **Dependabot.** Weekly pull requests for `uv.lock`, the Docker images and the actions (for the `deploy` job's actions, a new commit SHA and release comment). Merge after CI passes and you have read the change and, for an action, its release notes; each merge to `main` deploys at once. Close any pull request that moves Python to a new minor version.

## Automated checks

```bash
uv run pytest tests/unit/test_build_config.py tests/unit/test_deploy_preflight.py -q
```
