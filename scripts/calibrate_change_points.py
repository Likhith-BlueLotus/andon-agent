"""Calibrate the change-point detector on synthetic normal data (offline, no LLM, $0).

    uv run python scripts/calibrate_change_points.py [--db data/andon.duckdb]

Clean windows = every tag of every S-set ``no_fault`` scenario (the only abnormal thing there is
a 1-3 s glitch at the stop, which a robust per-bin aggregate ignores), for 6 h, 24 h and 7 d
windows ending 5 min before the stop. Target (SYNTHETIC_DATA_SPEC / tools contract): clean
windows return <= 1 change point. Also reports onset error on every S/R scenario whose root
asset has a duty-cycle or level signature, so penalty changes can be judged on both sides.

Reads truth.json: this is an offline calibration script, never imported by agents/.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analytics.changepoints import detect  # noqa: E402
from analytics.series import series_from_frame, signal_def  # noqa: E402
from simulator import plant  # noqa: E402
from simulator.load import DuckDBStore  # noqa: E402

WINDOWS_H = (6, 24, 168)


def _epoch(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC).timestamp())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=ROOT / "data" / "andon.duckdb")
    ap.add_argument("--scenarios", type=Path, default=ROOT / "data" / "scenarios")
    args = ap.parse_args(argv)
    store = DuckDBStore(args.db)
    truths = {
        d.name: json.loads((d / "truth.json").read_text())
        for d in sorted(args.scenarios.iterdir())
        if (d / "truth.json").exists()
    }
    clean = [s for s, t in truths.items() if s.startswith("S") and t["variant"] == "no_fault"]
    print(f"clean scenarios: {len(clean)}")
    worst: Counter[str] = Counter()
    counts: dict[int, list[tuple[int, int]]] = {h: [] for h in WINDOWS_H}
    for sid in clean:
        t1 = _epoch(truths[sid]["stop_ts"]) - 300
        h0 = t1 - 7 * 86400
        for a in plant.ASSETS:
            tags = [t.tag for t in a.tags]
            df = store.query_telemetry(
                sid, a.asset_id, tags, datetime.fromtimestamp(h0, UTC),
                datetime.fromtimestamp(t1, UTC),
            )  # fmt: skip
            for tag in tags:
                hist = series_from_frame(df, tag)
                for hours in WINDOWS_H:
                    t0 = t1 - hours * 3600
                    r = detect(hist.window(t0, t1), t0, t1, signal_def(a.asset_id, tag), hist)
                    cps = r["change_points"]
                    k_co = sum(c["at_changeover"] for c in cps)
                    counts[hours].append((len(cps) - k_co, k_co))
                    if len(cps) - k_co > 1:
                        worst[f"{hours}h {a.asset_id}.{tag}"] += 1
    for hours, cs in counts.items():
        n = len(cs)
        ok = sum(c <= 1 for c, _ in cs)
        print(
            f"{hours:>4} h windows: {n} tag-windows, <=1 cp (not at changeover): {ok / n:.1%}, "
            f"mean cps {sum(c for c, _ in cs) / n:.2f} (+{sum(k for _, k in cs) / n:.2f} at "
            f"changeovers), max {max(c for c, _ in cs)}"
        )
    for k, v in worst.most_common(15):
        print(f"   >1 cp: {k} x{v}")
    _onset_accuracy(store, truths)
    return 0


def _onset_accuracy(store: DuckDBStore, truths: dict[str, dict]) -> None:
    """Closest change point on any root-asset tag vs the truth onset,
    7-day window ending at the stop. Negative = detected before the labelled onset."""
    by_class: dict[str, list[float]] = {}
    for sid, tr in truths.items():
        if tr["root_cause_class"] == "no_fault" or not tr.get("onset_ts") or not tr["asset_id"]:
            continue
        aid = tr["asset_id"]
        t1 = _epoch(tr["stop_ts"])
        t0 = t1 - 7 * 86400
        tags = [t.tag for t in plant.asset(aid).tags]
        df = store.query_telemetry(
            sid, aid, tags, datetime.fromtimestamp(t0, UTC), datetime.fromtimestamp(t1, UTC)
        )
        onset = _epoch(tr["onset_ts"])
        best = None
        for tag in tags:
            h = series_from_frame(df, tag)
            r = detect(h, t0, t1, signal_def(aid, tag), h)
            for c in r["change_points"]:
                err = (_epoch(c["ts"]) - onset) / 60
                if err > -24 * 60 and (best is None or abs(err) < abs(best[0])):
                    best = (err, tag)
        key = f"{sid[0]}:{tr['root_cause_class']}"
        by_class.setdefault(key, []).append(best[0] if best else float("nan"))
        if sid in ("R001", "R002", "R003", "R004") or (sid.startswith("S") and best is None):
            print(f"   {sid} {tr['root_cause_class']}: {best}")
    print("onset error of the closest root-asset change point (minutes, median / max |err|):")
    for k, v in sorted(by_class.items()):
        a = [x for x in v if x == x]
        miss = len(v) - len(a)
        med = sorted(a)[len(a) // 2] if a else float("nan")
        mx = max((abs(x) for x in a), default=float("nan"))
        print(f"   {k:<32} n={len(v)} median {med:+.0f}  max|err| {mx:.0f}  missed {miss}")


if __name__ == "__main__":
    raise SystemExit(main())
