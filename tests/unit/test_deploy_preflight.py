"""deploy-cloud-run.sh preflight: committed tree and passing tests before any gcloud call."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "deploy-cloud-run.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None, reason="needs bash and git"
)


def _fake(path: Path, log: Path, exit_code: int) -> None:
    path.write_text(f'#!/bin/sh\necho "$@" >> "{log}"\nexit {exit_code}\n')
    path.chmod(0o755)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, root / "scripts" / "deploy-cloud-run.sh")
    (root / "README").write_text("x\n")
    git = ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "init"], check=True)
    return root


def _run(repo: Path, tmp_path: Path, *, uv_exit: int = 0, **env: str):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gcloud_log = tmp_path / "gcloud.log"
    uv_log = tmp_path / "uv.log"
    # gcloud fails its first call (auth check), so a run that gets past preflight stops there.
    _fake(bin_dir / "gcloud", gcloud_log, 1)
    _fake(bin_dir / "uv", uv_log, uv_exit)
    git_dir = os.path.dirname(shutil.which("git") or "/usr/bin/git")
    full_env = {
        "PATH": os.pathsep.join([str(bin_dir), git_dir, "/usr/bin", "/bin"]),
        "HOME": str(tmp_path),
        "GCP_PROJECT": "test-project",
        **env,
    }
    proc = subprocess.run(
        ["bash", str(repo / "scripts" / "deploy-cloud-run.sh")],
        cwd=repo,
        env=full_env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc, _read(gcloud_log), _read(uv_log)


def _read(path: Path) -> str:
    return path.read_text() if path.exists() else ""


@pytest.mark.parametrize("dirty", ["untracked", "modified"])
def test_dirty_tree_refused_before_gcloud(repo: Path, tmp_path: Path, dirty: str):
    if dirty == "untracked":
        (repo / "new.txt").write_text("x\n")
    else:
        (repo / "README").write_text("changed\n")
    proc, gcloud_calls, uv_calls = _run(repo, tmp_path)
    assert proc.returncode != 0
    assert "Uncommitted changes" in proc.stderr
    assert gcloud_calls == ""
    assert uv_calls == ""


def test_failing_tests_stop_deploy_before_gcloud(repo: Path, tmp_path: Path):
    proc, gcloud_calls, uv_calls = _run(repo, tmp_path, uv_exit=1)
    assert proc.returncode != 0
    assert "Tests failed" in proc.stderr
    assert "pytest -q --ignore=tests/e2e" in uv_calls
    assert gcloud_calls == ""


def test_clean_tree_and_passing_tests_reach_gcloud(repo: Path, tmp_path: Path):
    proc, gcloud_calls, uv_calls = _run(repo, tmp_path)
    assert "run --locked pytest -q --ignore=tests/e2e" in uv_calls
    assert gcloud_calls != ""
    assert "Uncommitted changes" not in proc.stderr


def test_allow_dirty_and_skip_tests(repo: Path, tmp_path: Path):
    (repo / "new.txt").write_text("x\n")
    proc, gcloud_calls, uv_calls = _run(repo, tmp_path, ALLOW_DIRTY="1", SKIP_TESTS="1")
    assert "Uncommitted changes" not in proc.stderr
    assert uv_calls == ""
    assert gcloud_calls != ""
