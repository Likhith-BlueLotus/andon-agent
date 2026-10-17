"""Short-fault detection before/after and false-positive rate (ADR-033; offline, no LLM, $0).

    uv run python -m simulator.generate --set D --out data/scenarios_dev
    uv run python -m simulator.load --scenarios data/scenarios_dev --db data/andon_dev.duckdb
    uv run python scripts/short_fault_check.py [--sweep] [--json out.json]

* **Detection** on the synthetic dev set (S101-S112, short hydraulic faults 10-20 min, 0.5-6 %):
  ``detect_change_points`` (the real tool) on every signature tag for 1 h / 4 h / 24 h windows
  ending at the stop. *Before* = a change point in the right direction with onset >= truth
  onset - 15 min; *after* = before, or a ``short_shift`` in the right direction, same onset rule,
  not marked as a data artefact.
* **False positives** on healthy windows of the S-set (data/andon.duckdb): every tag of every
  asset, (a) S-set and dev ``no_fault`` scenarios, window ending at the stop; (b) fault scenarios,
  window ending 1 h before the earliest abnormality (primary/secondary onset, noisy-tag herring);
  (c) fault scenarios at the stop, on assets with no part in any fault.
  A ``short_shift`` found there (without ``data_issue``) is a false positive. The healthy windows
  are scored through the same analytics call the tool makes (one 7-day query per asset instead of
  one per tag, for speed); the stuck-value rule is applied identically.
* ``--sweep``: z_min = 0, prints FP and detection for a grid of z thresholds (calibration).

Reads truth.json: offline evaluation script, never imported by agents/.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents import tools as T  # noqa: E402
from analytics import changepoints  # noqa: E402
from analytics.series import (  # noqa: E402
    data_quality,
    series_from_frame,
    signal_def,
    stuck_floor,
    stuck_min_s,
)
from simulator import plant  # noqa: E402
from simulator.load import DuckDBStore  # noqa: E402

WINDOWS_H = (1, 4, 24)
ONSET_TOL_S = 900
Z_GRID = (4.0, 5.0, 6.0, 7.0, 8.0, 10.0, 12.0)


def _ep(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC).timestamp())


def _iso(e: int) -> str:
    return datetime.fromtimestamp(e, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _truths(d: Path, prefix: str = "S") -> dict[str, tuple[dict, dict]]:
    out = {}
    for p in sorted(d.iterdir()):
        if p.name.startswith(prefix) and (p / "truth.json").exists():
            out[p.name] = (json.loads((p / "truth.json").read_text()),
                           json.loads((p / "sim_meta.json").read_text()))  # fmt: skip
    return out


def _short_ok(sh: dict, want: int, onset: int, stop: int, zmin: float) -> bool:
    if sh.get("status") != "found" or sh.get("data_issue"):
        return False
    if abs(sh["z"]) < zmin:
        return False
    d = 1 if sh["direction"] == "up" else -1
    return d == want and onset - ONSET_TOL_S <= _ep(sh["ts"]) <= stop


def detection(db: Path, scen: Path, zmins: tuple[float, ...]) -> list[dict]:
    store = DuckDBStore(db)
    rows = []
    for sid, (tr, meta) in _truths(scen).items():
        if tr["variant"] == "no_fault":
            continue
        stop, onset = _ep(tr["stop_ts"]), _ep(tr["onset_ts"])
        sigs = [s for s in meta["primary"]["signature"] if s["direction"] in (1, -1)]
        for h in WINDOWS_H:
            ctx = T.ToolContext(store, sid, now=lambda: datetime(2026, 10, 17, tzinfo=UTC))
            before, after = False, {z: False for z in zmins}
            detail = []
            for s in sigs:
                r = T.detect_change_points(ctx, s["asset_id"], s["tag"], _iso(stop - h * 3600),
                                           _iso(stop))  # fmt: skip
                sm = r["summary"]
                cp_hit = any((1 if c["direction"] == "up" else -1) == s["direction"]
                             and _ep(c["ts"]) >= onset - ONSET_TOL_S and not c.get("data_issue")
                             for c in sm["change_points"])  # fmt: skip
                sh = sm.get("short_shift", {})
                before |= cp_hit
                for z in zmins:
                    after[z] |= cp_hit or _short_ok(sh, s["direction"], onset, stop, z)
                detail.append({"tag": s["tag"], "dir": s["direction"], "cp_hit": cp_hit,
                               "short": {k: sh.get(k) for k in ("status", "ts", "delta",
                                                                "magnitude_pct", "z", "max_abs_z")}})  # fmt: skip
            rows.append({"sid": sid, "detail": tr["detail"], "window_h": h, "before": before,
                         "after": after, "onset_ts": tr["onset_ts"], "tags": detail})  # fmt: skip
    store.close()
    return rows


def _earliest_abnormal(tr: dict, meta: dict) -> int | None:
    ts = [tr["onset_ts"]] if tr["onset_ts"] else []
    if meta.get("secondary"):
        ts.append(meta["secondary"]["onset_ts"])
    for d in tr["distractors"]:
        if d.startswith("noisy_tag|"):
            ts.append(d.split("|")[3])
    return min(_ep(t) for t in ts) if ts else None


def offchain_windows(scen: Path) -> list[tuple[str, int, set[str]]]:
    """Fault scenarios at the stop, scored only on assets with no part in any fault (not in the
    primary/secondary chain or signature, not the herring's tag asset, not the stop station)."""
    out = []
    for sid, (tr, meta) in _truths(scen).items():
        if tr["variant"] == "no_fault":
            continue
        bad = {tr["stop_station"], *(tr["causal_chain"] or [])}
        for f in (meta.get("primary"), meta.get("secondary")):
            if f:
                bad |= {f["asset_id"], *f["chain"], *(x["asset_id"] for x in f["signature"])}
        for d in tr["distractors"]:
            if d.startswith("noisy_tag|"):
                bad.add(d.split("|")[1])
        out.append((sid, _ep(tr["stop_ts"]), {a for a in bad if a}))
    return out


def healthy_windows(scen: Path) -> list[tuple[str, int]]:
    out = []
    for sid, (tr, meta) in _truths(scen).items():
        if tr["variant"] == "no_fault":
            out.append((sid, _ep(tr["stop_ts"])))
            continue
        e = _earliest_abnormal(tr, meta)
        hist0 = _ep(tr["stop_ts"]) - 7 * 86400
        if e is not None and e - 3600 - 24 * 3600 >= hist0 + 4 * 3600:
            out.append((sid, e - 3600))
    return out


def false_positives(db: Path, wins: list[tuple], zmins: tuple[float, ...]) -> dict:
    store = DuckDBStore(db)
    n = 0
    fp = {z: 0 for z in zmins}
    flagged = 0
    hits: list[dict] = []
    for w in wins:
        sid, te = w[0], w[1]
        skip = w[2] if len(w) > 2 else set()
        for a in plant.ASSETS:
            if a.asset_id in skip:
                continue
            tags = [t.tag for t in a.tags]
            h0 = te - 7 * 86400
            df = store.query_telemetry(sid, a.asset_id, tags, datetime.fromtimestamp(h0, UTC),
                                       datetime.fromtimestamp(te, UTC))  # fmt: skip
            for tag in tags:
                hist = series_from_frame(df, tag)
                sd = signal_def(a.asset_id, tag)
                for h in WINDOWS_H:
                    t0 = te - h * 3600
                    s = hist.window(t0, te)
                    res = changepoints.detect(s, t0, te, sd, hist)
                    sh = res.get("short_shift", {})
                    n += 1
                    if sh.get("status") != "found":
                        continue
                    dq = data_quality(s, t0, te, stuck_min_s(a.asset_id, tag),
                                      stuck_floor(a.asset_id, tag))  # fmt: skip
                    s0, s1 = _ep(sh["ts"]), _ep(sh["end_ts"])
                    if any(_ep(p["start"]) < s1 and _ep(p["start"]) + p["duration_s"] > s0
                           for p in dq["stuck_periods"]):  # fmt: skip
                        flagged += 1
                        continue
                    for z in zmins:
                        fp[z] += abs(sh["z"]) >= z
                    hits.append({"sid": sid, "asset": a.asset_id, "tag": tag, "window_h": h,
                                 "ts": sh["ts"], "delta": sh["delta"], "z": sh["z"],
                                 "magnitude_pct": sh["magnitude_pct"]})  # fmt: skip
    store.close()
    return {"n_tag_windows": n, "fp": fp, "stuck_flagged": flagged, "hits": hits}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev-db", type=Path, default=ROOT / "data" / "andon_dev.duckdb")
    ap.add_argument("--dev", type=Path, default=ROOT / "data" / "scenarios_dev")
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "andon.duckdb")
    ap.add_argument("--scenarios", type=Path, default=ROOT / "data" / "scenarios")
    ap.add_argument("--sweep", action="store_true", help="z_min=0; report a grid of thresholds")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    zmins: tuple[float, ...] = (changepoints.SHORT.z_min,)
    if args.sweep:
        changepoints.SHORT = dataclasses.replace(changepoints.SHORT, z_min=0.0)
        zmins = Z_GRID
    det = detection(args.dev_db, args.dev, zmins)
    s_wins = healthy_windows(args.scenarios)
    d_wins = [(sid, _ep(tr["stop_ts"])) for sid, (tr, _) in _truths(args.dev).items()
              if tr["variant"] == "no_fault"]  # fmt: skip
    fp_s = false_positives(args.db, s_wins, zmins)
    fp_d = false_positives(args.dev_db, d_wins, zmins)
    o_wins = offchain_windows(args.scenarios)
    fp_o = false_positives(args.db, o_wins, zmins)

    print(f"dev detection ({len({r['sid'] for r in det})} short-fault scenarios)")
    for h in WINDOWS_H:
        rs = [r for r in det if r["window_h"] == h]
        b = sum(r["before"] for r in rs)
        a = {z: sum(r["after"][z] for r in rs) for z in zmins}
        print(f"  {h:>2} h window: before {b}/{len(rs)}  after " +
              "  ".join(f"z>={z:g}: {a[z]}/{len(rs)}" for z in zmins))  # fmt: skip
    for fp, name, w in (
        (fp_s, "S-set healthy", s_wins),
        (fp_d, "dev no_fault", d_wins),
        (fp_o, "S-set off-chain assets at the stop", o_wins),
    ):
        print(
            f"{name}: {len(w)} windows, {fp['n_tag_windows']} tag-windows, "
            f"stuck-flagged {fp['stuck_flagged']}"
        )
        print("  FP " + "  ".join(f"z>={z:g}: {fp['fp'][z]} ({100 * fp['fp'][z] / max(fp['n_tag_windows'], 1):.2f} %)"
                                  for z in zmins))  # fmt: skip
    if args.json:
        args.json.write_text(json.dumps({"detection": det, "fp_sset": fp_s, "fp_dev": fp_d, "fp_offchain": fp_o,
                                         "zmins": zmins}, indent=1, default=str))  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
