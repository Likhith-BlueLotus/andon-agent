# START HERE — Andon Agent build kit for Claude Code (v2)

This kit turns Claude Code into a small engineering org that builds **Andon Agent** (AI Builder Cup 2026, Manufacturing theme) from an empty folder to a submitted entry by **Sat Oct 17, 18:00 IST**.

**What changed in v2:** hybrid data (real public signals mapped into the synthetic line, with provenance and a licence register), a real-signal eval set graded by the datasets' own labels, small-n statistics, a risk register, a $300 budget ledger, a gated stretch ladder, a Gemini capability matrix, judge Q&A prep, a new `/data-audit` command, and Person A now owns the eval harness to balance the week.

## What's in the box

| Path | What it is | Who reads it |
|---|---|---|
| `CLAUDE.md` | Constitution: mission, hard rules, pinned models, commands, "which doc answers what", definition of done. Auto-loaded every session. | Every session |
| `DEVELOPMENT.md` | Roles, contracts-first, phases, day plan, testing, **budget ledger (§7)**, freeze, cut list, **stretch ladder (§9b)**. | Every session |
| `docs/ARCHITECTURE.md` | Layers, Mermaid diagram, contracts (incl. provenance), SSE events, **capability matrix**, stretch endpoints, observability. | Principal, Staff, all |
| `docs/AGENTS_SPEC.md` | Every ADK agent: model, job, tools, stop conditions, verifier rules, baselines, stretch agents. | Staff, backend |
| `docs/DATA_SOURCES.md` | **Licence register**: which public datasets we may use, how, attribution; what's forbidden and why. | Data, Security, Pitch |
| `docs/SYNTHETIC_DATA_SPEC.md` | Hybrid plant: stations ↔ real sources, imperfections, 11 fault classes, **S-set (60) + R-set (17)**, text, 5 manuals, provenance. | Data engineer |
| `docs/EVAL_PLAN.md` | Systems S1/S2/S3/B1/B2, metrics, **Wilson CIs, McNemar, variance, calibration**, eval budget, the slide. | QA/Eval |
| `docs/UX_SPEC.md` | Incident console, provenance chips, states, accessibility, stretch views. | UX/UI |
| `docs/SECURITY.md` | IAM, secrets, no physical writes, injection, data licences, stretch surfaces, checklist. | Security, SRE |
| `docs/TECH_STACK.md` | Versions, env vars, GCP bootstrap/deploy, gotchas. | SRE, all |
| `docs/DEMO_AND_SUBMISSION.md` | Demo scenario, 2:50 script, 12-slide deck, **judge Q&A**, README order, checklist. | Pitch lead |
| `docs/RISKS.md` | 21 risks across eligibility, licence, data, technical, cost, schedule, demo, judging — with triggers. | All, daily |
| `docs/DECISIONS.md` | 14 ADRs. | All |
| `docs/LESSONS_LEARNED.md` | Running log. | All |
| `.claude/agents/*.md` | 10 role subagents. | Claude Code |
| `.claude/commands/*.md` | `/phase-0` … `/phase-7`, `/judge-review`, `/status`, `/freeze-check`, `/handoff`, `/data-audit`. | You |
| `.claude/settings.json` | Permissions: routine allowed, deploys/pushes ask, secrets and destructive ops denied. | Claude Code |

## Setup (tonight)

1. **Register the team on aibuildercup.com before Oct 11 closes.** Screenshot it.
2. Email support+aibuildercup@hack2skill.com to confirm apprentice status counts as "working professional" (RISKS #2).
3. `mkdir andon-agent && cd andon-agent && git init`, copy this kit in (keep the dot-folders), create the **public** GitHub repo and push.
4. `gcloud auth login && gcloud auth application-default login`.
5. Check free disk space (≥30 GB is comfortable for the dataset fetch).
6. Open Claude Code in the repo root and paste the kickoff prompt below.

## The kickoff prompt (paste once, at the start of each person's first session)

```text
You are the engineering lead for "Andon Agent", our entry to the Google Cloud AI Builder Cup 2026
under the theme "Manufacturing: Intelligent Operations & Industrial Efficiency".

Read, in this order, before doing anything else: CLAUDE.md, DEVELOPMENT.md, docs/ARCHITECTURE.md,
docs/AGENTS_SPEC.md, docs/DATA_SOURCES.md, docs/RISKS.md, docs/DECISIONS.md. Then list the role
subagents in .claude/agents and the slash commands in .claude/commands and confirm how they map to
the phases and to my row of the day plan.

Context you must hold for the whole project:
- Team: 2 humans, both full-stack. Person A = agents, backend, infra, eval harness.
  Person B = data (S-set + R-set), frontend, deck/video. Each runs their own Claude Code session, both
  committing to `main` (trunk-based, ADR-016). You are working for: <A or B>.
- Deadline: submit by Sat Oct 17 18:00 IST. Feature freeze Thu Oct 15 23:59 IST. Today is <date>.
- Budget: US$300 GCP credits total until the Dec 4 finale; follow the ledger in DEVELOPMENT.md §7.
- Everything is fresh code written now. Data only from the USE list in docs/DATA_SOURCES.md, with
  provenance. No employer, startup, or past-research code, data, names, or terminology. The reference
  repo (github.com/ayoisio/ep2-agent-bake-off-finserv-agents) is a STRUCTURAL reference only — never copy code.

How I want you to work:
1. Before any task: state the plan in <=10 bullets, the subagent(s) you'll delegate to, the files
   that change, and the cost if it calls Gemini. Proceed without waiting unless it touches a contract
   file (agents/schemas.py, api/events.py, simulator/truth_schema.py), spends > $5, or deploys.
2. Verify fast-moving facts before coding against them (ADK + google-genai APIs on adk.dev and the
   Agent Platform model pages, pinned model IDs, dataset licence pages). Fix outdated docs and log an ADR.
3. Judge every piece of work on all dimensions: works live, honest (provenance, labelled assumptions),
   safe, cheap, legible to a judge, survives the judging window unattended.
4. Tests and a working demo path beat features. Never mark a task done without running it.
5. After each phase: update docs/LESSONS_LEARNED.md and docs/RISKS.md if needed, run /status,
   commit, push. End each session with /handoff.

Start now with my first item in the DEVELOPMENT.md §5 day plan.
```

## Daily driver

| When | Person A | Person B |
|---|---|---|
| Sat Oct 10 night | Register team · `/phase-0` | `/phase-1 contracts` (with A) · `/phase-1 fetch` (downloads run overnight) |
| Sun Oct 11 | `/phase-2` tools + Commander + Signal Analyst | data inspection · `/phase-1 v1` |
| Mon Oct 12 | `/phase-2` verifier, Librarian + cache, Judge loop | `/phase-1 v2` (text, manuals, audio) |
| Tue Oct 13 | `/phase-2` finish · `/phase-3` stream + **first deploy** | `/phase-1 rset` · `/phase-4` on fixture stream |
| Wed Oct 14 | `/phase-3` HITL/replay/protection · `/phase-5 harness`, `run20` | `/phase-4` live + deploy web |
| Thu Oct 15 | `/phase-5 final` · `/freeze-check` 23:59 | a11y, mobile, stretch if gate open, screenshots, manual baseline |
| Fri Oct 16 | `/phase-6` | `/phase-7 script`, record, deck |
| Sat Oct 17 | README, Q&A rehearsal, submit | deck PDF, video upload, submit by 18:00 |

Any time: `/status`, `/judge-review`, `/data-audit`, `/handoff`.

## Four rules that save the week
1. **Contracts first**, then parallel work against a fixture stream.
2. **Deploy on Day 3, not Day 6.**
3. **Never cut** the Verifier, the eval vs B1, the MetroPT-3 R-set, provenance, or the human-approval gate.
4. **Honesty is a feature.** Mapped real signals are called mapped; assumptions are labelled; replay is labelled. Judges reward it, and it costs nothing.
