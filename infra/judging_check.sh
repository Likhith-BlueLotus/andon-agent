#!/usr/bin/env bash
# Daily judging-window check (Oct 19 - Nov 6; finale Dec 4). Costs nothing unless LIVE=1.
# Usage: bash infra/judging_check.sh            # replay-only checks, $0
#        LIVE=1 bash infra/judging_check.sh     # + one live R002 investigation (~$0.15)
# Prints PASS/FAIL per check and exits non-zero on any failure. Never prints the passcode.
set -uo pipefail
export CLOUDSDK_ACTIVE_CONFIG_NAME="${CLOUDSDK_ACTIVE_CONFIG_NAME:-andon}"
PROJECT="${PROJECT:-andon-511816}"; REGION="${REGION:-asia-south1}"
NUM=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
API="${API_URL:-https://andon-api-$NUM.$REGION.run.app}"
WEB="${WEB_URL:-https://andon-agent-b9c77.web.app}"
fails=0
ok()  { echo "PASS  $*"; }
bad() { echo "FAIL  $*"; fails=$((fails + 1)); }

h=$(curl -s --max-time 30 "$API/health")
[[ "$h" == *'"status":"ok"'* ]] && ok "health ($(python3 -c 'import json,sys;d=json.loads(sys.argv[1]);print(d.get("git_sha"),d["models"]["judge"])' "$h"))" || bad "health: ${h:0:120}"
[[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$WEB")" == 200 ]] && ok "web $WEB" || bad "web $WEB"
c=$(curl -s --max-time 30 "$API/api/config")
python3 - "$c" <<'PY' && ok "budget not exhausted" || bad "budget: ${c:0:160}"
import json, sys
d = json.loads(sys.argv[1]); b = d["budget"]
print(f"      remaining ${b['remaining_usd']:.2f} of ${b['daily_usd']:.2f} today; features {d.get('features')}")
sys.exit(1 if b["exhausted"] else 0)
PY
n=$(curl -s --max-time 30 "$API/api/scenarios" | python3 -c 'import json,sys;print(sum(len(g["scenarios"]) for g in json.load(sys.stdin)["groups"]))' 2>/dev/null)
[[ "$n" == 77 ]] && ok "77 scenarios" || bad "scenarios: $n"
e=$(curl -s --max-time 30 "$API/api/eval/latest" | python3 -c 'import json,sys;print(json.load(sys.stdin)["run_id"])' 2>/dev/null)
[[ -n "$e" ]] && ok "eval published ($e)" || bad "eval/latest"
acao=$(curl -s -D - -o /dev/null -X OPTIONS "$API/api/config" -H "Origin: $WEB" -H "Access-Control-Request-Method: GET" | tr -d '\r' | awk -F': ' 'tolower($1)=="access-control-allow-origin"{print $2}')
[[ "$acao" == "$WEB" ]] && ok "CORS" || bad "CORS allow-origin='$acao'"
r=$(curl -sN -X POST --max-time 120 "$API/api/incidents/R002/investigate?mode=replay&run_id=r002-cloud-1&speed=4" -H "Origin: $WEB")
[[ "$r" == *'"type":"done"'* && "$r" == *'"type":"rca_final"'* ]] && ok "replay R002 streams to done" || bad "replay R002"
if [[ "${LIVE:-0}" == "1" ]]; then
  PC=$(gcloud secrets versions access latest --secret demo-passcode --project "$PROJECT")
  t0=$(date +%s)
  l=$(curl -sN -X POST --max-time 600 "$API/api/incidents/R002/investigate?mode=live" -H "X-Demo-Passcode: $PC" -H "Origin: $WEB")
  unset PC
  [[ "$l" == *'"overall":"PASS"'* && "$l" == *'"type":"done"'* ]] && ok "live R002 PASS in $(( $(date +%s) - t0 )) s" || bad "live R002: $(grep -o '"code":"[a-z_]*"' <<<"$l" | head -1)"
fi
[[ $fails == 0 ]] && echo "ALL PASS" || { echo "$fails FAILED"; exit 1; }
