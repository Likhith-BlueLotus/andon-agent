"""Sanity report for the generated S-set: per-class summary stats + 3 inspection figures.

    uv run python scripts/sim_inspection.py --scenarios data/scenarios --out docs/sim_inspection

Reads truth.json (this is an offline QA script, not agent code). Figures:
  1. s_week_overview.png       - one clean scenario, a week of every asset's key tags
  2. s_class_signatures.png    - per S-set class: root signature + first downstream symptom
  3. s_imperfections.png       - gaps / stuck value / noisy red-herring tag in one scenario
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import pyarrow.parquet as pq

KEY_TAGS = {
    "ST10-PRS": "hyd_pressure_bar",
    "ST20-WLD": "tip_resistance_mohm",
    "ST30-WLD": "servo_temp_c",
    "ST40-SLR": "flow_rate_ccm",
    "ST50-CNV": "vibration_rms_mms",
    "ST60-VIS": "reject_rate_pct",
    "UT-AIR": "header_pressure_bar",
    "UT-CHL": "supply_temp_c",
}


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def load(d: Path) -> tuple[dict, dict, pd.DataFrame]:
    truth = json.loads((d / "truth.json").read_text())
    meta = json.loads((d / "sim_meta.json").read_text())
    return truth, meta, pq.read_table(d / "telemetry.parquet").to_pandas()


def series(tel: pd.DataFrame, aid: str, tag: str) -> pd.Series:
    x = tel[(tel.asset_id == aid) & (tel.tag == tag)]
    return pd.Series(x["value"].to_numpy(), index=x["ts"])


def summary(root: Path) -> None:
    rows = []
    for d in sorted(p for p in root.iterdir() if (p / "truth.json").exists()):
        t = json.loads((d / "truth.json").read_text())
        al = pq.read_table(d / "alarms.parquet").to_pandas()
        notes = pq.read_table(d / "shift_notes.parquet").num_rows
        stop = _ts(t["stop_ts"])
        flood = int(
            ((al.ts >= stop - timedelta(minutes=30)) & (al.ts <= stop + timedelta(minutes=3))).sum()
        )
        lead = (stop - _ts(t["onset_ts"])).total_seconds() / 3600 if t["onset_ts"] else None
        mb = sum(f.stat().st_size for f in d.iterdir()) / 1e6
        rows.append((t["root_cause_class"], t["variant"], lead, len(al), flood, notes, len(t["imperfections"]), mb,
                     len(t["causal_chain"]), t["scenario_id"]))  # fmt: skip
    by = defaultdict(list)
    for r in rows:
        by[r[0]].append(r)
    print(
        f"{'class':26s} {'n':>2s} {'lead_h':>12s} {'alarms':>7s} {'flood':>9s} {'notes':>5s} {'imperf':>6s} {'chain':>5s}"
    )
    for c, rs in sorted(by.items()):
        leads = [r[2] for r in rs if r[2] is not None]
        lead = f"{min(leads):.1f}-{max(leads):.1f}" if leads else "-"
        fl = [r[4] for r in rs]
        print(f"{c:26s} {len(rs):2d} {lead:>12s} {statistics.mean(r[3] for r in rs):7.0f} {min(fl):3d}-{max(fl):<3d}"
              f"   {statistics.mean(r[5] for r in rs):5.1f} {statistics.mean(r[6] for r in rs):6.1f}"
              f" {statistics.mean(r[8] for r in rs):5.1f}")  # fmt: skip
    held = sorted({r[0] for r in rows if 51 <= int(r[9][1:]) <= 60})
    print(f"\nscenarios: {len(rows)}  total MB: {sum(r[7] for r in rows):.0f}  MB/scenario: "
          f"{statistics.mean(r[7] for r in rows):.1f}  held-out classes: {len(held)} {held}")  # fmt: skip


def fig_week(root: Path, out: Path) -> str:
    for d in sorted(p for p in root.iterdir() if (p / "truth.json").exists()):
        t = json.loads((d / "truth.json").read_text())
        if t["variant"] == "clean" and t["root_cause_class"] == "conveyor_bearing_defect":
            break
    _, _, tel = load(d)
    fig, axes = plt.subplots(len(KEY_TAGS), 1, figsize=(13, 14), sharex=True)
    for ax, (aid, tag) in zip(axes, KEY_TAGS.items(), strict=True):
        s = series(tel, aid, tag).resample("60s").mean()
        ax.plot(s.index, s.values, lw=0.6)
        ax.set_ylabel(f"{aid}\n{tag}", fontsize=7)
        if t["onset_ts"]:
            ax.axvline(_ts(t["onset_ts"]), color="r", lw=0.8, ls="--")
    axes[0].set_title(
        f"{d.name}: one week at 1 Hz (1-min means). red = injected onset ({t['root_cause_class']})"
    )
    fig.tight_layout()
    p = out / "s_week_overview.png"
    fig.savefig(p, dpi=110)
    plt.close(fig)
    return str(p)


def fig_classes(root: Path, out: Path) -> str:
    picked: dict[str, Path] = {}
    for d in sorted(p for p in root.iterdir() if (p / "truth.json").exists()):
        t = json.loads((d / "truth.json").read_text())
        if t["variant"] == "clean" and t["root_cause_class"] not in picked:
            picked[t["root_cause_class"]] = d
    fig, axes = plt.subplots(len(picked), 1, figsize=(12, 2.3 * len(picked)))
    for ax, (cls, d) in zip(axes, sorted(picked.items()), strict=True):
        truth, meta, tel = load(d)
        sig = meta["primary"]["signature"]
        onset, stop = _ts(truth["onset_ts"]), _ts(truth["stop_ts"])
        t0 = onset - timedelta(hours=6)
        root_sig = sig[0]
        down = next((s for s in sig if s["downstream"]), None)
        s1 = series(tel, root_sig["asset_id"], root_sig["tag"])
        s1 = s1[s1.index >= t0].resample("60s").mean()
        ax.plot(
            s1.index, s1.values, lw=0.7, label=f"{root_sig['asset_id']}.{root_sig['tag']} (root)"
        )
        if down:
            ax2 = ax.twinx()
            s2 = series(tel, down["asset_id"], down["tag"])
            s2 = s2[s2.index >= t0].resample("60s").mean()
            ax2.plot(
                s2.index,
                s2.values,
                lw=0.7,
                color="tab:orange",
                label=f"{down['asset_id']}.{down['tag']}",
            )
            ax2.tick_params(labelsize=6)
            ax2.legend(loc="upper center", fontsize=6)
        ax.axvline(onset, color="r", ls="--", lw=0.8)
        ax.axvline(stop, color="k", lw=0.8)
        ax.set_title(f"{d.name}  {cls}", fontsize=8, loc="left")
        ax.legend(loc="upper left", fontsize=6)
        ax.tick_params(labelsize=6)
    fig.tight_layout()
    p = out / "s_class_signatures.png"
    fig.savefig(p, dpi=110)
    plt.close(fig)
    return str(p)


def fig_imperfections(root: Path, out: Path) -> str:
    for d in sorted(p for p in root.iterdir() if (p / "truth.json").exists()):
        t = json.loads((d / "truth.json").read_text())
        if t["variant"] == "red_herring":
            break
    truth, _, tel = load(d)
    imps = [i.split("|") for i in truth["imperfections"]]
    stuck = next(i for i in imps if i[0] == "stuck")
    noisy = next(x.split("|") for x in truth["distractors"] if x.startswith("noisy_tag"))
    gap = next(i for i in imps if i[0] == "gap")
    fig, axes = plt.subplots(3, 1, figsize=(12, 8))
    for ax, (aid, tag, a, b, label) in zip(axes, [
        (stuck[1], stuck[2], _ts(stuck[3]), _ts(stuck[4]), "stuck value (imperfection)"),
        (noisy[1], noisy[2], _ts(noisy[3]), _ts(noisy[4]), "noisy unrelated tag (red herring)"),
        (gap[1], plant_first_tag(tel, gap[1]), _ts(gap[3]), _ts(gap[4]), "comms gap (imperfection)"),
    ], strict=True):  # fmt: skip
        s = series(tel, aid, tag)
        pad = max((b - a) * 2, timedelta(minutes=10))
        s = s[(s.index >= a - pad) & (s.index <= b + pad)]
        ax.plot(s.index, s.values, ".", ms=1.5)
        ax.axvspan(a, b, color="orange", alpha=0.25)
        ax.set_title(f"{d.name} {aid}.{tag}: {label}", fontsize=8, loc="left")
        ax.tick_params(labelsize=6)
    fig.tight_layout()
    p = out / "s_imperfections.png"
    fig.savefig(p, dpi=110)
    plt.close(fig)
    return str(p)


def plant_first_tag(tel: pd.DataFrame, aid: str) -> str:
    return str(sorted(tel[tel.asset_id == aid].tag.unique())[0])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", type=Path, default=Path("data/scenarios"))
    ap.add_argument("--out", type=Path, default=Path("docs/sim_inspection"))
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    summary(a.scenarios)
    for f in (fig_week, fig_classes, fig_imperfections):
        print("wrote", f(a.scenarios, a.out))


if __name__ == "__main__":
    main()
