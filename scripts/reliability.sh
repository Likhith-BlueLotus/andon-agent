#!/usr/bin/env bash
# Phase 6 reliability: N consecutive live investigations on the deployed API, p50/p95 latency.
# Usage: bash scripts/reliability.sh [R002,S014,S005,R002,S005]   (~$0.15 per run)
# Also kills one stream after 15 s to check server-side cancel (LOG it in Cloud Run logs).
set -uo pipefail
export CLOUDSDK_ACTIVE_CONFIG_NAME="${CLOUDSDK_ACTIVE_CONFIG_NAME:-andon}"
PROJECT="${PROJECT:-andon-511816}"; REGION="${REGION:-asia-south1}"
NUM=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
API="${API_URL:-https://andon-api-$NUM.$REGION.run.app}"; O="Origin: https://andon-agent-b9c77.web.app"
IFS=, read -ra IDS <<<"${1:-R002,S014,S005,R002,S005}"
PC=$(gcloud secrets versions access latest --secret demo-passcode --project "$PROJECT")
times=(); fails=0
for sid in "${IDS[@]}"; do
  t0=$(python3 -c 'import time;print(time.time())')
  out=$(curl -sN -X POST --max-time 600 "$API/api/incidents/$sid/investigate?mode=live" -H "X-Demo-Passcode: $PC" -H "$O")
  dt=$(python3 -c "import time;print(round(time.time()-$t0,1))")
  verdict=$(grep -o '"overall":"[A-Z]*"' <<<"$out" | tail -1); err=$(grep -o '"type":"error"[^}]*"code":"[a-z_]*"' <<<"$out" | grep -o 'code":"[a-z_]*' | head -1)
  top=$(python3 -c 'import json,sys
for l in sys.stdin:
    if l.startswith("data: ") and "\"rca_final\"" in l:
        h=json.loads(l[6:])["data"]["hypotheses"][0]; print(h["cause_class"]+"@"+h["asset_id"]); break' <<<"$out")
  usd=$(grep -o '"type":"cost".*"usd":[0-9.]*' <<<"$out" | grep -o '"usd":[0-9.]*' | tail -1)
  fb=$(grep -c '"type":"model_fallback"' <<<"$out")
  echo "$sid  ${dt}s  ${verdict:-no-verdict}  ${top:-no-rca}  ${usd:-}  fallbacks=$fb  ${err:+ERROR $err}"
  [[ -n "$err" || -z "$verdict" ]] && fails=$((fails + 1)); times+=("$dt")
done
python3 -c "
import statistics,sys; t=sorted(map(float,sys.argv[1:])); n=len(t)
print(f'runs={n} p50={statistics.median(t):.1f}s p95={t[min(n-1,round(0.95*(n-1)))]:.1f}s max={t[-1]:.1f}s')" "${times[@]}"
echo "failures=$fails"
echo "-- cancel check: stream cut after 15 s"
curl -sN -X POST --max-time 15 "$API/api/incidents/S005/investigate?mode=live" -H "X-Demo-Passcode: $PC" -H "$O" >/dev/null; unset PC
echo "cut at $(date -u +%H:%M:%SZ); now run: gcloud logging read 'resource.labels.service_name=\"andon-api\" AND textPayload:\"investigation cancelled\"' --project $PROJECT --freshness=10m --limit 5 --format='value(textPayload)'"
