---
description: Phase 7 — video script, deck, Q&A, README, submission (done by Sat Oct 17 18:00 IST)
argument-hint: "[script | deck | qa | readme | form | final-check]"
---

# Phase 7 — Ship

Focus: $ARGUMENTS (default: next unfinished).

Delegate content to `pitch-lead`; final scoring to `hackathon-judge`. docs/DEMO_AND_SUBMISSION.md is the spec.

1. **Video script** `deck/video_script.md`: timed to ≤2:50 on the R002 real-signal air-leak scenario (ADR-014), with measured numbers from the latest eval run (with intervals), the exact moments of the verifier rejection and the human approval, and a shot list. Read-aloud timing (≈150 words/minute). Open the Siemens source and confirm the figure before it goes in. Data wording exactly as DEMO_AND_SUBMISSION says.
2. **Recording plan**: `infra/warm.sh on`, warm-up run, three takes, replay fallback with banner, backup take on the S-set sealer scenario. I record; you give me the checklist.
3. **Deck** `deck/outline.md`: 12 slides with content, visuals and speaker notes; export the architecture diagram, capability matrix and results slide PNG; help me build it (Google Slides or HTML → PDF); check every link in the PDF.
4. **Q&A**: refresh the judge Q&A table against what was actually built (remove any answer that depends on an unbuilt stretch item), then run a 10-minute mock Q&A with me: you ask as `hackathon-judge`, I answer, you critique.
5. **README** final: order from the spec, S-set and R-set result tables with intervals, reproduction steps, data statement + dataset table linking `data/SOURCES.md`, fresh-build statement, live URL, video and deck links.
6. **Submission form text** `deck/submission_form.md`: every field ready to paste, theme exactly `Manufacturing: Intelligent Operations & Industrial Efficiency`, passcode for live mode in the notes.
7. **Final check**: run the submission checklist item by item and show the evidence for each; `/data-audit` clean; `hackathon-judge` final score with the top 3 risks.
8. After I confirm submission: tag `v1.0-submitted`; write `docs/JUDGING_RUNBOOK.md` (daily `infra/judging_check.sh` owner per day Oct 19–Nov 6, warm/cold schedule, budget remaining by ledger line, what to do if the URL fails, finalist prep list for Nov 7 → Dec 4).
