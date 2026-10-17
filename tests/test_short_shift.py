"""Short-shift scan (ADR-033): a 10-20 min step right before the stop that PELT's physical
minimum effect removes must be reported in ``short_shift``; healthy windows must not be.

Offline: synthetic 1 Hz series with the plant's own AR(1) noise model, plus one simulator build
for the dev-set injector. No store, no LLM."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from agents.schemas import CauseClass
from analytics import changepoints
from analytics.series import Series, signal_def
from simulator import faults
from simulator.generate import Scenario, Slot, build, dev_slots
from simulator.plant import tag_spec
from simulator.text_artifacts import TextGen

STOP = int(datetime(2026, 9, 10, 12, 0, tzinfo=UTC).timestamp())  # 17:30 local: no changeover
DAYS = 3


def _series(asset: str, tag: str, seed: int, step: float = 0.0, step_s: int = 720,
            noise_mult_tail: float = 1.0) -> Series:  # fmt: skip
    """1 Hz AR(1) noise around the nominal (the plant's TagSpec noise model), quantised to the
    sensor resolution; optional level step (fraction of nominal) over the last ``step_s``."""
    sp = tag_spec(asset, tag)
    n = DAYS * 86400
    rng = np.random.default_rng(seed)
    e = rng.normal(0.0, sp.noise_std * np.sqrt(1 - sp.ar**2), n)
    x = np.empty(n)
    x[0] = e[0]
    for i in range(1, n):
        x[i] = sp.ar * x[i - 1] + e[i]
    x[n - step_s :] *= noise_mult_tail
    v = sp.nominal + x
    v[n - step_s :] += step * sp.nominal
    v = np.round(v / sp.resolution) * sp.resolution
    t = np.arange(STOP - n, STOP, dtype=np.int64)
    return Series(t, v)


def _detect(s: Series, asset: str, tag: str, span_s: int) -> dict:
    t0 = STOP - span_s
    return changepoints.detect(s.window(t0, STOP), t0, STOP, signal_def(asset, tag), s)


@pytest.mark.parametrize("span_s", [3600, 4 * 3600, 86400])
def test_12min_step_is_reported_in_short_shift(span_s):
    # +2.5 % on the press motor current (1.05 A, ~3 bin-sigma): below PELT's 8 %-of-span floor
    s = _series("ST10-PRS", "motor_current_a", seed=11, step=0.025, step_s=720)
    r = _detect(s, "ST10-PRS", "motor_current_a", span_s)
    sh = r["short_shift"]
    assert sh["status"] == "found", sh
    assert sh["direction"] == "up"
    onset = STOP - 720
    assert (
        abs(int(datetime.fromisoformat(sh["ts"].replace("Z", "+00:00")).timestamp()) - onset) <= 180
    )
    assert 0.6 < sh["delta"] / (0.025 * 42.0) < 1.4
    assert sh["end_ts"] == datetime.fromtimestamp(STOP, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    # the old output is untouched: PELT + min_effect alone does not report this step
    assert not [c for c in r["change_points"] if c["ts"] >= sh["baseline"]["t1"]]


def test_down_step_on_oil_temperature():
    s = _series("ST10-PRS", "oil_temp_c", seed=5, step=-0.02, step_s=900)
    sh = _detect(s, "ST10-PRS", "oil_temp_c", 86400)["short_shift"]
    assert sh["status"] == "found" and sh["direction"] == "down"


@pytest.mark.parametrize("seed", range(8))
@pytest.mark.parametrize("tag", ["motor_current_a", "hyd_pressure_bar", "oil_temp_c",
                                 "vibration_rms_mms"])  # fmt: skip
def test_no_short_shift_on_a_healthy_window(seed, tag):
    s = _series("ST10-PRS", tag, seed=100 + seed)
    for span in (3600, 86400):
        sh = _detect(s, "ST10-PRS", tag, span)["short_shift"]
        assert sh["status"] == "none", (tag, seed, span, sh)


def test_noise_increase_alone_is_not_a_level_shift():
    s = _series("ST10-PRS", "hyd_pressure_bar", seed=3, step_s=1200, noise_mult_tail=3.0)
    assert _detect(s, "ST10-PRS", "hyd_pressure_bar", 3600)["short_shift"]["status"] == "none"


def test_tail_stays_inside_the_window_and_short_windows_are_insufficient():
    s = _series("ST10-PRS", "motor_current_a", seed=11, step=0.05, step_s=3000)
    sh = _detect(s, "ST10-PRS", "motor_current_a", 1800)["short_shift"]
    assert sh["status"] == "found"
    assert sh["ts"] >= datetime.fromtimestamp(STOP - 1800, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    tiny = _detect(s, "ST10-PRS", "motor_current_a", 240)
    assert tiny["short_shift"]["status"] == "insufficient_data"


def test_short_shift_is_deterministic():
    s = _series("ST10-PRS", "motor_current_a", seed=11, step=0.025)
    assert _detect(s, "ST10-PRS", "motor_current_a", 3600) == _detect(
        s, "ST10-PRS", "motor_current_a", 3600
    )


# --- dev-set injector (simulator principle: signature in the right tag, direction, after onset)
def _null(sub: str):
    """Same injector, same rng draws, but its modifiers are thrown away: the plant noise is
    identical, so (faulted - null) is exactly the fault's effect."""
    from simulator.plant import Modifiers

    inj = faults.short_hydraulic(sub)
    return lambda ctx, mods: inj(ctx, Modifiers(mods.n))


@pytest.mark.parametrize("sub", faults.HYDRAULIC_SUBTYPES)
def test_short_hydraulic_signature(sub):
    slot = Slot(CauseClass.HYDRAULIC_DEGRADATION, "clean", 0)
    g = TextGen(mode="template")
    b = build(
        Scenario("S199", 2033199, slot, 2 * 86400, injector=faults.short_hydraulic(sub)), g, []
    )
    b0 = build(Scenario("S199", 2033199, slot, 2 * 86400, injector=_null(sub)), g, [])
    tr, sim, meta = b["truth"], b["sim"], b["meta"]["primary"]
    assert tr.root_cause_class is CauseClass.HYDRAULIC_DEGRADATION and tr.variant == "clean"
    assert b0["truth"].stop_ts == tr.stop_ts and b0["truth"].onset_ts == tr.onset_ts
    dur = int((tr.stop_ts - tr.onset_ts).total_seconds())
    assert 600 <= dur <= 1200
    assert tr.detail.startswith(f"short_{sub}|")
    mag = float(tr.detail.split("mag_pct=")[1].split("|")[0]) / 100
    assert 0.005 <= mag <= 0.06
    for s in meta["signature"]:
        key = (s["asset_id"], s["tag"])
        diff = sim.values[key].astype(float) - b0["sim"].values[key].astype(float)
        n = len(diff)
        on = n - dur
        assert np.all(diff[: on - 1] == 0), (sub, s["tag"])  # nothing before onset
        late = s["direction"] * diff[n - 120 :].mean()  # right tag, right direction, after onset
        nominal = tag_spec(*key).nominal
        assert late > 0.5 * mag * nominal, (sub, s["tag"], late, mag * nominal)


def test_dev_ids_are_a_shuffle_and_never_overwrite_the_s_set(tmp_path):
    from simulator import generate

    a, b = dev_slots(2033), dev_slots(2033)
    assert a == b and sorted(a) == [f"S{i}" for i in range(101, 113)]
    subs = [sub for _, sub in a.values()]
    assert subs.count(None) == 2 and subs != sorted(subs, key=str)
    with pytest.raises(SystemExit):
        generate.main(["--set", "D", "--out", str(Path("data/scenarios"))])


def test_window_past_the_history_end_scans_up_to_the_last_sample():
    s = _series("ST10-PRS", "motor_current_a", seed=11, step=0.025, step_s=720)
    t0, t1 = STOP - 3600, STOP + 1800  # tools allow 1 h of slack past the history
    r = changepoints.detect(s.window(t0, t1), t0, t1, signal_def("ST10-PRS", "motor_current_a"), s)
    assert r["short_shift"]["status"] == "found"


def test_window_ending_in_a_changeover_is_insufficient_not_none():
    # 08:40 UTC = 14:10 local: inside the 14:00 changeover (+ restart tail)
    t1 = int(datetime(2026, 9, 10, 8, 40, tzinfo=UTC).timestamp())
    s = _series("ST10-PRS", "motor_current_a", seed=2)
    s = Series(s.t - (STOP - t1), s.v)
    r = changepoints.detect(s.window(t1 - 3600, t1), t1 - 3600, t1,
                            signal_def("ST10-PRS", "motor_current_a"), s)  # fmt: skip
    assert r["short_shift"]["status"] == "insufficient_data"
    assert "changeover" in r["short_shift"]["reason"]


@pytest.mark.parametrize("end_h", [1.5, 3.0, 6.5])  # hours after the 14:00 shift start
def test_setpoint_by_product_model_is_not_a_short_shift(end_h):
    """Press pressure follows the product model (180 / 190 bar), set per shift. Three of the last
    six days ran the 14:00 shift at 190 bar, today at 180. A daily profile cut at the tail start
    mixes 7-day medians (0) before the cut with 6-day medians (5 bar, the mean of the two middle
    values) after it, i.e. a fake 5-bar step (S025 healthy window). The profile must rest on
    whole days."""
    from simulator import plant

    sp = tag_spec("ST10-PRS", "hyd_pressure_bar")
    off = plant.PLANT_UTC_OFFSET_S
    shift0 = int(datetime(2026, 9, 10, 8, 30, tzinfo=UTC).timestamp())  # 14:00 local
    t1 = shift0 + int(end_h * 3600)
    t = np.arange(t1 - 7 * 86400, t1, dtype=np.int64)
    day = (t + off) // 86400 - (t1 + off) // 86400  # 0 = today, -1 = yesterday, ...
    hour = ((t + off) % 86400) // 3600
    b_shift = (hour >= 14) & (hour < 22)
    v = np.where(b_shift & (day >= -3) & (day <= -1), 190.0, 180.0)
    rng = np.random.default_rng(7)
    v = np.round((v + rng.normal(0, sp.noise_std, len(t))) / sp.resolution) * sp.resolution
    s = Series(t, v)
    for span in (3600, 86400):
        r = changepoints.detect(s.window(t1 - span, t1), t1 - span, t1,
                                signal_def("ST10-PRS", "hyd_pressure_bar"), s)  # fmt: skip
        assert r["short_shift"]["status"] in ("none", "insufficient_data"), r["short_shift"]


def test_coarse_bin_tags_are_not_scanned():
    """Per-cycle tags (5-min bins) are outside the short scan (ADR-033): status says so."""
    s = _series("ST10-PRS", "cycle_time_s", seed=4, step=0.05, step_s=1800)
    sh = _detect(s, "ST10-PRS", "cycle_time_s", 86400)["short_shift"]
    assert sh["status"] == "not_applicable" and sh["bin_s"] == 300
