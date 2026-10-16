#!/usr/bin/env bash
# Deploy the API to Cloud Run as andon-api@ (never the default compute SA).
# Usage: PROJECT=<id> bash infra/deploy_api.sh
# Flags: WARM=1  min-instances 1 (recording / judging window); default 0
#        PUBLIC=1  allow unauthenticated (default 0: private until the security review passes)
#        DEV=1  also allow http://localhost:5173 in CORS
#        SKIP_SMOKE=1  skip the post-deploy smoke test
# Cloud Run flags checked: https://cloud.google.com/sdk/gcloud/reference/run/deploy
set -euo pipefail
export CLOUDSDK_ACTIVE_CONFIG_NAME="${CLOUDSDK_ACTIVE_CONFIG_NAME:-andon}"
PROJECT="${PROJECT:-andon-511816}"
REGION="${REGION:-asia-south1}"
EXTRA_ENV="${EXTRA_ENV:-}"   # e.g. ";REPLAY_ONLY=1" (leading ';' because of the ^;^ delimiter)
# Stretch CSV upload (ADR-028) stays OFF unless asked: EXTRA_ENV=";ENABLE_STRETCH=upload". Uploads and their
# U<id> scenarios live in ONE instance's memory/tmp, so a second instance would answer 404 unknown_upload:
# max instances is forced to 1 when 'upload' appears in EXTRA_ENV / ENABLE_STRETCH.
MAXI="${MAXI:-3}"
# upload keeps files/ids per process; upload and tech rate limits are in memory (ADR-028/029)
if [[ "$EXTRA_ENV ${ENABLE_STRETCH:-}" == *upload* || "$EXTRA_ENV ${ENABLE_STRETCH:-}" == *tech* ]]; then MAXI=1; fi
echo "max instances: $MAXI"
FIREBASE_PROJECT="${FIREBASE_PROJECT:-andon-agent-b9c77}"  # hosting lives in its own Firebase project (ADR-024)
ORIGINS="${ALLOWED_ORIGINS:-https://$FIREBASE_PROJECT.web.app,https://$FIREBASE_PROJECT.firebaseapp.com}"
[[ "${DEV:-0}" == "1" ]] && ORIGINS="$ORIGINS,http://localhost:5173"
MIN=0; [[ "${WARM:-0}" == "1" ]] && MIN=1
AUTH=(--no-allow-unauthenticated); [[ "${PUBLIC:-0}" == "1" ]] && AUTH=(--allow-unauthenticated)

# Secrets: the passcode and the daily budget come from Secret Manager, never from env literals in git.
gcloud secrets describe demo-passcode --project "$PROJECT" >/dev/null || { echo "missing secret demo-passcode"; exit 1; }
gcloud secrets describe daily-budget-usd --project "$PROJECT" >/dev/null || { echo "missing secret daily-budget-usd"; exit 1; }

# `,` inside values needs the ^;^ delimiter; EXTRA_ENV commas are rewritten to ';'-safe form by the caller.
ENVV="GOOGLE_CLOUD_PROJECT=$PROJECT;GOOGLE_CLOUD_LOCATION=global;GOOGLE_GENAI_USE_ENTERPRISE=true;GOOGLE_GENAI_USE_VERTEXAI=True"
ENVV="$ENVV;APP_REGION=$REGION;STORE_BACKEND=gcs;STORE_CACHE_DIR=/tmp/andon-store;FIRESTORE=1;BQ_DATASET=andon"
ENVV="$ENVV;GCS_BUCKET=$PROJECT-assets;ALLOWED_ORIGINS=$ORIGINS$EXTRA_ENV"

gcloud run deploy andon-api --source . --project "$PROJECT" --region "$REGION" \
  --service-account "andon-api@$PROJECT.iam.gserviceaccount.com" \
  --build-service-account "projects/$PROJECT/serviceAccounts/andon-build@$PROJECT.iam.gserviceaccount.com" \
  --execution-environment gen2 \
  --timeout 900 --concurrency 10 --cpu 2 --memory 4Gi --cpu-boost \
  --min-instances "$MIN" --max-instances "$MAXI" \
  --startup-probe "httpGet.path=/health,httpGet.port=8080,initialDelaySeconds=0,timeoutSeconds=3,periodSeconds=3,failureThreshold=20" \
  --set-env-vars "^;^$ENVV" \
  --set-secrets "DEMO_PASSCODE=demo-passcode:latest,DAILY_BUDGET_USD=daily-budget-usd:latest" \
  "${AUTH[@]}"

URL=$(gcloud run services describe andon-api --project "$PROJECT" --region "$REGION" --format='value(status.url)')
echo "API_URL=$URL (public=${PUBLIC:-0} min=$MIN)"
if [[ "${SKIP_SMOKE:-0}" != "1" ]]; then
  if [[ "${PUBLIC:-0}" == "1" ]]; then bash scripts/smoke.sh "$URL"
  else echo "private service: run  TOKEN=\$(gcloud auth print-identity-token) bash scripts/smoke.sh $URL"; fi
fi
