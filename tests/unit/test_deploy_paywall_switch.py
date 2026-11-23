"""deploy-cloud-run.sh: the paywall switch and the kb pin reach `gcloud run deploy`.

A fake gcloud records every call. The script must hand MCP_SUBSCRIPTION_REQUIRED=true and
the kb folder id to the deploy, and must stop before any deploy when a Stripe secret is
missing: without the paywall the server would serve kb to anyone.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "deploy-cloud-run.sh"
KB_ID = "1kbFolderIdUsedOnlyInTests000000"
ALL_SECRETS = [
    "MCP_AUTH_TOKEN",
    "GOOGLE_AUTHORIZED_USER_JSON",
    "MCP_PRINCIPAL_ID",
    "DRIVE_ALLOWED_FOLDER_ID",
    "STRIPE_SECRET_KEY",
    "STRIPE_PRICE_ID",
]

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None, reason="needs bash and git"
)

FAKE_GCLOUD = """#!/bin/sh
echo "$*" >> "$FAKE_GCLOUD_LOG"
case "$1 $2" in
  "auth print-access-token") echo token; exit 0 ;;
  "secrets describe")
    case ",$FAKE_SECRETS," in *",$3,"*) exit 0 ;; esac
    exit 1 ;;
  "secrets versions") printf '%s' "$FAKE_KB_ID"; exit 0 ;;
  "run deploy") exit 7 ;;
  "run services") echo "https://onto-kb-test.example"; exit 0 ;;
esac
exit 0
"""


def _deploy(tmp_path: Path, secrets: list[str], kb_id: str = KB_ID):
    """Run the script against a clean temporary repo and a fake gcloud."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / "deploy-cloud-run.sh")
    (repo / "README").write_text("x\n")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "init"], check=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gcloud = bin_dir / "gcloud"
    gcloud.write_text(FAKE_GCLOUD)
    gcloud.chmod(0o755)
    log = tmp_path / "gcloud.log"
    git_dir = os.path.dirname(shutil.which("git") or "/usr/bin/git")
    env = {
        "PATH": os.pathsep.join([str(bin_dir), git_dir, "/usr/bin", "/bin"]),
        "HOME": str(tmp_path),
        "GCP_PROJECT": "test-project",
        "SKIP_TESTS": "1",
        "ONE_TIME_SETUP": "0",
        "FAKE_GCLOUD_LOG": str(log),
        "FAKE_SECRETS": ",".join(secrets),
        "FAKE_KB_ID": kb_id,
    }
    proc = subprocess.run(
        ["bash", str(repo / "scripts" / "deploy-cloud-run.sh")],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return proc, [line for line in calls if line.startswith("run deploy")]


def test_the_deploy_carries_the_paywall_switch_and_the_kb_pin(tmp_path: Path):
    proc, deploys = _deploy(tmp_path, ALL_SECRETS)
    assert len(deploys) == 1, proc.stderr
    assert "MCP_SUBSCRIPTION_REQUIRED=true" in deploys[0]
    assert f"DRIVE_ALLOWED_FOLDER_ID={KB_ID}" in deploys[0]


@pytest.mark.parametrize("missing", ["STRIPE_SECRET_KEY", "STRIPE_PRICE_ID"])
def test_a_missing_stripe_secret_stops_the_deploy_before_it_starts(tmp_path: Path, missing: str):
    proc, deploys = _deploy(tmp_path, [s for s in ALL_SECRETS if s != missing])
    assert deploys == []
    assert proc.returncode != 0
    assert "Refusing to deploy without the paywall" in proc.stderr


@pytest.mark.parametrize("bad_id", ["root", "short", "has spaces in it 123"])
def test_a_folder_secret_that_is_not_a_drive_folder_id_stops_the_deploy(tmp_path: Path, bad_id: str):
    proc, deploys = _deploy(tmp_path, ALL_SECRETS, kb_id=bad_id)
    assert deploys == []
    assert proc.returncode != 0
    assert "not a Drive folder id" in proc.stderr
