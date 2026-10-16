# Judging-window runbook (Oct 19 - Nov 6; finale Dec 4)

All commands use `CLOUDSDK_ACTIVE_CONFIG_NAME=andon` (project `andon-511816`, region `asia-south1`).

## Who checks, when (Oct 19 - Nov 6; finale Dec 4)
| Days | Daily check owner | Backup |
|---|---|---|
| Mon, Wed, Fri, Sun | Person A (Likhith M) | Person B |
| Tue, Thu, Sat | Person B | Person A |
One-line status in the team chat after each check: `judging_check: ALL PASS` or the failing line.

## Daily URL check (once a day, 2 min)
0. `bash infra/judging_check.sh` (free, replay only) — expect `ALL PASS`. Once a week, or after any deploy: `LIVE=1 bash infra/judging_check.sh` (~$0.15).
1. `bash scripts/smoke.sh https://<api-url>` (add `TOKEN=$(gcloud auth print-identity-token)` only if the service is private). Expect `PASS`, replay `done` within 120 s, events spread over time (no buffering warning).
2. Open the web URL in an incognito window: badge `SYNTHETIC LINE · REAL SIGNALS MARKED` visible, replay plays.
3. Spend: `bash infra/cost_report.sh` (when present) or Console > Billing > Reports (gross cost, group by SKU). Compare with the DEVELOPMENT.md section 7 ledger. Budget alerts fire at $100/$200/$250.
4. Optional live check (costs money): `PASSCODE=1 bash scripts/smoke.sh <url>`.

## Warm schedule
Default `min-instances 0` (cold start about 1-3 s plus first-request imports). Warm only when needed:
- `bash infra/warm.sh on` 30 min before a recording or a known judging session; `bash infra/warm.sh off` after.
- A warm instance (2 vCPU / 4 GiB, instance-based idle) costs a few USD per day; never leave on overnight without checking the ledger.
- Or `WARM=1 PUBLIC=1 bash infra/deploy_api.sh` on redeploy.

## Rotate the passcode
```
python3 -c "import secrets;print(secrets.token_urlsafe(24),end='')" | gcloud secrets versions add demo-passcode --data-file=-
gcloud run services update andon-api --region asia-south1 --update-secrets DEMO_PASSCODE=demo-passcode:latest   # new revision picks it up
gcloud secrets versions list demo-passcode        # disable the old version:
gcloud secrets versions disable <old-version> --secret demo-passcode
```
Read the value with `gcloud secrets versions access latest --secret demo-passcode` (do not paste into chat, docs or git).

## Raise or lower the daily budget kill switch
`printf 8 | gcloud secrets versions add daily-budget-usd --data-file=-` then update the service as above (secret is read at start).

## Flip REPLAY_ONLY (no live Gemini spend at all)
- On: `gcloud run services update andon-api --region asia-south1 --update-env-vars REPLAY_ONLY=1`
- Off: `... --remove-env-vars REPLAY_ONLY`
Use immediately if spend spikes or Gemini returns sustained 429s; replays keep working.

## Emergency stop
- Make private: `gcloud run services remove-iam-policy-binding andon-api --region asia-south1 --member=allUsers --role=roles/run.invoker`
- Hard stop traffic: `gcloud run services update andon-api --region asia-south1 --max-instances 0` (restore to 3 after).

## Known traps
Paths ending in `z` are reserved by Cloud Run (use `/health`). Request timeout 900 s with heartbeats. Firebase Hosting does not proxy the stream: the web app calls Cloud Run directly (CORS allow-list). Per-incident DuckDB lives in `/tmp` (memory-backed, 4 GiB).
