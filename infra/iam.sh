#!/usr/bin/env bash
# Least-privilege roles per docs/SECURITY.md. Idempotent.
# Usage: PROJECT=<id> bash infra/iam.sh
set -euo pipefail
PROJECT="${PROJECT:?set PROJECT}"
API_SA="andon-api@$PROJECT.iam.gserviceaccount.com"
EVAL_SA="andon-eval@$PROJECT.iam.gserviceaccount.com"

for SA in "$API_SA" "$EVAL_SA"; do
  for ROLE in roles/aiplatform.user roles/bigquery.jobUser roles/datastore.user roles/logging.logWriter; do
    gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" \
      --role="$ROLE" --condition=None --quiet >/dev/null
  done
  # Dataset-scoped read on `andon` only.
  bq query --project_id="$PROJECT" --use_legacy_sql=false \
    "GRANT \`roles/bigquery.dataViewer\` ON SCHEMA \`$PROJECT.andon\` TO \"serviceAccount:$SA\""
  # Bucket-scoped read on assets (audio, manuals, vibration snapshots).
  gcloud storage buckets add-iam-policy-binding "gs://$PROJECT-assets" \
    --member="serviceAccount:$SA" --role=roles/storage.objectViewer >/dev/null
  # Named secrets only (created in Phase 3).
  for SECRET in demo-passcode daily-budget-usd; do
    if gcloud secrets describe "$SECRET" >/dev/null 2>&1; then
      gcloud secrets add-iam-policy-binding "$SECRET" --member="serviceAccount:$SA" \
        --role=roles/secretmanager.secretAccessor >/dev/null
    fi
  done
done

# Eval job may write results to the eval bucket only.
gcloud storage buckets add-iam-policy-binding "gs://$PROJECT-eval" \
  --member="serviceAccount:$EVAL_SA" --role=roles/storage.objectAdmin >/dev/null
echo "iam done"
