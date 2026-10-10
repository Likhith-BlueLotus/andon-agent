#!/usr/bin/env bash
# Deploy the API to Cloud Run as andon-api@ (never the default compute SA).
# Usage: PROJECT=<id> bash infra/deploy_api.sh
# max-instances 1 until the spend counter moves to Firestore (it is per-process; 3 instances = 3x budget).
set -euo pipefail
PROJECT="${PROJECT:?set PROJECT}"
REGION="${REGION:-asia-south1}"
EXTRA_ENV="${EXTRA_ENV:-}"   # e.g. ",JUDGE_MODEL=gemini-3.1-pro-preview"
SECRETS_FLAG=()
if gcloud secrets describe demo-passcode --project "$PROJECT" >/dev/null 2>&1; then
  SECRETS_FLAG=(--set-secrets "DEMO_PASSCODE=demo-passcode:latest")
fi

gcloud run deploy andon-api --source . --project "$PROJECT" --region "$REGION" \
  --service-account "andon-api@$PROJECT.iam.gserviceaccount.com" \
  --timeout 900 --concurrency 20 --cpu 2 --memory 2Gi \
  --min-instances 0 --max-instances 1 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=global,GOOGLE_GENAI_USE_ENTERPRISE=true,GOOGLE_GENAI_USE_VERTEXAI=True,APP_REGION=$REGION,STORE_BACKEND=bigquery,BQ_DATASET=andon,GCS_BUCKET=$PROJECT-assets$EXTRA_ENV" \
  ${SECRETS_FLAG[@]+"${SECRETS_FLAG[@]}"} \
  --allow-unauthenticated

URL=$(gcloud run services describe andon-api --project "$PROJECT" --region "$REGION" --format='value(status.url)')
echo "API_URL=$URL"
bash scripts/smoke.sh "$URL"
