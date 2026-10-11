#!/usr/bin/env bash
# End-to-end smoke test. Usage: bash scripts/smoke.sh <API_URL>
# Env: TOKEN=<identity token> for a private service; PASSCODE=1 to also run one live investigation
# (passcode is read from Secret Manager into a variable and never printed); SCENARIO (default S001);
# REPLAY_RUN (run_id for replay; default: first one listed by the API).
set -uo pipefail
export CLOUDSDK_ACTIVE_CONFIG_NAME="${CLOUDSDK_ACTIVE_CONFIG_NAME:-andon}"
URL="${1:?usage: smoke.sh <API_URL>}"; URL="${URL%/}"
SCENARIO="${SCENARIO:-S001}"
AUTHH=(); [[ -n "${TOKEN:-}" ]] && AUTHH=(-H "Authorization: Bearer $TOKEN")
fail() { echo "FAIL: $*"; exit 1; }
now() { python3 -c 'import time;print(time.time())'; }

echo "== (a) GET /health"
body=$(curl -fsS --max-time 30 ${AUTHH[@]+"${AUTHH[@]}"} "$URL/health") || fail "/health"
echo "$body"; echo "$body" | grep -Eq '"status" *: *"ok"' || fail "/health not ok"

echo "== (b) GET /api/scenarios"
sc=$(curl -fsS --max-time 30 ${AUTHH[@]+"${AUTHH[@]}"} "$URL/api/scenarios") || fail "/api/scenarios"
echo "$sc" | python3 -c 'import sys,json;d=json.load(sys.stdin);g=d.get("groups") if isinstance(d,dict) else None;n=sum(len(x.get("scenarios",[])) for x in g) if g else (len(d) if isinstance(d,list) else 0);print("scenarios:",n);sys.exit(0 if n else 1)' || fail "no scenarios"

# Stream an SSE endpoint, print per-event arrival time, succeed only if `done` arrives in time.
# Many events arriving in one lump (all within 0.2 s of each other after a long wait) = buffering.
stream() { # $1=label $2=timeout $3...=curl args
  local label="$1" tmo="$2"; shift 2
  curl -sN --max-time "$tmo" ${AUTHH[@]+"${AUTHH[@]}"} "$@" | python3 -u -c '
import sys,time
t0=time.time();first=None;last=None;names=[];cur=None;gaps=0
for line in sys.stdin:
    line=line.rstrip("\n")
    if line.startswith("event:"): cur=line[6:].strip()
    elif line.startswith("data:") and cur:
        t=time.time()-t0; names.append(cur)
        if len(names)<=40 or cur in ("done","error","budget_exhausted"): print("  +%6.2fs  %s"%(t,cur))
        if last is not None and t-last>0.5: gaps+=1
        last=t; cur=None
        if cur is None and names[-1]=="done": break
print("  events=%d distinct_gaps>0.5s=%d"%(len(names),gaps))
if "done" not in names: print("  no done event"); sys.exit(1)
if len(names)>5 and gaps==0 and last>3: print("  WARN: events arrived in a lump (buffering?)")
'
  [[ ${PIPESTATUS[1]} -eq 0 ]] || fail "$label"
}

# Replay: default to the first run the API lists (a scenario without a recording is a 404 by design).
RUN="${REPLAY_RUN:-}"; RSC="$SCENARIO"
if [[ -z "$RUN" ]]; then
  read -r RUN RSC < <(curl -fsS --max-time 30 ${AUTHH[@]+"${AUTHH[@]}"} "$URL/api/replays" | python3 -c 'import sys,json;r=json.load(sys.stdin)["replays"];print(r[0]["run_id"],r[0]["scenario_id"]) if r else print("","")') || fail "/api/replays"
  [[ -n "$RUN" ]] || fail "no replays listed"
fi
echo "== (c) replay SSE ($RSC, run $RUN, speed 4)"
stream "replay" 120 "$URL/api/incidents/$RSC/investigate?mode=replay&run_id=$RUN&speed=4" -X POST

if [[ -n "${PASSCODE:-}" ]]; then
  echo "== (d) live run (spends real money, see DEVELOPMENT.md ledger)"
  PC=$(gcloud secrets versions access latest --secret demo-passcode 2>/dev/null) || fail "cannot read passcode secret"
  stream "live" 600 "$URL/api/incidents/$SCENARIO/investigate?mode=live" -X POST -H "X-Demo-Passcode: $PC"
  unset PC
fi
echo "PASS"
