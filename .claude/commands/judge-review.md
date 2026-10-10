---
description: Brutal scoring of the current state against the official AI Builder Cup rubric
argument-hint: "[focus: all | demo | deck | code | eval]"
---

Use the `hackathon-judge` subagent to score the project as it stands right now. Focus: $ARGUMENTS (default all).

Give the judge: README, docs/, latest `eval/results/*/summary.json` (if any), the agent code, `deck/` (if any), and the live URL from the README (fetch `/health`).

Return the judge's table and total /100, the top 3 weaknesses with a fix each that fits the remaining calendar (today vs. freeze Thu Oct 15 23:59 IST), and the hardest question they'd ask in the room. Then, as Engineering Manager, say which one fix you'd do next and which cut-list item (DEVELOPMENT.md §9) it would cost, if any. Don't change any files.
