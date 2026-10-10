"""Inspect the fetched raw datasets: stats (JSON to stdout) + one PNG per dataset.

Feeds docs/data_inspection.md. Reads only from data/raw (or --raw-dir); writes PNGs to
docs/data_inspection/. Dev-only (needs matplotlib from the dev group)::

    uv run python -I scripts/inspect_datasets.py --only metropt3,uci_hydraulic,ims_bearings,mimii,maintie
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import wave
from collections import Counter
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import signal, stats

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "docs" / "data_inspection"

# Failure-report table from the UCI MetroPT-3 page (checked 2026-10-11). The page numbers the
# first two rows "#1"; they are distinct events by time, so the second is renumbered #2.
# Times are local (operator logs, timezone not stated), same clock as the CSV timestamps.
METROPT_FAILURES = [
    ("#1", "2020-04-18 00:00", "2020-04-18 23:59", "Air leak", "High stress", ""),
    (
        "#2 (page: #1)",
        "2020-05-29 23:30",
        "2020-05-30 06:00",
        "Air Leak",
        "High stress",
        "Maintenance on 30Apr at 12:00",
    ),
    (
        "#3",
        "2020-06-05 10:00",
        "2020-06-07 14:30",
        "Air Leak",
        "High stress",
        "Maintenance on 8Jun at 16:00",
    ),
    (
        "#4",
        "2020-07-15 14:30",
        "2020-07-15 19:00",
        "Air Leak",
        "High stress",
        "Maintenance on 16Jul at 00:00",
    ),
]


def _rng(s: pd.Series | np.ndarray) -> dict[str, float]:
    a = np.asarray(s, dtype=float)
    a = a[np.isfinite(a)]
    q = np.percentile(a, [0, 1, 50, 99, 100])
    return {
        "min": round(float(q[0]), 4),
        "p01": round(float(q[1]), 4),
        "median": round(float(q[2]), 4),
        "p99": round(float(q[3]), 4),
        "max": round(float(q[4]), 4),
        "mean": round(float(a.mean()), 4),
    }


# --------------------------------------------------------------------------------------
def inspect_metropt3(raw: Path) -> dict[str, Any]:
    df = pd.read_csv(raw / "metropt3" / "MetroPT3(AirCompressor).csv")
    df = df.rename(columns={df.columns[0]: "row"})
    ts = pd.to_datetime(df["timestamp"])
    dt_s = ts.diff().dt.total_seconds().iloc[1:]
    idx_step = df["row"].diff().iloc[1:]
    gaps = dt_s[dt_s > 60]
    big = dt_s.sort_values(ascending=False).head(8)
    res: dict[str, Any] = {
        "rows": len(df),
        "columns": list(df.columns),
        "t_first": str(ts.iloc[0]),
        "t_last": str(ts.iloc[-1]),
        "dt_mode_s": float(dt_s.mode().iloc[0]),
        "dt_counts_top": {str(k): int(v) for k, v in dt_s.value_counts().head(6).items()},
        "dt_share_10s": round(float((dt_s == 10).mean()), 5),
        "index_step_mode": float(idx_step.mode().iloc[0]),
        "index_step_share_10": round(float((idx_step == 10).mean()), 5),
        "n_gaps_gt_60s": len(gaps),
        "gap_total_hours": round(float(gaps.sum() / 3600), 2),
        "largest_gaps": [
            {"after": str(ts.iloc[i - 1]), "seconds": float(v)}
            for i, v in zip(big.index, big.values, strict=True)
        ],
        "non_monotonic": int((dt_s <= 0).sum()),
        "duplicate_timestamps": int(ts.duplicated().sum()),
        "ranges": {
            c: _rng(df[c])
            for c in [
                "TP2",
                "TP3",
                "H1",
                "DV_pressure",
                "Reservoirs",
                "Oil_temperature",
                "Motor_current",
            ]
        },
        "digital_unique": {
            c: sorted(map(float, df[c].unique()))[:6]
            for c in [
                "COMP",
                "DV_eletric",
                "Towers",
                "MPG",
                "LPS",
                "Pressure_switch",
                "Oil_level",
                "Caudal_impulses",
            ]
        },
    }
    # Per failure window: coverage + behaviour vs the 24 h before.
    s = df.set_index(ts)
    windows = []
    for nr, a, b, *_ in METROPT_FAILURES:
        t0, t1 = pd.Timestamp(a), pd.Timestamp(b)
        w = s.loc[t0:t1]
        pre = s.loc[t0 - pd.Timedelta(hours=24) : t0 - pd.Timedelta(seconds=1)]
        windows.append(
            {
                "nr": nr,
                "start": a,
                "end": b,
                "rows": len(w),
                "expected_rows_at_0.1Hz": int((t1 - t0).total_seconds() / 10) + 1,
                "first_row_index": int(w["row"].iloc[0]) if len(w) else None,
                "last_row_index": int(w["row"].iloc[-1]) if len(w) else None,
                "TP3_mean_window": round(float(w["TP3"].mean()), 3) if len(w) else None,
                "TP3_mean_pre24h": round(float(pre["TP3"].mean()), 3) if len(pre) else None,
                "TP3_min_window": round(float(w["TP3"].min()), 3) if len(w) else None,
                "LPS_share_window": round(float(w["LPS"].mean()), 4) if len(w) else None,
                "LPS_share_pre24h": round(float(pre["LPS"].mean()), 4) if len(pre) else None,
                "motor_on_share_window": round(float((w["Motor_current"] > 1).mean()), 3)
                if len(w)
                else None,
                "motor_on_share_pre24h": round(float((pre["Motor_current"] > 1).mean()), 3)
                if len(pre)
                else None,
            }
        )
    res["failure_windows"] = windows
    res["LPS_share_overall"] = round(float(df["LPS"].mean()), 5)
    res["motor_on_share_overall"] = round(float((df["Motor_current"] > 1).mean()), 4)

    # Plot: hourly min/mean TP3 + motor-on share over the whole span, failures shaded; zoom #4.
    hourly = s[["TP3", "Motor_current", "Oil_temperature"]].resample("1h")
    hmin, hmean = hourly.min(), hourly.mean()
    fig, axes = plt.subplots(3, 1, figsize=(13, 9))
    ax = axes[0]
    ax.plot(hmean.index, hmean["TP3"], lw=0.5, label="TP3 hourly mean")
    ax.plot(hmin.index, hmin["TP3"], lw=0.5, alpha=0.6, label="TP3 hourly min")
    ax.set_ylabel("bar")
    ax.set_title("MetroPT-3 TP3 (pneumatic panel pressure), failure-report windows shaded")
    ax2 = axes[1]
    ax2.plot(hmean.index, hmean["Oil_temperature"], lw=0.5, color="tab:red")
    ax2.set_ylabel("Oil temp (°C)")
    for a_ in axes[:2]:
        for _nr, a, b, *_ in METROPT_FAILURES:
            a_.axvspan(pd.Timestamp(a), pd.Timestamp(b), color="orange", alpha=0.35)
    axes[0].legend(loc="lower left", fontsize=8)
    nr, a, b, *_ = METROPT_FAILURES[3]
    t0, t1 = pd.Timestamp(a) - pd.Timedelta(hours=12), pd.Timestamp(b) + pd.Timedelta(hours=6)
    z = s.loc[t0:t1]
    ax3 = axes[2]
    ax3.plot(z.index, z["TP3"], lw=0.4, label="TP3 (bar)")
    ax3.plot(z.index, z["Motor_current"], lw=0.4, alpha=0.7, label="Motor current (A)")
    ax3.axvspan(pd.Timestamp(a), pd.Timestamp(b), color="orange", alpha=0.35)
    ax3.set_title(f"Zoom: failure {nr} ({a} to {b}), raw 0.1 Hz samples")
    ax3.legend(loc="lower left", fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "metropt3.png", dpi=110)
    plt.close(fig)
    return res


# --------------------------------------------------------------------------------------
HYD_SENSORS = {
    "PS1": 100,
    "PS2": 100,
    "PS3": 100,
    "PS4": 100,
    "PS5": 100,
    "PS6": 100,
    "EPS1": 100,
    "FS1": 10,
    "FS2": 10,
    "TS1": 1,
    "TS2": 1,
    "TS3": 1,
    "TS4": 1,
    "VS1": 1,
    "CE": 1,
    "CP": 1,
    "SE": 1,
}


def _runs(values: np.ndarray) -> list[tuple[int, int, Any]]:
    out, start = [], 0
    for i in range(1, len(values) + 1):
        if i == len(values) or values[i] != values[start]:
            out.append((start, i - 1, values[start]))
            start = i
    return out


def inspect_uci_hydraulic(raw: Path) -> dict[str, Any]:
    d = raw / "uci_hydraulic"
    prof = pd.read_csv(
        d / "profile.txt",
        sep="\t",
        header=None,
        names=["cooler_pct", "valve_pct", "pump_leak", "accum_bar", "stable_flag"],
    )
    res: dict[str, Any] = {"cycles": len(prof)}
    res["label_counts"] = {
        c: {str(k): int(v) for k, v in prof[c].value_counts().sort_index().items()}
        for c in prof.columns
    }
    stable = prof[prof.stable_flag == 0]
    res["stable_cycles(flag==0)"] = len(stable)
    res["healthy_stable_cycles"] = int(
        (
            (stable.cooler_pct == 100)
            & (stable.valve_pct == 100)
            & (stable.pump_leak == 0)
            & (stable.accum_bar == 130)
        ).sum()
    )
    res["target_cycles_stable"] = {
        "pump_leak==2": int((stable.pump_leak == 2).sum()),
        "valve==80": int((stable.valve_pct == 80).sum()),
        "valve==73": int((stable.valve_pct == 73).sum()),
        "accum==90": int((stable.accum_bar == 90).sum()),
        "cooler==3": int((stable.cooler_pct == 3).sum()),
    }
    # Contiguous runs of each label column (how the rig sequences conditions).
    res["runs_per_label"] = {
        c: len(_runs(prof[c].to_numpy())) for c in prof.columns if c != "stable_flag"
    }
    res["stable_flag_runs"] = [
        (int(a), int(b), int(v)) for a, b, v in _runs(prof.stable_flag.to_numpy()) if v == 1
    ][:15]
    sensors = {}
    shapes = {}
    for name, hz in HYD_SENSORS.items():
        arr = np.loadtxt(d / f"{name}.txt")
        shapes[name] = list(arr.shape)
        assert arr.shape == (len(prof), 60 * hz), (name, arr.shape)
        sensors[name] = {"hz": hz, **_rng(arr)}
        if name == "PS1":
            ps1 = arr
        if name == "EPS1":
            eps1 = arr
    res["sensor_shapes"] = shapes
    res["sensor_ranges"] = sensors
    # Per-cycle mean PS1 by pump-leak class (does the fault show in the raw signal?).
    res["PS1_cycle_mean_by_pump_leak"] = {
        str(k): round(float(ps1[stable.index[stable.pump_leak == k]].mean()), 3) for k in (0, 1, 2)
    }
    res["EPS1_cycle_mean_by_accum"] = {
        str(k): round(float(eps1[stable.index[stable.accum_bar == k]].mean()), 1)
        for k in (130, 115, 100, 90)
    }

    fig, axes = plt.subplots(3, 2, figsize=(13, 9))
    for ax, c in zip(axes.flat[:4], prof.columns[:4], strict=True):
        ax.plot(prof.index, prof[c], lw=0.7)
        ax.set_title(f"profile.txt: {c} per cycle")
        ax.set_xlabel("cycle #")
    ax = axes.flat[4]
    ax.plot(prof.index, prof.stable_flag, lw=0.7, color="tab:red")
    ax.set_title("stable_flag (0 = stable, 1 = not yet static)")
    ax = axes.flat[5]
    opt = (stable.cooler_pct == 100) & (stable.valve_pct == 100) & (stable.accum_bar == 130)
    i_h = int(stable.index[opt & (stable.pump_leak == 0)][0])
    i_f = int(stable.index[opt & (stable.pump_leak == 2)][0])
    t = np.arange(6000) / 100
    for i, lab in [(i_h, "pump_leak=0"), (i_f, "pump_leak=2")]:
        ax.plot(t, ps1[i], lw=0.4, alpha=0.6, label=f"PS1 100 Hz, cycle {i} ({lab}, rest optimal)")
        ax.plot(np.arange(60) + 0.5, ps1[i].reshape(60, 100).mean(1), "o-", ms=2, label="1 Hz mean")
    ax.set_title("PS1 one cycle: 100 Hz raw vs 1 Hz mean")
    ax.set_xlabel("s in cycle")
    ax.set_ylabel("bar")
    ax.legend(fontsize=6)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "uci_hydraulic.png", dpi=110)
    plt.close(fig)
    return res


# --------------------------------------------------------------------------------------
IMS_FS = 20_000
IMS_BPFO_HZ = 236.4  # outer-race defect frequency commonly reported for ZA-2115 at 2000 RPM


def inspect_ims(raw: Path) -> dict[str, Any]:
    d = raw / "ims_bearings" / "2nd_test" / "2nd_test"
    files = sorted(p for p in d.iterdir() if re.fullmatch(r"\d{4}(\.\d{2}){5}", p.name))
    times = pd.to_datetime([p.name for p in files], format="%Y.%m.%d.%H.%M.%S")
    rms = np.zeros((len(files), 4))
    kurt = np.zeros((len(files), 4))
    lengths = Counter()
    clipped = np.zeros(4, dtype=int)
    for i, p in enumerate(files):
        x = np.loadtxt(p)
        lengths[x.shape] += 1
        rms[i] = np.sqrt((x**2).mean(0))
        kurt[i] = stats.kurtosis(x, axis=0, fisher=False)
        clipped += (np.abs(x) >= 4.999).any(0)
    # The final snapshots are near-zero (rig/DAQ stopped): "last" means last *live* snapshot.
    live = rms.max(1) > 0.01
    last_live = int(np.flatnonzero(live)[-1])
    first = np.loadtxt(files[0])
    last = np.loadtxt(files[last_live])
    dt_min = np.diff(times.values).astype("timedelta64[s]").astype(float) / 60
    res: dict[str, Any] = {
        "files": len(files),
        "t_first": str(times[0]),
        "t_last": str(times[-1]),
        "shapes": {str(k): v for k, v in lengths.items()},
        "interval_min_counts": {
            str(round(k, 2)): int(v) for k, v in Counter(np.round(dt_min, 2)).most_common(5)
        },
        "max_interval_min": float(dt_min.max()),
        "rms_first_g": [round(float(v), 4) for v in rms[0]],
        "dead_snapshots": [str(times[i]) for i in np.flatnonzero(~live)],
        "last_live_snapshot": str(times[last_live]),
        "snapshots_with_clipping_at_5g_per_channel": clipped.tolist(),
        "rms_last_live_g": [round(float(v), 4) for v in rms[last_live]],
        "rms_max_g": [round(float(v), 4) for v in rms.max(0)],
        "kurtosis_first": [round(float(v), 2) for v in kurt[0]],
        "kurtosis_last_live": [round(float(v), 2) for v in kurt[last_live]],
        "kurtosis_max": [round(float(v), 2) for v in kurt.max(0)],
    }
    # Degradation onset estimate for bearing 1: first snapshot where RMS > baseline + 6 sigma
    # sustained for 6 consecutive snapshots (1 h). Baseline = first 200 snapshots.
    base = rms[:200, 0]
    thr = base.mean() + 6 * base.std()
    above = rms[:, 0] > thr
    onset = next(
        (i for i in range(len(above) - 6) if above[i : i + 6].all()),
        None,
    )
    res["b1_rms_baseline_g"] = round(float(base.mean()), 4)
    res["b1_onset_threshold_g"] = round(float(thr), 4)
    res["b1_onset_estimate"] = (
        {"index": int(onset), "time": str(times[onset])} if onset is not None else None
    )
    # Welch PSD of bearing 1: first vs last snapshot; top peaks of the last.
    f, p_first = signal.welch(first[:, 0], fs=IMS_FS, nperseg=4096)
    _, p_last = signal.welch(last[:, 0], fs=IMS_FS, nperseg=4096)
    pk, _ = signal.find_peaks(p_last)
    top = pk[np.argsort(p_last[pk])[::-1][:5]]
    res["b1_last_live_top5_peaks_hz"] = [round(float(f[i]), 1) for i in sorted(top)]
    # Envelope spectrum (classic outer-race check) on the last snapshot.
    b, a = signal.butter(4, [2000, 8000], btype="band", fs=IMS_FS)
    env = np.abs(signal.hilbert(signal.filtfilt(b, a, last[:, 0])))
    fe, pe = signal.welch(env - env.mean(), fs=IMS_FS, nperseg=8192)
    band = (fe > 50) & (fe < 600)
    res["b1_last_live_envelope_peak_hz"] = round(float(fe[band][np.argmax(pe[band])]), 1)
    # Same for a mid-life snapshot after onset, to see the defect before the end.
    if onset is not None:
        mid = np.loadtxt(files[min(onset + 50, len(files) - 1)])
        env_m = np.abs(signal.hilbert(signal.filtfilt(b, a, mid[:, 0])))
        fe2, pe2 = signal.welch(env_m - env_m.mean(), fs=IMS_FS, nperseg=8192)
        res["b1_onset+50_envelope_peak_hz"] = round(float(fe2[band][np.argmax(pe2[band])]), 1)

    fig, axes = plt.subplots(3, 1, figsize=(13, 10))
    for ch in range(4):
        axes[0].plot(times, rms[:, ch], lw=0.7, label=f"Bearing {ch + 1}")
    if onset is not None:
        axes[0].axvline(times[onset], color="k", ls="--", lw=0.8, label="B1 onset est.")
    axes[0].set_ylabel("RMS (g)")
    axes[0].set_title("IMS test 2: per-snapshot RMS (1 s @ 20 kHz every 10 min)")
    axes[0].legend(fontsize=8)
    for ch in range(4):
        axes[1].plot(times, kurt[:, ch], lw=0.7)
    axes[1].set_ylabel("kurtosis")
    axes[1].set_yscale("log")
    axes[2].semilogy(f, p_first, lw=0.6, label=f"B1 first ({times[0]})")
    axes[2].semilogy(f, p_last, lw=0.6, label=f"B1 last live ({times[last_live]})")
    axes[2].axvline(IMS_BPFO_HZ, color="r", ls=":", lw=0.8, label="BPFO ~236 Hz")
    axes[2].set_xlim(0, 3000)
    axes[2].set_xlabel("Hz")
    axes[2].set_title("Welch PSD, bearing 1")
    axes[2].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "ims_bearings.png", dpi=110)
    plt.close(fig)
    return res


# --------------------------------------------------------------------------------------
def inspect_mimii(raw: Path) -> dict[str, Any]:
    base = raw / "mimii" / "6_dB"
    res: dict[str, Any] = {}
    fig, axes = plt.subplots(2, 4, figsize=(15, 7))
    for j, machine in enumerate(["pump", "fan", "slider", "valve"]):
        clips = sorted((base / machine).rglob("*.wav"))
        info: dict[str, Any] = {"clips": len(clips)}
        params = Counter()
        durs = []
        rms = {"normal": [], "abnormal": []}
        ids = Counter()
        psd = {"normal": [], "abnormal": []}
        for p in clips:
            label = p.parent.name
            ids[f"{p.parent.parent.name}/{label}"] += 1
            with wave.open(str(p)) as w:
                params[(w.getframerate(), w.getnchannels(), w.getsampwidth())] += 1
                n = w.getnframes()
                durs.append(n / w.getframerate())
                x = np.frombuffer(w.readframes(n), dtype="<i2").reshape(-1, w.getnchannels())
            ch0 = x[:, 0].astype(float) / 32768
            rms[label].append(float(np.sqrt((ch0**2).mean())))
            f, pxx = signal.welch(ch0, fs=16000, nperseg=2048)
            psd[label].append(pxx)
        info["by_id_label"] = dict(sorted(ids.items()))
        info["format(sr,ch,bytes)"] = {str(k): v for k, v in params.items()}
        info["duration_s"] = {"min": min(durs), "max": max(durs), "total": round(sum(durs), 1)}
        info["rms_ch0"] = {k: _rng(v) for k, v in rms.items() if v}
        res[machine] = info
        ax = axes[0, j]
        for label, color in (("normal", "tab:blue"), ("abnormal", "tab:red")):
            if psd[label]:
                ax.semilogy(f, np.mean(psd[label], 0), color=color, lw=0.8, label=label)
        ax.set_title(f"{machine}: mean PSD ch0")
        ax.set_xlabel("Hz")
        ax.legend(fontsize=8)
        ax = axes[1, j]
        ax.boxplot([rms["normal"], rms["abnormal"]], tick_labels=["normal", "abnormal"])
        ax.set_title(f"{machine}: RMS ch0 per clip")
    fig.suptitle("MIMII 6 dB subset (range-extracted clips)")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "mimii.png", dpi=110)
    plt.close(fig)
    return res


# --------------------------------------------------------------------------------------
def inspect_maintie(raw: Path) -> dict[str, Any]:
    d = raw / "maintie"
    res: dict[str, Any] = {}
    all_tok = []
    texts_all: list[str] = []
    for name in ("gold_release.json", "silver_release.json"):
        data = json.loads((d / name).read_text())
        toks = [len(r["tokens"]) for r in data]
        chars = [len(r["text"]) for r in data]
        texts = [r["text"] for r in data]
        texts_all += texts
        all_tok += toks
        res[name] = {
            "records": len(data),
            "unique_texts": len(set(texts)),
            "tokens": _rng(toks),
            "chars": _rng(chars),
            "share_with_<id>": round(sum("<id>" in t for t in texts) / len(texts), 3),
            "entity_types_top": Counter(
                e["type"].split("/")[0] for r in data for e in r["entities"]
            ).most_common(6),
        }
    rng = random.Random(2026)
    res["examples_seeded"] = rng.sample(texts_all, 5)
    vocab = Counter(w for t in texts_all for w in t.split() if w != "<id>")
    res["top_tokens"] = vocab.most_common(25)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.hist(all_tok, bins=range(1, max(all_tok) + 2), color="tab:green")
    ax.set_title(f"MaintIE gold+silver: tokens per text (n={len(all_tok)})")
    ax.set_xlabel("tokens")
    fig.tight_layout()
    fig.savefig(OUT_DIR / "maintie.png", dpi=110)
    plt.close(fig)
    return res


INSPECTORS = {
    "metropt3": inspect_metropt3,
    "uci_hydraulic": inspect_uci_hydraulic,
    "ims_bearings": inspect_ims,
    "mimii": inspect_mimii,
    "maintie": inspect_maintie,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=",".join(INSPECTORS))
    ap.add_argument(
        "--raw-dir",
        type=Path,
        default=Path(os.environ.get("DATA_RAW_DIR", REPO_ROOT / "data" / "raw")),
    )
    args = ap.parse_args()
    raw = args.raw_dir if args.raw_dir.is_absolute() else REPO_ROOT / args.raw_dir
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = {k: INSPECTORS[k](raw) for k in args.only.split(",") if k}
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
