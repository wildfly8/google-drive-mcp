"""Build and supply-chain settings: image from uv.lock as non-root, bounded deps, CI, Dependabot."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _name(requirement: str) -> str:
    return re.split(r"[<>=!~;\[ ]", requirement, maxsplit=1)[0].lower()


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_image_installs_from_lockfile_and_runs_as_non_root():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "pip install" not in text
    assert re.search(r"ghcr\.io/astral-sh/uv:\d+\.\d+\.\d+", text)
    assert re.search(r"^RUN uv sync --frozen --no-dev\b", text, re.M)
    runtime = text.split("\nFROM ")[-1]
    users = re.findall(r"^USER (\S+)", runtime, re.M)
    assert users and users[-1] not in {"root", "0", "0:0"}
    assert 'CMD ["python", "-m", "google_drive_mcp"]' in runtime


def test_runtime_dependencies_are_bounded_and_exclude_test_tools():
    project = _pyproject()
    deps = {_name(d): d for d in project["project"]["dependencies"]}
    assert ">=2.2" in deps["mcp"] and "<3" in deps["mcp"]
    for imported in ("starlette", "uvicorn", "regex"):
        assert imported in deps
    dev = {_name(d) for d in project["dependency-groups"]["dev"]}
    for tool in ("pytest", "pytest-asyncio", "ruff"):
        assert tool not in deps
        assert tool in dev


def test_lockfile_matches_pyproject_dependencies():
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    root = next(p for p in lock["package"] if p["name"] == "google-drive-mcp")
    project = _pyproject()
    locked = {d["name"] for d in root["metadata"]["requires-dist"]}
    assert locked == {_name(d) for d in project["project"]["dependencies"]}
    locked_dev = {d["name"] for d in root["metadata"]["requires-dev"]["dev"]}
    assert locked_dev == {_name(d) for d in project["dependency-groups"]["dev"]}


def test_ci_runs_tests_lint_and_audit_from_the_lockfile():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for needle in (
        "push:",
        "pull_request:",
        "astral-sh/setup-uv@v",
        "uv sync --frozen",
        "uv run pytest -q --ignore=tests/e2e",
        "uv run ruff check --select F,E9 src tests",
        "uv export --frozen --no-dev",
        "uvx pip-audit",
    ):
        assert needle in text, needle


def test_dependabot_covers_uv_docker_and_actions_weekly():
    text = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    for ecosystem in ("uv", "docker", "github-actions"):
        assert f'package-ecosystem: "{ecosystem}"' in text
    assert text.count('interval: "weekly"') == 3


def test_deploy_waits_for_tests_and_a_working_image():
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    image = text[text.index("\n  image:") : text.index("\n  deploy:")]
    for needle in (
        "docker build --pull --tag onto-kb:ci .",
        'test "$(docker run --rm onto-kb:ci id -u)" = "10001"',
        'python -c "import google_drive_mcp.mcp.server"',
        'grep -q "DRIVE_ALLOWED_FOLDER_ID"',
    ):
        assert needle in image, needle
    deploy = text[text.index("\n  deploy:") :]
    assert "needs: [test, image]" in deploy
    assert "environment: production" in deploy
    assert "github.ref == 'refs/heads/main'" in deploy
    assert "ONE_TIME_SETUP: \"0\"" in deploy


def test_ci_credentials_are_never_committed_or_uploaded():
    # google-github-actions/auth writes gha-creds-*.json into the workspace.
    assert "gha-creds-*.json" in (ROOT / ".gitignore").read_text(encoding="utf-8")
    gcloudignore = (ROOT / ".gcloudignore").read_text(encoding="utf-8")
    assert "gha-creds-*.json" in gcloudignore
    assert "#!include:.gitignore" in gcloudignore
    assert "gha-creds-*.json" in (ROOT / ".dockerignore").read_text(encoding="utf-8")
