// Renders every composition to video/out/*.mp4, or (--stills) one review PNG each into docs/screenshots/video-*.png.
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = join(dirname(fileURLToPath(import.meta.url)), "..");
const shots = join(here, "..", "docs", "screenshots");
const stills = process.argv.includes("--stills");
const only = process.argv.filter((a) => a.startsWith("--only=")).map((a) => a.slice(7))[0];

// id, still frame (a moment where the composition tells its story)
const COMPS = [
  ["01-title", 200],
  ["02-hook", 330],
  ["02-hook-vertical", 330],
  ["03-verifier", 270],
  ["04-architecture", 580],
  ["05-results", 520],
  ["05-results-vertical", 520],
  ["06-end-card", 100],
];

const bin = join(here, "node_modules", ".bin", "remotion");
let failed = false;
for (const [id, frame] of COMPS) {
  if (only && !id.startsWith(only)) continue;
  const args = stills
    ? ["still", "src/index.ts", id, join(shots, `video-${id}.png`), `--frame=${frame}`]
    : ["render", "src/index.ts", id, join(here, "out", `${id}.mp4`)];
  console.log(`\n> remotion ${args.slice(0, 3).join(" ")}`);
  const r = spawnSync(bin, args, { cwd: here, stdio: "inherit" });
  if (r.status !== 0) { failed = true; console.error(`FAILED: ${id}`); }
}
process.exit(failed ? 1 : 0);
