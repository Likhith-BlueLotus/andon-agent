#!/usr/bin/env bash
# Idempotent GCP bootstrap for Andon Agent. Creates billable (but idle-free) resources.
# Usage: PROJECT=<id> BILLING_ACCOUNT=<XXXXXX-XXXXXX-XXXXXX> bash infra/bootstrap.sh
#   CREATE_PROJECT=1  also creates the project and links billing (first run only).
set -euo pipefail
PROJECT="${PROJECT:?set PROJECT}"
REGION="${REGION:-asia-south1}"
BILLING_ACCOUNT="${BILLING_ACCOUNT:-}"

if [[ "${CREATE_PROJECT:-0}" == "1" ]]; then
  gcloud projects create "$PROJECT" --name="Andon Agent" || true
  [[ -n "$BILLING_ACCOUNT" ]] || { echo "BILLING_ACCOUNT required with CREATE_PROJECT=1"; exit 1; }
  gcloud billing projects link "$PROJECT" --billing-account="$BILLING_ACCOUNT"
fi

gcloud config set project "$PROJECT"
gcloud services enable \
  aiplatform.googleapis.com run.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com bigquery.googleapis.com firestore.googleapis.com \
  storage.googleapis.com secretmanager.googleapis.com logging.googleapis.com \
  firebase.googleapis.com firebasehosting.googleapis.com billingbudgets.googleapis.com

gcloud artifacts repositories create andon --repository-format=docker --location="$REGION" || true
gcloud iam service-accounts create andon-api --display-name="Andon API (Cloud Run)" || true
gcloud iam service-accounts create andon-eval --display-name="Andon eval (Cloud Run Job)" || true
bq --location="$REGION" mk -d "$PROJECT:andon" || true
gcloud storage buckets create "gs://$PROJECT-assets" --location="$REGION" --uniform-bucket-level-access || true
gcloud storage buckets create "gs://$PROJECT-eval" --location="$REGION" --uniform-bucket-level-access || true
gcloud firestore databases create --location="$REGION" --type=firestore-native || true

# Budget alerts at $100 / $200 / $250 of the $300 credit, on gross cost (credits excluded,
# otherwise spend nets to 0 while credits last and alerts never fire). The budget must be in the
# billing account's currency; INR uses BUDGET_INR (default assumes ~88 INR/USD).
if [[ -n "$BILLING_ACCOUNT" ]]; then
  if ! gcloud billing budgets list --billing-account="$BILLING_ACCOUNT" --format="value(displayName)" | grep -qx "andon-300"; then
    CURRENCY=$(gcloud billing accounts describe "$BILLING_ACCOUNT" --format="value(currencyCode)")
    case "$CURRENCY" in
      USD) AMOUNT="300USD" ;;
      INR) AMOUNT="${BUDGET_INR:-26500}INR" ;;
      *) echo "unsupported billing currency $CURRENCY; set the budget by hand"; exit 1 ;;
    esac
    PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format="value(projectNumber)")
    gcloud billing budgets create --billing-account="$BILLING_ACCOUNT" \
      --display-name="andon-300" --budget-amount="$AMOUNT" \
      --filter-projects="projects/$PROJECT_NUMBER" --credit-types-treatment=exclude-all-credits \
      --threshold-rule=percent=0.3333 --threshold-rule=percent=0.6667 --threshold-rule=percent=0.8333 \
      --threshold-rule=percent=1.0
  fi
else
  echo "WARN: BILLING_ACCOUNT not set; budget alerts NOT created."
fi
echo "bootstrap done. Next: PROJECT=$PROJECT bash infra/iam.sh"
