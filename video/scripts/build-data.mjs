// Reads the real numbers at build time. Nothing on screen that is a measurement is typed by hand.
//   eval/results/latest.json            -> top-1 + Wilson intervals, set sizes, run id
//   eval/results/<run_id>/summary.json  -> claim counts (unsupported / total) for the grounding stat
//   data/replays/s014-cloud-1.jsonl     -> the rejected claim, asserted vs measured, iteration counter
//   web/src/lib/config.ts               -> assumed downtime rate, theme string, badge text
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const rd = (p) => readFileSync(join(root, p), "utf8");
const die = (m) => { console.error("build-data: " + m); process.exit(1); };

// ---- results
const latest = JSON.parse(rd("eval/results/latest.json"));
const summary = JSON.parse(rd(`eval/results/${latest.run_id}/summary.json`));
const pick = (set, key) => {
  const r = latest.sets[set].find((x) => x.system.startsWith(key + " "));
  if (!r) die(`no ${key} in ${set}`);
  return { n: r.n, top1: r.top1.value, lo: r.top1.lo, hi: r.top1.hi, system: r.system, cost: r.cost_per_run_usd };
};
const results = { runId: latest.run_id, S: {}, R: {} };
for (const set of ["S", "R"]) for (const k of ["S1", "S2", "B1", "B2"]) results[set][k] = pick(set, k);
const pooled = (sys) => {
  let un = 0, tot = 0;
  for (const set of ["S", "R"]) {
    const c = summary.sets[set][sys]?.claims;
    if (!c) die(`no claims for ${sys}/${set}`);
    un += c.n_unsupported; tot += c.n_claims;
  }
  return { unsupported: un, total: tot };
};
results.claims = { S1: pooled("S1"), B1: pooled("B1") };
const mc = (set, a, b) => summary.tests[set].find((t) => t.a === a && t.b === b);
results.sig = {
  S_S1_vs_B1: mc("S", "S1", "B1").significant_at_0_05 ?? mc("S", "S1", "B1")["significant_at_0.05"],
  R_S1_vs_B1: mc("R", "S1", "B1")["significant_at_0.05"],
  S_p: mc("S", "S1", "B1").p, R_p: mc("R", "S1", "B1").p,
};

// ---- verifier example (s014)
const ev = rd("data/replays/s014-cloud-1.jsonl").trim().split("\n").map((l) => JSON.parse(l));
const hyp = ev.filter((e) => e.type === "hypotheses");
const vv = ev.filter((e) => e.type === "verifier_verdict");
if (hyp.length < 2 || vv.length < 2) die("s014 replay does not contain a FAIL then PASS loop");
if (vv[0].data.overall !== "FAIL" || vv[1].data.overall !== "PASS") die("s014 verdict order changed");
const bad = vv[0].data.claims.find((c) => c.verdict === "fail");
const claimText = (h, id) => h.data.hypotheses.flatMap((x) => x.claims).find((c) => c.claim_id === id);
const c1 = claimText(hyp[0], bad.claim_id);
const c2 = claimText(hyp[1], bad.claim_id);
const ok2 = vv[1].data.claims.find((c) => c.claim_id === bad.claim_id);
const ts = [...bad.reason.matchAll(/(\d{4}-\d\d-\d\dT[\d:]+Z)/g)].map((m) => m[1]);
const evs = [...bad.reason.matchAll(/\[(ev_[a-z_0-9]+) \(([a-z_]+)\)\]/g)].map((m) => ({ ev: m[1], tag: m[2] }));
const started = ev[0].data;
const maxIter = 3; // web/src/lib/config.ts MAX_VERIFIER_ITERATIONS, asserted below
if (!/MAX_VERIFIER_ITERATIONS = 3/.test(rd("web/src/lib/config.ts"))) die("max iterations changed");
const verifier = {
  scenario: started.scenario_id, stopped: started.stopped_station, maxIter,
  iter1: vv[0].data.iteration, iter2: vv[1].data.iteration,
  rejected: { id: bad.claim_id, kind: c1.kind, text: c1.text, evidence: c1.evidence_ids, reason: bad.reason, measured: bad.measured_value,
    tsMeasured: ts[0], tsRoot: ts[1], evMeasured: evs[0], evRoot: evs[1] },
  revised: { text: c2.text, kind: c2.kind, assertedTs: c2.asserted_ts, measured: ok2.measured_value, reason: ok2.reason },
  nClaims2: vv[1].data.claims.length,
  nPass2: vv[1].data.claims.filter((c) => c.verdict === "pass").length,
};

// ---- constants from the web app
const cfg = rd("web/src/lib/config.ts");
const perHour = Number((cfg.match(/ASSUMED_DOWNTIME_USD_PER_HOUR = ([\d_]+)/) ?? die("no rate"))[1].replace(/_/g, ""));
const theme = (cfg.match(/THEME_STRING = "([^"]+)"/) ?? die("no theme"))[1];
const badge = (cfg.match(/BADGE_TEXT = "([^"]+)"/) ?? die("no badge"))[1];

writeFileSync(join(root, "video/src/data.generated.json"), JSON.stringify({ perHour, theme, badge, results, verifier }, null, 2) + "\n");
console.log("build-data ok:", results.runId, JSON.stringify(results.claims), "verifier", verifier.rejected.id, verifier.rejected.measured);
