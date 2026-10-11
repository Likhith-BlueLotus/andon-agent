"""S-set generator CLI (SYNTHETIC_DATA_SPEC §4).

    uv run python -m simulator.generate --set S --n 60 --seed 2026 --out data/scenarios

* 10 classes x 6 variants (3 clean, 1 red_herring, 1 dual_fault, 1 no_fault) = 60 slots.
* Scenario numbering is a seeded shuffle of (class, variant): an ID never encodes its cause. The
  shuffle is re-drawn (deterministically) until the held-out block S051-S060 covers ≥ 8 classes.
* Per-scenario seed = seed*1000 + n. Same seed -> byte-identical files.
* Writes per scenario: telemetry.parquet, alarms.parquet, shift_notes.parquet, work_orders.parquet,
  provenance.parquet, stop_event.json, truth.json (+ sim_meta.json: hidden QA/audio-placement
  details, never loaded into the store). Also data/work_orders.parquet (2,000 historical WOs) and
  data/work_orders_labels.parquet (theme/cause labels for the eval's B2 baseline; never loaded).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from agents.schemas import CauseClass
from simulator import alarms as alarm_mod
from simulator import faults, imperfections, plant, text_artifacts
from simulator.faults import FaultContext, FaultInstance
from simulator.imperfections import Note
from simulator.plant import Modifiers, TagKey, rng_for
from simulator.text_artifacts import TextGen, TextMode
from simulator.truth_schema import GroundTruth

SIM_VERSION = "sim-1.0.0"
Variant = Literal["clean", "red_herring", "dual_fault", "no_fault"]
VARIANTS: tuple[Variant, ...] = ("clean", "clean", "clean", "red_herring", "dual_fault", "no_fault")
HELD_OUT = range(51, 61)
MIN_HELD_OUT_CLASSES = 8
DEFAULT_HISTORY_S = 7 * 86400
# Simulated before the window so a limit-anchored stop can move earlier and still keep a full week.
PRE_BUFFER_S = 8 * 3600
STOP_WINDOW = (datetime(2026, 8, 3, tzinfo=UTC), datetime(2026, 9, 28, tzinfo=UTC))
N_WORK_ORDERS = 2000
TS = pa.timestamp("s", tz="UTC")
# square-wave / sawtooth tags where extra sensor noise would be invisible: never the noisy herring
NOISY_EXCLUDED = {("UT-AIR", "compressor_current_a"), ("UT-AIR", "header_pressure_bar")}


# --- ID assignment ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Slot:
    group_class: CauseClass  # the class this slot belongs to (no_fault slots: the paired class)
    variant: Variant
    replicate: int


def all_slots() -> list[Slot]:
    return [Slot(c, v, k) for c in faults.S_SET_CLASSES for k, v in enumerate(VARIANTS)]


def assign_ids(seed: int) -> dict[str, Slot]:
    """Seeded shuffle of the 60 (class, variant) slots onto S001-S060. Re-drawn deterministically
    until the held-out block covers >= 8 classes and every variant (so red-herring and
    abstention robustness can be reported on held-out data too)."""
    slots = all_slots()
    for attempt in range(10_000):
        perm = np.random.default_rng([seed, 7919, attempt]).permutation(len(slots))
        order = [slots[i] for i in perm]
        held = {order[i - 1].group_class for i in HELD_OUT}
        held_variants = {order[i - 1].variant for i in HELD_OUT}
        if len(held) >= MIN_HELD_OUT_CLASSES and held_variants == set(VARIANTS):
            return {f"S{i + 1:03d}": s for i, s in enumerate(order)}
    raise RuntimeError("could not satisfy held-out coverage")  # pragma: no cover


# --- One scenario ----------------------------------------------------------------------------
@dataclass
class Scenario:
    scenario_id: str
    seed: int
    slot: Slot
    history_s: int = DEFAULT_HISTORY_S


def _stop_ts(seed: int) -> datetime:
    lo, hi = (int(t.timestamp()) for t in STOP_WINDOW)
    return datetime.fromtimestamp(int(rng_for(seed, "stop").integers(lo, hi)), tz=UTC)


def _iso(t: datetime | None) -> str | None:
    return None if t is None else t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _pick_root(fd: faults.FaultDef, avoid: set[str], rng: np.random.Generator) -> str | None:
    opts = [a for a in fd.root_assets if a not in avoid]
    return None if not opts else opts[int(rng.integers(len(opts)))]


def build(sc: Scenario, gen: TextGen, wo_pool: list[dict[str, Any]]) -> dict[str, Any]:
    """Simulate one scenario; returns in-memory tables and the truth (nothing written)."""
    seed, slot = sc.seed, sc.slot
    stop = _stop_ts(seed)
    primary_cls = CauseClass.NO_FAULT if slot.variant == "no_fault" else slot.group_class

    # Timeline (changeover_error needs a product-model change at its shift start)
    sim_s = sc.history_s + PRE_BUFFER_S
    tl = plant.make_timeline(stop, sim_s, rng_for(seed, "timeline"))
    if primary_cls is CauseClass.CHANGEOVER_ERROR:
        probe = FaultContext(tl, rng_for(seed, "probe"))
        idx = probe.shift_change_onset(1.0, 6.0)
        tl = plant.make_timeline(stop, sim_s, rng_for(seed, "timeline"), force_model_change_at=idx)
    mods = Modifiers(tl.n)

    # Primary fault (or the benign glitch)
    frng = rng_for(seed, "fault", "primary")
    if primary_cls is CauseClass.NO_FAULT:
        fd = faults.FAULTS[slot.group_class]
        station = fd.home_stations[int(frng.integers(len(fd.home_stations)))]
        primary = faults.no_fault(FaultContext(tl, frng), mods, station)
    else:
        primary = faults.inject(primary_cls, FaultContext(tl, frng), mods)
    assert primary.stop is not None

    secondary: FaultInstance | None = None
    distractors: list[str] = []
    extra_notes: list[Note] = []
    planted_wos: list[dict[str, Any]] = []
    touched = set(primary.touched)
    chain_assets = set(primary.chain) | ({primary.asset_id} if primary.asset_id else set())

    if slot.variant == "dual_fault":
        srng = rng_for(seed, "fault", "secondary")
        cands = [
            c
            for c in faults.compatible_secondaries(primary)
            if _pick_root(faults.FAULTS[c], chain_assets, np.random.default_rng(0))
        ]
        sec_cls = cands[int(srng.integers(len(cands)))]
        root = _pick_root(faults.FAULTS[sec_cls], chain_assets, srng)
        ctx = FaultContext(tl, srng, scale=float(srng.uniform(0.45, 0.6)), primary=False, root=root)
        secondary = faults.inject(sec_cls, ctx, mods)
        touched |= secondary.touched
        chain_assets |= set(secondary.chain)

    herring: tuple[str, TagKey, int, np.random.Generator] | None = None
    if slot.variant == "red_herring":
        hrng = rng_for(seed, "herring")
        stop_station = primary.stop.station
        cands = [
            a for a in [stop_station, *plant.upstream_of(stop_station)] if a not in chain_assets
        ]
        cands = cands or [a.asset_id for a in plant.ASSETS if a.asset_id not in chain_assets]
        blamed = cands[int(hrng.integers(len(cands)))]
        noisy_pool = sorted(
            k for k in plant.TAG_SPECS
            if k[0] not in chain_assets and k[0] != blamed and k not in touched and k not in NOISY_EXCLUDED
            and plant.TAG_SPECS[k].kind == "continuous"
        )  # fmt: skip
        nk = noisy_pool[int(hrng.integers(len(noisy_pool)))]
        n0 = tl.n - int(
            hrng.integers(PRE_BUFFER_S + 2 * 3600, min(PRE_BUFFER_S + 24 * 3600, int(0.5 * tl.n)))
        )
        mods.get("noise_mult", nk)[n0:] += float(hrng.uniform(2.5, 4.0))
        touched.add(nk)
        herring = (blamed, nk, n0, hrng)

    sim = plant.simulate(tl, mods, seed)

    # Anchor the stop: a hard-limit stop happens when that limit first fires, not at an arbitrary
    # time after it. Then keep exactly `history_s` of history ending at the stop.
    end = tl.n
    st = primary.stop
    if st.limit and primary.onset_idx is not None:
        c = alarm_mod.first_crossing(sim, tl, st.trigger[0], st.limit)
        if c is not None and c > primary.onset_idx:
            end = min(c + 1, tl.n)
    start = max(0, end - sc.history_s)
    tl, sim = tl.slice(start, end), sim.slice(start, end)
    primary = faults.shifted(primary, start)
    faults.finalize(primary, sim)
    if secondary:
        secondary = faults.shifted(secondary, start)
        faults.finalize(secondary, sim)

    if herring:
        blamed, nk, n0, hrng = herring
        n0 -= start
        distractors.append(f"noisy_tag|{nk[0]}|{nk[1]}|{_iso(tl.ts(n0))}|{_iso(tl.stop)}")
        if hrng.random() < 0.5:
            ts = tl.stop - timedelta(seconds=int(hrng.integers(3600, 12 * 3600)))
            note = text_artifacts.red_herring_note(blamed, ts, sc.scenario_id, hrng)
            extra_notes.append(note)
            distractors.append(f"planted_note|{blamed}|{note.note_id}|{_iso(ts)}")
        else:
            date = tl.stop - timedelta(seconds=int(hrng.integers(86400, 5 * 86400)))
            planted_wos.append(text_artifacts.red_herring_wo(blamed, date, "PLANTED", hrng))
            distractors.append(f"planted_wo|{blamed}|PLANTED|{_iso(date)}")

    alarms = alarm_mod.build_alarms(sim, tl, primary.stop, seed)

    # Shift notes from visible symptoms only
    nrng = rng_for(seed, "notes")
    slots = text_artifacts.note_slots(tl, alarms, primary.stop.text, nrng)
    notes = gen.run(text_artifacts.shift_notes(sc.scenario_id, slots, gen, nrng)) + extra_notes
    notes.sort(key=lambda x: x.ts)

    # Recent background WOs + planted one
    wrng = rng_for(seed, "recent_wos")
    wos = (
        text_artifacts.recent_wos(wo_pool, tl.stop, sc.scenario_id, wrng, int(wrng.integers(2, 6)))
        if wo_pool
        else []
    )
    wos = sorted(wos + planted_wos, key=lambda w: w["date"])
    for j, w in enumerate(wos):  # ids by date order, so a planted WO's id is not a tell
        w["wo_id"] = f"WO-{w['date']:%y}{90000 + int(sc.scenario_id[1:]) * 10 + j:05d}"
        if w in planted_wos:
            distractors = [d.replace("|PLANTED|", f"|{w['wo_id']}|") for d in distractors]

    # Imperfections (never on a causal-chain onset; stuck tag never a touched tag)
    onsets = dict(primary.asset_onsets)
    if secondary:
        for a, i in secondary.asset_onsets.items():
            onsets.setdefault(a, i)
    imp = imperfections.apply(
        tl, sim.values, alarms, notes,
        rng=rng_for(seed, "imperfections"),
        asset_onsets=onsets,
        excluded_assets=chain_assets | {primary.stop.station},
        excluded_tags=touched,
    )  # fmt: skip

    truth = GroundTruth(
        scenario_id=sc.scenario_id,
        seed=seed,
        scenario_set="synthetic",
        truth_source="injected",
        variant=slot.variant,
        root_cause_class=primary.cause,
        asset_id=primary.asset_id,
        onset_ts=tl.ts(primary.onset_idx) if primary.onset_idx is not None else None,
        detail=primary.detail,
        causal_chain=primary.chain,
        secondary_cause=secondary.cause if secondary else None,
        distractors=distractors,
        imperfections=[i.to_str() for i in imp.items],
        stop_station=primary.stop.station,
        stop_ts=tl.stop,
    )
    stop_event = {
        "scenario_id": sc.scenario_id,
        "line_id": plant.LINE_ID,
        "stop_ts": _iso(tl.stop),
        "stopped_station": primary.stop.station,
        "stop_code": primary.stop.code,
        "stop_text": primary.stop.text,
        "shift": tl.shift_at(tl.n - 1),
        "product_model": tl.model_at(tl.n - 1),
        "history_start": _iso(tl.start),
        "history_end": _iso(tl.stop),
        "plant_utc_offset": "+05:30",
    }
    meta = {
        "sim_version": SIM_VERSION,
        "group_class": slot.group_class.value,
        "replicate": slot.replicate,
        "primary": _fault_meta(primary, tl),
        "secondary": _fault_meta(secondary, tl) if secondary else None,
    }
    return {
        "tl": tl,
        "imp": imp,
        "truth": truth,
        "stop_event": stop_event,
        "meta": meta,
        "wos": wos,
        "sim": sim,
    }


def _fault_meta(f: FaultInstance, tl: plant.Timeline) -> dict[str, Any]:
    return {
        "cause": f.cause.value,
        "asset_id": f.asset_id,
        "onset_ts": _iso(tl.ts(f.onset_idx)) if f.onset_idx is not None else None,
        "chain": f.chain,
        "detail": f.detail,
        "asset_onsets": {a: _iso(tl.ts(i)) for a, i in sorted(f.asset_onsets.items())},
        "signature": [
            {
                "asset_id": s.asset_id,
                "tag": s.tag,
                "direction": s.direction,
                "onset_ts": _iso(tl.ts(s.onset_idx)),
                "downstream": s.downstream,
            }
            for s in f.signature
        ],
        "stop": None
        if f.stop is None
        else {
            "station": f.stop.station,
            "code": f.stop.code,
            "trigger": [list(t) for t in f.stop.trigger],
            "limit": f.stop.limit,
        },
        "manual": None if f.manual is None else {"doc": f.manual.doc, "topic": f.manual.topic},
        "audio": None
        if f.audio is None
        else {
            "machine_type": f.audio.machine_type,
            "asset_id": f.audio.asset_id,
            "abnormal_from": _iso(tl.ts(f.audio.from_idx)),
        },
    }


# --- Writing ---------------------------------------------------------------------------------
def _write(table: pa.Table, path: Path, **kw: Any) -> None:
    pq.write_table(
        table, path, compression="zstd", compression_level=6, write_statistics=True, **kw
    )


def _dict_col(values: list[str]) -> pa.DictionaryArray:
    return pa.array(values, pa.string()).dictionary_encode()


def telemetry_table(
    sid: str, tl: plant.Timeline, imp: imperfections.ImperfectionResult
) -> pa.Table:
    ts_parts, val_parts, a_idx, t_idx = [], [], [], []
    keys = sorted(imp.values)
    assets = sorted({k[0] for k in keys})
    tags = sorted({k[1] for k in keys})
    epoch0 = int(tl.start.timestamp())
    for aid, tag in keys:
        idx = np.flatnonzero(imp.keep[(aid, tag)])
        ts_parts.append(epoch0 + idx.astype(np.int64))
        val_parts.append(imp.values[(aid, tag)][idx])
        a_idx.append(np.full(len(idx), assets.index(aid), dtype=np.int32))
        t_idx.append(np.full(len(idx), tags.index(tag), dtype=np.int32))
    n = sum(len(x) for x in ts_parts)
    return pa.table(
        {
            "scenario_id": pa.DictionaryArray.from_arrays(
                np.zeros(n, dtype=np.int32), pa.array([sid])
            ),
            "asset_id": pa.DictionaryArray.from_arrays(np.concatenate(a_idx), pa.array(assets)),
            "tag": pa.DictionaryArray.from_arrays(np.concatenate(t_idx), pa.array(tags)),
            "ts": pa.array(np.concatenate(ts_parts), pa.int64()).cast(TS),
            "value": pa.array(np.concatenate(val_parts).astype(np.float32), pa.float32()),
        }
    )


def write_scenario(out: Path, sid: str, built: dict[str, Any]) -> Path:
    d = out / sid
    d.mkdir(parents=True, exist_ok=True)
    tl, imp = built["tl"], built["imp"]
    _write(
        telemetry_table(sid, tl, imp), d / "telemetry.parquet",
        row_group_size=1 << 20,
        use_dictionary=["scenario_id", "asset_id", "tag", "value"],
        column_encoding={"ts": "DELTA_BINARY_PACKED"},
    )  # fmt: skip
    al = imp.alarms
    _write(pa.table({
        "scenario_id": pa.array([sid] * len(al)),
        "ts": pa.array([a.ts for a in al], TS),
        "line_id": pa.array([plant.LINE_ID] * len(al)),
        "station": pa.array([a.station for a in al]),
        "asset_id": pa.array([a.asset_id for a in al]),
        "code": pa.array([a.code for a in al]),
        "severity": pa.array([a.severity for a in al]),
        "text": pa.array([a.text for a in al]),
    }), d / "alarms.parquet")  # fmt: skip
    nt = imp.notes
    _write(pa.table({
        "scenario_id": pa.array([sid] * len(nt)),
        "note_id": pa.array([x.note_id for x in nt]),
        "ts": pa.array([x.ts for x in nt], TS),
        "line_id": pa.array([plant.LINE_ID] * len(nt)),
        "author_role": pa.array([x.author_role for x in nt]),
        "text": pa.array([x.text for x in nt]),
    }), d / "shift_notes.parquet")  # fmt: skip
    _write(wo_table(built["wos"], sid), d / "work_orders.parquet")
    prov = built.get("provenance")  # R-set: per-segment real-source provenance
    _write(prov if prov is not None else provenance_table(sid, tl), d / "provenance.parquet")
    (d / "stop_event.json").write_text(
        json.dumps(built["stop_event"], indent=2, sort_keys=True) + "\n"
    )
    (d / "truth.json").write_text(
        json.dumps(built["truth"].model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    )
    (d / "sim_meta.json").write_text(json.dumps(built["meta"], indent=2, sort_keys=True) + "\n")
    return d


WO_SCHEMA = pa.schema([
    ("wo_id", pa.string()), ("date", TS), ("asset_id", pa.string()), ("symptom", pa.string()),
    ("action", pa.string()), ("outcome", pa.string()), ("technician_role", pa.string()),
    ("scenario_id", pa.string()), ("source_id", pa.string()),
])  # fmt: skip


def wo_table(rows: list[dict[str, Any]], scenario_id: str | None) -> pa.Table:
    cols: dict[str, list[Any]] = {f.name: [] for f in WO_SCHEMA}
    for r in rows:
        for f in WO_SCHEMA:
            if f.name == "scenario_id":
                cols[f.name].append(scenario_id)
            elif f.name == "source_id":
                cols[f.name].append(r.get("source_id", "synthetic"))
            else:
                cols[f.name].append(r[f.name])
    return pa.table(cols, schema=WO_SCHEMA)


def provenance_table(sid: str, tl: plant.Timeline) -> pa.Table:
    """One row per tag segment and per text artifact. Identical wording for every synthetic
    segment, so provenance never hints at which tags a fault touched."""
    ref = f"simulator {SIM_VERSION}"
    rows = [
        (sid, aid, tag, tl.start, tl.stop, "synthetic", ref,
         "simulated at 1 Hz; quantised to sensor resolution; data-quality imperfections applied")
        for aid, tag in sorted(plant.TAG_SPECS)
    ]  # fmt: skip
    rows += [
        (sid, "*", "alarms", tl.start, tl.stop + timedelta(minutes=10), "synthetic", ref,
         "derived deterministically from simulated telemetry and events"),
        (sid, "*", "shift_notes", tl.start, tl.stop + timedelta(minutes=10), "synthetic", ref,
         "written from visible symptoms only (gemini-3.1-flash-lite or fixed templates)"),
        (sid, "*", "work_orders", tl.start - timedelta(days=30), tl.stop, "synthetic", ref,
         "historical work-order texts; MaintIE used as style exemplars only"),
    ]  # fmt: skip
    names = ["scenario_id", "asset_id", "tag", "t0", "t1", "source_id", "source_ref", "transform"]
    cols = list(zip(*rows, strict=True))
    return pa.table(
        {
            n: pa.array(list(c), TS if n in ("t0", "t1") else pa.string())
            for n, c in zip(names, cols, strict=True)
        }
    )


# --- Work-order history ----------------------------------------------------------------------
def ensure_work_orders(data_dir: Path, gen: TextGen, seed: int, n: int = N_WORK_ORDERS,
                       maintie_dir: Path = Path("data/raw/maintie")) -> list[dict[str, Any]]:  # fmt: skip
    """Build (or rebuild from the text cache) data/work_orders.parquet + labels."""
    wos, labels = gen.run(text_artifacts.build_work_orders(gen, n, seed, maintie_dir))
    # The 4 MetroPT-3 failure reports, rewritten as UT-AIR work orders (source_id metropt3).
    from simulator.real_signals import metropt3_work_orders  # lazy: real_signals imports us

    src_wos, src_labels = metropt3_work_orders()
    wos = wos + src_wos  # appended (not re-sorted) so the S-set's WO pool order is unchanged
    labels += src_labels
    data_dir.mkdir(parents=True, exist_ok=True)
    _write(wo_table(wos, None), data_dir / "work_orders.parquet")
    lab = pa.Table.from_pylist(labels)
    _write(lab, data_dir / "work_orders_labels.parquet")
    kinds = {lb["wo_id"]: lb["kind"] for lb in labels}
    return [w for w in wos if kinds[w["wo_id"]] == "normal"]


# --- CLI -------------------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--set", choices=["S"], default="S")
    ap.add_argument("--n", type=int, default=60, help="generate S001..S<n> (max 60)")
    ap.add_argument("--ids", default="", help="comma-separated subset, e.g. S001,S007")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", type=Path, default=Path("data/scenarios"))
    ap.add_argument("--history-days", type=float, default=7.0)
    ap.add_argument(
        "--text",
        choices=["template", "cached", "live"],
        default="cached",
        help="template: no LLM; cached: cache only (templates on miss); live: call Gemini on miss",
    )
    ap.add_argument("--work-orders", type=int, default=N_WORK_ORDERS)
    ap.add_argument("--cache-dir", type=Path, default=text_artifacts.DEFAULT_CACHE_DIR)
    ap.add_argument(
        "--prune-cache", action="store_true", help="delete cache entries this run did not use"
    )
    args = ap.parse_args(argv)

    if not 1 <= args.n <= 60:
        ap.error("--n must be 1..60")
    mode: TextMode = args.text
    gen = TextGen(mode=mode, cache_dir=args.cache_dir)
    ids = assign_ids(args.seed)
    wanted = [s.strip() for s in args.ids.split(",") if s.strip()] or [
        f"S{i:03d}" for i in range(1, args.n + 1)
    ]
    t0 = time.time()
    data_dir = args.out.parent
    pool = ensure_work_orders(data_dir, gen, args.seed, args.work_orders)
    print(f"work orders: {args.work_orders} -> {data_dir / 'work_orders.parquet'}")
    for sid in wanted:
        num = int(sid[1:])
        sc = Scenario(sid, args.seed * 1000 + num, ids[sid], int(args.history_days * 86400))
        built = build(sc, gen, pool)
        d = write_scenario(args.out, sid, built)
        mb = sum(f.stat().st_size for f in d.iterdir()) / 1e6
        print(f"{sid}  {mb:6.1f} MB  {time.time() - t0:6.1f}s", flush=True)
    print(gen.summary())
    if args.prune_cache:
        if args.ids or args.n != 60:
            print("--prune-cache ignored: only valid for a full --n 60 run", file=sys.stderr)
        else:
            print(f"pruned {gen.prune()} unused cache entries")
    if gen.failures:
        print(f"text validation fallbacks: {len(gen.failures)}", file=sys.stderr)
        for f in gen.failures[:20]:
            print("  " + f, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
