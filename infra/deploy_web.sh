#!/usr/bin/env bash
# Build the React app against the Cloud Run API and deploy it to Firebase Hosting.
# Usage: bash infra/deploy_web.sh
# Env:   VITE_API_URL  override the API origin (default: Cloud Run URL of andon-api)
#        SKIP_TESTS=1  skip `npm test`
# Config: firebase.json (hosting, SPA rewrite, cache + security headers; see docs/RUNBOOK_JUDGING.md).
#   The CSP in firebase.json pins connect-src/media-src to the Cloud Run API origin; if the API URL
#   changes, update firebase.json too (this script warns on mismatch). We call Cloud Run directly
#   (CORS), not through a Hosting rewrite, because rewrites time out on long SSE streams.
# Needs: `firebase login` as the owner (CLI 15.x); hosting site $FIREBASE_PROJECT exists.
set -euo pipefail
export CLOUDSDK_ACTIVE_CONFIG_NAME="${CLOUDSDK_ACTIVE_CONFIG_NAME:-andon}"
PROJECT="${PROJECT:-andon-511816}"            # GCP project of the API (Cloud Run)
FIREBASE_PROJECT="${FIREBASE_PROJECT:-andon-agent-b9c77}"  # separate Firebase project that only hosts the static app (ADR-024)
REGION="${REGION:-asia-south1}"
cd "$(dirname "$0")/.."
SITE_URL="https://$FIREBASE_PROJECT.web.app"

# deterministic URL form https://<service>-<project-number>.<region>.run.app (the one firebase.json's CSP allows)
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
API_URL="${VITE_API_URL:-https://andon-api-$PROJECT_NUMBER.$REGION.run.app}"
[[ -n "$API_URL" ]] || { echo "FAIL: cannot resolve API URL"; exit 1; }
API_URL="${API_URL%/}"
export VITE_API_URL="$API_URL"
echo "VITE_API_URL=$VITE_API_URL"
grep -q "$API_URL" firebase.json || echo "WARN: $API_URL not found in firebase.json CSP; the browser will block API calls. Update firebase.json."

npm --prefix web ci
[[ "${SKIP_TESTS:-0}" == "1" ]] || npm --prefix web test -- --run
npm --prefix web run build
[[ -f web/dist/index.html ]] || { echo "FAIL: web/dist/index.html missing"; exit 1; }

firebase deploy --only hosting --project "$FIREBASE_PROJECT"
echo "HOSTING_URLS=$SITE_URL https://$FIREBASE_PROJECT.firebaseapp.com"

# Post-deploy checks
# a fresh release can 404 for a few seconds while the CDN picks it up
for _ in 1 2 3 4 5 6; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "$SITE_URL")
  [[ "$code" == "200" ]] && break
  sleep 5
done
[[ "$code" == "200" ]] || { echo "FAIL: $SITE_URL returned $code"; exit 1; }
echo "PASS: $SITE_URL -> 200"

acao=$(curl -s -D - -o /dev/null -X OPTIONS "$API_URL/api/config" \
  -H "Origin: $SITE_URL" -H "Access-Control-Request-Method: GET" \
  | tr -d '\r' | awk -F': ' 'tolower($1)=="access-control-allow-origin"{print $2}')
[[ "$acao" == "$SITE_URL" ]] || { echo "FAIL: CORS preflight allow-origin='$acao' (want $SITE_URL); redeploy API with ALLOWED_ORIGINS"; exit 1; }
echo "PASS: CORS preflight echoes $SITE_URL"
