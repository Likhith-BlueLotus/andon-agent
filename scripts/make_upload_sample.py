"""Make the demo CSV for "bring your own CSV" from a SYNTHETIC S-set scenario.

    uv run python scripts/make_upload_sample.py [--scenario S005] [--hours 6] [--out data/samples/upload_air_leak.csv]

Reads only the scenario's agent-visible telemetry and stop record (never truth.json, never R-set /
MetroPT data: hard rule 2), resamples to 10 s bins and renames the columns the way a historian
export would. S005 is a compressed-air leak that stops the ST30 weld cell; the default 6 h window
ends at the stop and starts about an hour before the leak begins, so the leak is visible as a change.
The file is synthetic: it is committed (small) because the demo and the tests need it.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
COLUMNS = {  # historian-style name -> (asset_id, tag, decimals)
    "Compressor_Amps": ("UT-AIR", "compressor_current_a", 1),
    "Header_P_bar": ("UT-AIR", "header_pressure_bar", 2),
    "Gun_Air_ST20": ("ST20-WLD", "air_pressure_bar", 2),
    "Gun_Air_ST30": ("ST30-WLD", "air_pressure_bar", 2),
    "Weld_kA_ST30": ("ST30-WLD", "weld_current_ka", 2),
    "Servo_Temp_ST30": ("ST30-WLD", "servo_temp_c", 1),
    "Cycle_s_ST30": ("ST30-WLD", "cycle_time_s", 1),
    "Coolant_Lpm_ST30": ("ST30-WLD", "coolant_flow_lpm", 2),
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="S005")
    ap.add_argument("--hours", type=float, default=6.0)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "samples" / "upload_air_leak.csv")
    a = ap.parse_args()
    if not a.scenario.startswith("S"):
        raise SystemExit("only synthetic S-set scenarios may be used for the sample")
    d = ROOT / "data" / "scenarios" / a.scenario
    stop = pd.Timestamp(json.loads((d / "stop_event.json").read_text())["stop_ts"])
    start = stop - pd.Timedelta(hours=a.hours)
    t = pq.read_table(d / "telemetry.parquet", filters=[("ts", ">=", start.to_pydatetime())])
    df = t.to_pandas()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df[df["ts"] <= stop]
    out = {}
    for col, (asset, tag, dec) in COLUMNS.items():
        s = df[(df["asset_id"].astype(str) == asset) & (df["tag"].astype(str) == tag)]
        s = s.set_index("ts")["value"].astype(float).resample("10s", origin=start).mean()
        out[col] = s.round(dec)
    res = pd.DataFrame(out)
    res.index = res.index.strftime("%Y-%m-%dT%H:%M:%SZ")
    res.index.name = "Timestamp"
    a.out.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(a.out)
    print(f"{a.out}: {len(res)} rows x {len(res.columns)} columns, {a.out.stat().st_size} bytes")


if __name__ == "__main__":
    main()
