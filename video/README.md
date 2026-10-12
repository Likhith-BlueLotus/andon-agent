# Andon Agent demo video: code-rendered motion graphics

Six clips (plus two vertical variants) rendered with [Remotion](https://www.remotion.dev/) as H.264 MP4, 1920x1080 at 30 fps. Style is copied from the app (`web/src/index.css` dark tokens, Inter + IBM Plex Mono via `@fontsource`, indigo accent for agent activity only, red/amber/green only for status, always with icon and word). Exact on-screen text and numbers come from `video/SEGMENTS.md`.

## Render

```bash
npm --prefix video ci
npm --prefix video run render          # all clips -> video/out/*.mp4 (about 1 minute)
npm --prefix video run still           # one review PNG per clip -> docs/screenshots/video-*.png
npm --prefix video run studio          # live preview in the browser
node video/scripts/render.mjs --only=03   # one clip (prefix match on the composition id)
```

Nothing is installed globally and no system ffmpeg is needed: Remotion ships its own compositor (`@remotion/compositor-darwin-arm64` etc., chosen by `npm ci`), and downloads a headless Chrome into `video/node_modules/.remotion` on the first render (needs network once). `npx remotion ffprobe <file>` inspects an output.

## Clips

| File | Length | What |
|---|---|---|
| `01-title.mp4` | 8 s | Andon Agent, theme string (exact), tagline |
| `02-hook.mp4` / `02-hook-vertical.mp4` (1080x1920) | 12 s | Stylised line ST10-ST60 + UT-AIR / UT-CHL rails; ST20 alarms; $2.3M/h with source; arrow runs upstream to UT-AIR |
| `03-verifier.mp4` | 12 s | Real s014 claim rejected by code (measured -390,495 s), Judge revises, iteration 2 of 3 PASS |
| `04-architecture.mp4` | 20 s | Agent graph, tools, models, verifier loop, human approval, mock CMMS, Google Cloud services, no physical writes |
| `05-results.mp4` / `05-results-vertical.mp4` | 20 s | S-set and R-set top-1 with Wilson intervals; unsupported claims 1 of 586 vs 54 of 645; honesty + cost chips |
| `06-end-card.mp4` | 5 s | URL, repo, theme string, badge |

## Where every number comes from (nothing is typed from memory)

`npm run data` (runs automatically before render/still/studio) executes `scripts/build-data.mjs`, which writes `src/data.generated.json` from:

- `eval/results/latest.json` (run id, n, top-1 value and Wilson lo/hi, cost per run) and `eval/results/<run_id>/summary.json` (pooled claim counts S+R: S1 1/586, B1 54/645; McNemar p-values).
- `data/replays/s014-cloud-1.jsonl` (the rejected claim text, measured value, timestamps, evidence ids, iteration counter, the revised claim). The script fails loudly if the replay no longer contains a FAIL followed by a PASS.
- `web/src/lib/config.ts` (assumed downtime rate, theme string, badge text, max iterations).

`Results.tsx` throws at render time if S1 vs B1 ever becomes statistically significant, so the "not significant" chip cannot go stale silently.

Not from files (labelled on screen or documented here): the $2.3M/h figure is a Siemens 2024 estimate (shown as "est. · assumption" with source, as in the app); the hook line is marked ILLUSTRATIVE, it is not a recorded incident.

## Licence note (checked 2026-10-12)

Remotion is source-available under its own licence (`node_modules/remotion/LICENSE.md`; https://github.com/remotion-dev/remotion/blob/main/LICENSE.md). Free use covers individuals, for-profit companies with up to 3 employees, non-profits, and evaluation; any other company needs a paid Company License. Rendering a hackathon demo as an individual/small team fits the free tier; if any team member is rendering on behalf of a larger company, get the company licence or re-render elsewhere. We do not copy or modify Remotion code. Pinned: `remotion` and `@remotion/cli` 4.0.535, `react` and `react-dom` 19.3.0, `@fontsource/inter` and `@fontsource/ibm-plex-mono` 5.3.0 (SIL OFL 1.1), `typescript` 5.9.3.

## Layout

```
video/src/index.ts, Root.tsx     composition registry
video/src/comps/*.tsx            one file per clip (Hook and Results take a `vertical` prop)
video/src/lib/                   theme tokens, easing helpers, shared UI bits, font loader
video/scripts/build-data.mjs     reads eval + replay files
video/scripts/render.mjs         render / still driver
```
