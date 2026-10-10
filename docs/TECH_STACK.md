# Tech stack & environment

## Versions (pin in `pyproject.toml` / `package.json` on Day 0 after checking latest)
Pinned 2026-10-10: google-adk 2.11.0, google-genai 2.29.0, fastapi 0.141.x (ADK caps <0.143), pydantic 2.14, duckdb 1.5, librosa 1.0 (major bump — check API before use).
| Thing | Choice | Why |
|---|---|---|
| Python | 3.12 | ADK + google-genai support; fast |
| Packaging | `uv` | Fast installs, lockfile, simple Docker layer |
| Agent framework | `google-adk` (latest stable) | Workflow agents (Sequential/Parallel/Loop), session state, SSE streaming |
| Model SDK | `google-genai` in Agent Platform (Vertex) mode | Context caching, structured output, audio parts from `gs://` |
| API | FastAPI + uvicorn | Async, Pydantic v2, `StreamingResponse` for SSE |
| Numeric | numpy, pandas, pyarrow, scipy (spectra), `ruptures` (change points), scikit-learn (IsolationForest), librosa (MFCC baseline), joblib | Real analytics in tools |
| Data fetch | `remotezip` (pull single wavs out of 7–11 GB MIMII zips via HTTP range requests), `requests`, hashlib | MIMII is 100.2 GB in total — never download whole zips |
| Stats | scipy.stats (binomial/McNemar), statsmodels optional (Wilson intervals are 5 lines; write them) | Small-n honesty in the eval |
| Local store | DuckDB on Parquet | Offline tests, zero cost |
| Cloud store | BigQuery (`andon` dataset), Firestore (native), Cloud Storage | Google Cloud integration, cheap at this size |
| Frontend | React 18 + Vite + TypeScript + Tailwind + Recharts | Fast to build, static deploy |
| Frontend hosting | Firebase Hosting (static SPA) | Satisfies "Firebase"; zero server |
| Tests / lint | pytest (+ pytest-asyncio), ruff; vitest for web | |

**Gotcha decided up front:** the SPA calls the Cloud Run URL directly (CORS), *not* through a Firebase Hosting rewrite — Hosting rewrites to Cloud Run have a short request timeout that would cut long SSE streams. Verified 2026-10-10: the Hosting→Cloud Run rewrite still times out at 60 s (504), so direct calls are required.

## Environment variables (`.env.example`, real values in Secret Manager / deploy flags)
```
GOOGLE_CLOUD_PROJECT=andon-agent-xxxx
GOOGLE_CLOUD_LOCATION=global           # Gemini
GOOGLE_GENAI_USE_ENTERPRISE=true       # google-genai >=2.29 preferred name (wins if both set)
GOOGLE_GENAI_USE_VERTEXAI=True         # legacy name, still honoured; keep both equal
APP_REGION=asia-south1
BQ_DATASET=andon
GCS_BUCKET=andon-agent-xxxx-assets
STORE_BACKEND=duckdb                   # duckdb | bigquery
DATA_RAW_DIR=./data/raw                # can point outside the repo
ENABLE_STRETCH=                        # comma list: csv_ingest,voice_note,translate (off by default)
JUDGE_MODEL=gemini-3.8-flash           # set to gemini-3.1-pro-preview for eval/recording
DAILY_BUDGET_USD=8
MAX_LLM_CALLS=40
ALLOWED_ORIGINS=http://localhost:5173,https://<firebase-site>.web.app
DEMO_PASSCODE=<from Secret Manager>
```

## GCP bootstrap (`infra/bootstrap.sh`, idempotent)
```bash
PROJECT=andon-agent-xxxx; REGION=asia-south1
gcloud config set project $PROJECT
gcloud services enable aiplatform.googleapis.com run.googleapis.com artifactregistry.googleapis.com \
  cloudbuild.googleapis.com bigquery.googleapis.com firestore.googleapis.com storage.googleapis.com \
  secretmanager.googleapis.com logging.googleapis.com firebase.googleapis.com firebasehosting.googleapis.com
gcloud artifacts repositories create andon --repository-format=docker --location=$REGION || true
gcloud iam service-accounts create andon-api || true
gcloud iam service-accounts create andon-eval || true
bq --location=$REGION mk -d andon || true
gcloud storage buckets create gs://$PROJECT-assets --location=$REGION --uniform-bucket-level-access || true
gcloud firestore databases create --location=$REGION || true
# then infra/iam.sh grants the roles listed in docs/SECURITY.md
# budget alerts: 100/200/250 USD via `gcloud billing budgets create` (needs billing account id)
```

## Deploy API (`infra/deploy_api.sh`)
```bash
gcloud run deploy andon-api --source . --region $REGION \
  --service-account andon-api@$PROJECT.iam.gserviceaccount.com \
  --timeout 900 --concurrency 20 --cpu 2 --memory 2Gi \
  --min-instances 0 --max-instances 3 \
  --set-env-vars GOOGLE_CLOUD_LOCATION=global,STORE_BACKEND=bigquery,... \
  --set-secrets DEMO_PASSCODE=demo-passcode:latest \
  --allow-unauthenticated
# During recording/judging: gcloud run services update andon-api --min-instances 1 ; set back to 0 after.
```

## Cloud Run / Gemini gotchas (each one has a test or a script)
| Gotcha | Fix |
|---|---|
| Default request timeout 300 s (max 3600 s) | `--timeout 900`; SSE heartbeat every 15 s |
| Proxies buffer SSE | `Cache-Control: no-cache`, `X-Accel-Buffering: no`, flush each event |
| Background work throttled after response (request-based billing) | Run eval as a Cloud Run **Job**, never as a background task |
| Cold start | Slim image, lazy-load sklearn model and librosa; `--min-instances 1` only when it matters |
| 429 RESOURCE_EXHAUSTED | `location=global`, jittered backoff, Pro→Flash fallback, ≤4 concurrent Gemini calls per instance in eval |
| Gemini 3 sampling params | Don't send temperature/top_p/top_k; use thinking level |
| Thought signatures in tool loops | Let ADK's runner carry them; if calling google-genai directly, return the full previous content |
| Context cache minimum size | Docs (2026-10-10): 6,144 tokens for 3.1 Pro preview / 3.8 Flash, 4,096 for other Gemini 3; wording for 3.8 Flash *explicit* caching is ambiguous — confirm with one live `caches.create`. Default TTL 60 min; storage billed per hour — GC at session end |
| response_schema limits | Shallow schemas, enums, no giant `anyOf`; validate with Pydantic; one retry then fail closed |
| Large media | Pass `gs://` URIs as parts, never base64 large files |
| Model retirement | Never 2.x; IDs only from `config.py`; Phase 0 live-checks them |
| Firestore in wrong mode/region | Create native mode in asia-south1 before first write |
| Huge datasets in the container | Never bake raw data into the image; real-signal scenarios are pre-built into BigQuery/GCS; image stays slim |
| Laptop disk fills during fetch | `remotezip` for MIMII, one IMS test set, check `df -h` before fetching; raw data outside the repo if needed (`DATA_RAW_DIR`) |
