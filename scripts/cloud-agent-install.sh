#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap: uv + pinned specify-cli for Spec-Kit SDD.
set -euo pipefail

export PATH="${HOME}/.local/bin:${PATH}"

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

# uv's installer writes env to ~/.local/bin/env; source it when present.
if [[ -f "${HOME}/.local/bin/env" ]]; then
  # shellcheck disable=SC1091
  source "${HOME}/.local/bin/env"
fi

export PATH="${HOME}/.local/bin:${PATH}"

# Pin to the Spec Kit release used to scaffold this repository.
uv tool install "specify-cli==1.0.4"

if ! command -v specify >/dev/null 2>&1; then
  echo "specify CLI is not on PATH after install" >&2
  exit 1
fi

specify version
echo "cloud-agent-install: specify-cli 1.0.4 ready"
