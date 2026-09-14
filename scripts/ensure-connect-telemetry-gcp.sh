#!/usr/bin/env bash
# Create or update log-based metrics and the Cloud Monitoring dashboard
# for feature 003 (connect counter). Safe to run repeatedly.
#
# Labels must go through --config-from-file (LogMetric JSON). This gcloud
# does not accept --label-extractors.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT="${GOOGLE_CLOUD_PROJECT:-${GCP_PROJECT:-project-84207120-95a7-43ac-95e}}"
PYTHON="${PYTHON:-python3}"
if [[ -x "${ROOT}/.venv/bin/python" ]]; then
  PYTHON="${ROOT}/.venv/bin/python"
fi
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}"

if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud is not on PATH. Install the Google Cloud SDK and authenticate." >&2
  exit 1
fi

gcloud services enable \
  logging.googleapis.com \
  monitoring.googleapis.com \
  --project="${PROJECT}" >/dev/null

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

echo "Ensuring log-based metrics in ${PROJECT}..."
for metric_id in onto_kb_oauth_connects onto_kb_drive_first_uses; do
  config_file="${tmpdir}/${metric_id}.json"
  METRIC_ID="${metric_id}" "${PYTHON}" - <<'PY' > "${config_file}"
import json
import os

from google_drive_mcp.infra.telemetry.gcp_console import log_metric_resource_for_id

print(json.dumps(log_metric_resource_for_id(os.environ["METRIC_ID"])))
PY
  if gcloud logging metrics describe "${metric_id}" --project="${PROJECT}" >/dev/null 2>&1; then
    gcloud logging metrics update "${metric_id}" \
      --project="${PROJECT}" \
      --config-from-file="${config_file}"
  else
    gcloud logging metrics create "${metric_id}" \
      --project="${PROJECT}" \
      --config-from-file="${config_file}"
  fi
done

echo "Ensuring Cloud Monitoring dashboard 'onto-kb connect counter'..."
dash_file="${tmpdir}/dashboard.json"

existing="$("${PYTHON}" - "${PROJECT}" <<'PY'
import json
import subprocess
import sys

project = sys.argv[1]
out = subprocess.check_output(
    [
        "gcloud",
        "monitoring",
        "dashboards",
        "list",
        f"--project={project}",
        "--format=json",
    ],
    text=True,
)
for dash in json.loads(out or "[]"):
    if dash.get("displayName") == "onto-kb connect counter":
        print(dash["name"])
        break
PY
)"

if [[ -n "${existing}" ]]; then
  etag="$(gcloud monitoring dashboards describe "${existing}" \
    --project="${PROJECT}" \
    --format='value(etag)')"
  DASH_NAME="${existing}" DASH_ETAG="${etag}" "${PYTHON}" - <<'PY' > "${dash_file}"
import json
import os

from google_drive_mcp.infra.telemetry.gcp_console import dashboard_update_config

print(json.dumps(dashboard_update_config(name=os.environ["DASH_NAME"], etag=os.environ["DASH_ETAG"])))
PY
  gcloud monitoring dashboards update "${existing}" \
    --project="${PROJECT}" \
    --config-from-file="${dash_file}"
else
  "${PYTHON}" - <<'PY' > "${dash_file}"
import json

from google_drive_mcp.infra.telemetry.gcp_console import dashboard_config

print(json.dumps(dashboard_config()))
PY
  gcloud monitoring dashboards create \
    --project="${PROJECT}" \
    --config-from-file="${dash_file}"
fi

echo "GCP connect telemetry is ready."
echo "Dashboard: https://console.cloud.google.com/monitoring/dashboards?project=${PROJECT}"
echo "Metrics Explorer: https://console.cloud.google.com/monitoring/metrics-explorer?project=${PROJECT}"
echo "Log-based metrics: logging.googleapis.com/user/onto_kb_oauth_connects and onto_kb_drive_first_uses"
