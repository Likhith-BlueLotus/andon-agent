#!/usr/bin/env bash
# Build and deploy the eval as a Cloud Run Job (andon-eval@ service account). Does NOT execute it
# unless RUN=1. Nothing here is run by the build agent; read it, then run it yourself.
#
# Usage: PROJECT=<id> bash infra/deploy_eval_job.sh
#   RUN=1                 also execute the job and wait (this spends real money!)
#   RUN_ID=<name>         results prefix gs://$PROJECT-eval/runs/<RUN_ID> (default: eval_YYYYmmdd_HHMM)
#   SYSTEMS / SETS / EXTRA  eval arguments, e.g. SYSTEMS=S1,S2,B1,B2 SETS=S,R EXTRA="--judge pro"
#   DAILY_BUDGET_USD=<n>  kill switch for the job process; MUST cover the estimate (e.g. 60 for the
#                         final S1-Pro run). Default is the same value as the API's secret would give
#                         (8), which stops the job early by design; the job is resumable.
#   UPLOAD_INPUTS=1       (re)upload truth + labels from data/ to gs://$PROJECT-eval/inputs
# The job passes --yes: the cost estimate and the DEVELOPMENT.md §7 ledger check still print first,
# and the ledger hard stop still refuses; confirm the estimate yourself with
#   uv run python -m eval.run_eval --estimate-only ...   before RUN=1.
set -euo pipefail
export CLOUDSDK_ACTIVE_CONFIG_NAME="${CLOUDSDK_ACTIVE_CONFIG_NAME:-andon}"
PROJECT="${PROJECT:-andon-511816}"
REGION="${REGION:-asia-south1}"
SA="andon-eval@$PROJECT.iam.gserviceaccount.com"
BUILD_SA="projects/$PROJECT/serviceAccounts/andon-build@$PROJECT.iam.gserviceaccount.com"
REPO="$REGION-docker.pkg.dev/$PROJECT/andon"
IMAGE="$REPO/andon-eval:$(git rev-parse --short HEAD)"
BUCKET="gs://$PROJECT-eval"
RUN_ID="${RUN_ID:-eval_$(date +%Y%m%d_%H%M)}"
SYSTEMS="${SYSTEMS:-S1,S2,B1,B2}"
SETS="${SETS:-S,R}"
EXTRA="${EXTRA:-}"
BUDGET="${DAILY_BUDGET_USD:-8}"

if [[ "${UPLOAD_INPUTS:-0}" == "1" ]]; then
  # Ground truth and eval-only labels never go into an image or the public repo.
  for d in data/scenarios/*/; do
    id=$(basename "$d")
    gcloud storage cp "$d/truth.json" "$BUCKET/inputs/scenarios/$id/truth.json" --quiet
    [[ -f "$d/audio_truth.json" ]] && gcloud storage cp "$d/audio_truth.json" "$BUCKET/inputs/scenarios/$id/audio_truth.json" --quiet
  done
  gcloud storage cp data/work_orders.parquet data/work_orders_labels.parquet "$BUCKET/inputs/" --quiet
fi

# Build with Cloud Build as andon-build@ (infra/eval.Dockerfile, repo root as context).
CFG=$(mktemp)
cat >"$CFG" <<YAML
steps:
  - name: gcr.io/cloud-builders/docker
    args: ["build", "-f", "infra/eval.Dockerfile", "-t", "$IMAGE", "."]
images: ["$IMAGE"]
serviceAccount: "$BUILD_SA"
options: {logging: CLOUD_LOGGING_ONLY}
YAML
gcloud builds submit --project "$PROJECT" --region "$REGION" --config "$CFG" .
rm -f "$CFG"

# The container: pull inputs, then run. --store gcs reads the published store (objectViewer on assets).
RUN_CMD="python -m eval.gcs_sync pull $BUCKET/inputs /data && python -m eval.run_eval \
--systems $SYSTEMS --sets $SETS --concurrency 4 --yes --store gcs \
--scenarios-dir /data/scenarios --data-dir /data --out /tmp/run --sync-to $BUCKET/runs/$RUN_ID $EXTRA"

gcloud run jobs deploy andon-eval --project "$PROJECT" --region "$REGION" \
  --image "$IMAGE" --service-account "$SA" \
  --tasks 1 --max-retries 0 --task-timeout 6h --cpu 4 --memory 8Gi \
  --set-env-vars "^;^GOOGLE_CLOUD_PROJECT=$PROJECT;GOOGLE_CLOUD_LOCATION=global;GOOGLE_GENAI_USE_ENTERPRISE=true;GOOGLE_GENAI_USE_VERTEXAI=True;STORE_BACKEND=gcs;GCS_BUCKET=$PROJECT-assets;STORE_CACHE_DIR=/tmp/andon-store;DAILY_BUDGET_USD=$BUDGET;JUDGE_MODEL=gemini-3.1-pro-preview" \
  --command sh --args=-c --args="$RUN_CMD"
echo "deployed andon-eval; results -> $BUCKET/runs/$RUN_ID (re-run with the same RUN_ID to resume)"

if [[ "${RUN:-0}" == "1" ]]; then
  gcloud run jobs execute andon-eval --project "$PROJECT" --region "$REGION" --wait
  echo "fetch: gcloud storage cp -r $BUCKET/runs/$RUN_ID eval/results/$RUN_ID"
  echo "then:  uv run python -m eval.report eval/results/$RUN_ID --truth-dir data/scenarios --publish"
else
  echo "not executed (set RUN=1 to run; it spends money)"
fi
