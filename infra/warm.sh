#!/usr/bin/env bash
# Toggle min-instances. Usage: bash infra/warm.sh on|off   (on = 1 warm instance, ~2 vCPU/4Gi idle cost)
set -euo pipefail
export CLOUDSDK_ACTIVE_CONFIG_NAME="${CLOUDSDK_ACTIVE_CONFIG_NAME:-andon}"
PROJECT="${PROJECT:-andon-agent-511218}"; REGION="${REGION:-asia-south1}"
case "${1:-}" in on) MIN=1;; off) MIN=0;; *) echo "usage: warm.sh on|off"; exit 2;; esac
gcloud run services update andon-api --project "$PROJECT" --region "$REGION" --min-instances "$MIN" --quiet
URL=$(gcloud run services describe andon-api --project "$PROJECT" --region "$REGION" --format='value(status.url)')
if [[ "$MIN" == "1" ]]; then
  H=(); [[ "${TOKEN:-}" ]] && H=(-H "Authorization: Bearer $TOKEN")
  curl -fsS --max-time 60 ${H[@]+"${H[@]}"} "$URL/health" && echo " warm-up ok"
fi
echo "min-instances=$MIN"
