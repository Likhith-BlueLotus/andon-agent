#!/usr/bin/env bash
# End-to-end smoke test against a deployed (or local) API. Usage: bash scripts/smoke.sh <API_URL>
set -euo pipefail
URL="${1:?usage: smoke.sh <API_URL>}"
URL="${URL%/}"
echo "GET $URL/healthz"
body=$(curl -fsS --max-time 30 "$URL/healthz")
echo "$body"
echo "$body" | grep -q '"status":"ok"' || { echo "FAIL: healthz not ok"; exit 1; }
echo "PASS"
