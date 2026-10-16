"""Audio placement (SYNTHETIC_DATA_SPEC §7): real MIMII clips placed on the synthetic line.

    uv run python -m simulator.audio --scenarios data/scenarios            # place (local only)
    uv run python -m simulator.audio --scenarios data/scenarios --upload   # + upload to GCS

Machine mapping (DATA_SOURCES.md): pump -> ST40-SLR, slider -> ST50-CNV, fan -> ST20-WLD and
ST30-WLD (servo cabinet cooling), valve -> UT-AIR. Every scenario gets the same clip pattern on
each of those five assets, so the *presence* of a clip never hints at a fault:

* three baseline clips spread over the history and one recent clip shortly before the stop;
* one machine id per asset per scenario (ST20/ST30 use two different fan ids), so the MFCC
  baseline compares like with like (MIMII loudness differs by machine id; data_inspection §4);
* the recent clip on an asset whose fault has an audio signature (``sim_meta.json`` audio hint)
  is an *abnormal* clip, placed after the fault became audible; every other clip is normal;
* one scenario in each block of ten gets a deliberately noisy but normal recent clip (pink
  noise + 50 Hz hum at 3 dB SNR) on an asset with no fault, to test that ``listen`` does not
  cry wolf.

Clips are downmixed from 8 channels to mono (mean of the channels; 16 kHz, 16-bit) - that is
what ``listen()`` sends to Gemini and what the MFCC baseline reads.

Outputs per scenario:

* ``audio_index.json`` (agent-visible): ts, asset, machine type and id, ``gs://`` URI, local file.
  It carries **no** normal/abnormal label and no MIMII folder name.
* ``audio_truth.json`` (eval-only, never loaded into the store, never read by agents/ or api/):
  label, original MIMII path and SHA-256, noisy flag.
* ``provenance.parquet``: one ``tag='audio'`` row per clip (source_id ``mimii``). The source_ref
  names the zip, machine id, file number and SHA-256 prefix (exactly traceable through
  ``data/raw/mimii/manifest.json``) but withholds the ``normal``/``abnormal`` folder name, because
  provenance is visible to the agents.

GCS layout: ``gs://<bucket>/audio/{scenario_id}/{asset_id}/{YYYYmmddTHHMMSSZ}.wav`` plus
``audio/{scenario_id}/audio_index.json``. MIMII is CC BY-SA 4.0: the uploaded clips stay
CC BY-SA 4.0 with attribution (data/SOURCES.md).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.io import wavfile

from simulator.plant import rng_for

AUDIO_ASSETS: dict[str, str] = {
    "ST20-WLD": "fan",
    "ST30-WLD": "fan",
    "ST40-SLR": "pump",
    "ST50-CNV": "slider",
    "UT-AIR": "valve",
}
SNR_DIR = "6_dB"
SAMPLE_RATE_HZ = 16_000
CLIP_S = 10
DOWNMIX = "mono-mean-v1"
NOISY = "pink-noise+50Hz-hum@3dB-SNR-v1"
NOISY_SNR_DB = 3.0
BASELINE_FRACTIONS = (0.12, 0.45, 0.80)  # of the history, +/- jitter
RECENT_MIN_S, RECENT_MAX_S = 8 * 60, 50 * 60  # recent clip: this long before the stop
DEFAULT_BUCKET = "andon-511816-assets"
DEFAULT_RAW = Path("data/raw/mimii")
DEFAULT_CLIP_DIR = Path("data/audio/clips")
TS = pa.timestamp("s", tz="UTC")
PROV_NAMES = ["scenario_id", "asset_id", "tag", "t0", "t1", "source_id", "source_ref", "transform"]


@dataclass(frozen=True)
class SourceClip:
    machine_type: str
    machine_id: str
    label: str  # normal | abnormal
    path: str  # relative to data/raw/mimii, e.g. 6_dB/pump/id_00/normal/00000012.wav
    sha256: str

    @property
    def number(self) -> str:
        return Path(self.path).name


@dataclass(frozen=True)
class Hint:
    """An asset whose fault is audible from ``from_ts`` on (from sim_meta.json)."""

    asset_id: str
    machine_type: str
    from_ts: datetime


@dataclass(frozen=True)
class Placed:
    ts: datetime
    asset_id: str
    src: SourceClip
    noisy: bool = False

    @property
    def key(self) -> str:
        parts = [self.src.sha256, DOWNMIX] + (
            [NOISY, self.ts.isoformat(), self.asset_id] if self.noisy else []
        )
        return hashlib.sha256("|".join(parts).encode()).hexdigest()[:20]

    @property
    def ts_name(self) -> str:
        return self.ts.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")

    def object_name(self, scenario_id: str) -> str:
        return f"audio/{scenario_id}/{self.asset_id}/{self.ts_name}.wav"


# --- Source pool -----------------------------------------------------------------------------
def load_pool(raw: Path = DEFAULT_RAW) -> dict[tuple[str, str], dict[str, list[SourceClip]]]:
    """(machine_type, machine_id) -> {"normal": [...], "abnormal": [...]} from the manifest."""
    man = json.loads((raw / "manifest.json").read_text())
    pool: dict[tuple[str, str], dict[str, list[SourceClip]]] = {}
    for f in man["files"]:
        parts = Path(f["path"]).parts  # 6_dB/<type>/<id>/<label>/<file>.wav
        if len(parts) != 5 or parts[0] != SNR_DIR or not parts[4].endswith(".wav"):
            continue
        clip = SourceClip(parts[1], parts[2], parts[3], f["path"], f["sha256"])
        pool.setdefault((clip.machine_type, clip.machine_id), {"normal": [], "abnormal": []})
        pool[(clip.machine_type, clip.machine_id)][clip.label].append(clip)
    for v in pool.values():
        for lab in v:
            v[lab].sort(key=lambda c: c.path)
    return pool


def machine_ids(pool: dict, machine_type: str) -> list[str]:
    return sorted(i for t, i in pool if t == machine_type)


# --- Placement -------------------------------------------------------------------------------
def _iso(t: datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)


def hints_from_meta(meta: dict[str, Any]) -> list[Hint]:
    out = []
    for k in ("primary", "secondary"):
        f = meta.get(k) or {}
        a = f.get("audio")
        if a:
            out.append(Hint(a["asset_id"], a["machine_type"], _parse(a["abnormal_from"])))
    return out


def plan(
    scenario_id: str,
    seed: int,
    start: datetime,
    stop: datetime,
    hints: list[Hint],
    pool: dict,
    noisy: bool = False,
) -> list[Placed]:
    """Deterministic clip placement for one scenario (see module docstring)."""
    rng = rng_for(seed, "audio")
    hist = (stop - start).total_seconds()
    by_asset = {h.asset_id: h for h in hints}
    for h in hints:
        if AUDIO_ASSETS.get(h.asset_id) != h.machine_type:
            raise ValueError(f"{scenario_id}: audio hint {h} does not match the machine mapping")
    # machine id per asset (two fans -> two different ids)
    ids: dict[str, str] = {}
    for mtype in sorted(set(AUDIO_ASSETS.values())):
        assets = sorted(a for a, t in AUDIO_ASSETS.items() if t == mtype)
        choice = rng.permutation(machine_ids(pool, mtype))[: len(assets)]
        if len(choice) < len(assets):
            raise ValueError(f"not enough {mtype} machine ids in the MIMII pool")
        ids.update({a: str(i) for a, i in zip(assets, choice, strict=True)})
    quiet = sorted(a for a in AUDIO_ASSETS if a not in by_asset)
    noisy_asset = quiet[int(rng.integers(len(quiet)))] if noisy and quiet else None

    out: list[Placed] = []
    for aid in sorted(AUDIO_ASSETS):
        arng = rng_for(seed, "audio", aid)
        src = pool[(AUDIO_ASSETS[aid], ids[aid])]
        normals = [src["normal"][i] for i in arng.permutation(len(src["normal"]))]
        hint = by_asset.get(aid)
        recent = stop - timedelta(seconds=int(arng.integers(RECENT_MIN_S, RECENT_MAX_S + 1)))
        latest_baseline = stop - timedelta(hours=2)
        if hint is not None:
            if recent < hint.from_ts:  # fault audible only very late: clip between onset and stop
                recent = hint.from_ts + (stop - timedelta(seconds=CLIP_S + 5) - hint.from_ts) / 2
            latest_baseline = min(latest_baseline, hint.from_ts - timedelta(hours=1))
        times = []
        for f in BASELINE_FRACTIONS:
            t = start + timedelta(seconds=int(hist * (f + arng.uniform(-0.04, 0.04))))
            t = min(t, latest_baseline - timedelta(seconds=int(arng.integers(0, 1800))))
            if t >= start + timedelta(minutes=5) and all(
                abs((t - u).total_seconds()) > 1800 for u in times
            ):
                times.append(t)
        for t, clip in zip(times, normals, strict=False):
            out.append(Placed(t.replace(microsecond=0), aid, clip))
        if hint is not None:
            ab = src["abnormal"]
            clip = ab[int(arng.integers(len(ab)))]
            out.append(Placed(recent.replace(microsecond=0), aid, clip))
        else:
            out.append(
                Placed(recent.replace(microsecond=0), aid, normals[len(times)], aid == noisy_asset)
            )
    for p in out:
        if not (start <= p.ts and p.ts + timedelta(seconds=CLIP_S) <= stop):
            raise AssertionError(f"{scenario_id}: clip {p} outside history")
    return sorted(out, key=lambda p: (p.ts, p.asset_id))


SET_SIZES = {"S": 60, "R": 17}  # canonical set sizes, so a subset run picks the same scenarios


def noisy_scenarios(scenario_ids: list[str], seed: int = 2026) -> set[str]:
    """One scenario per block of ten (S001-S010, ..., R011-R017) gets the noisy-normal clip.
    The pick depends only on the canonical ID blocks, not on which directories exist."""
    out = set()
    for letter, b in sorted({(sid[0], (int(sid[1:]) - 1) // 10) for sid in scenario_ids}):
        total = SET_SIZES.get(letter, max(int(s[1:]) for s in scenario_ids if s[0] == letter))
        size = max(1, min(10, total - b * 10))
        k = int(rng_for(seed, "noisy-audio", letter, b).integers(size))
        out.add(f"{letter}{b * 10 + 1 + k:03d}")
    return out


# --- Audio processing ------------------------------------------------------------------------
def downmix(path: Path) -> np.ndarray:
    """8-channel int16 wav -> mono float64 in [-1, 1] (mean of the channels)."""
    sr, x = wavfile.read(path)
    if sr != SAMPLE_RATE_HZ:
        raise ValueError(f"{path}: {sr} Hz, expected {SAMPLE_RATE_HZ}")
    x = x.astype(np.float64) / 32768.0
    return x.mean(axis=1) if x.ndim == 2 else x


def add_noise(y: np.ndarray, key: str) -> np.ndarray:
    """Pink noise + 50 Hz mains hum (with 100/150 Hz harmonics) at NOISY_SNR_DB."""
    rng = np.random.default_rng(int(key[:12], 16))
    n = len(y)
    spec = np.fft.rfft(rng.standard_normal(n))
    f = np.fft.rfftfreq(n, 1 / SAMPLE_RATE_HZ)
    spec[1:] /= np.sqrt(f[1:])
    spec[0] = 0
    pink = np.fft.irfft(spec, n)
    t = np.arange(n) / SAMPLE_RATE_HZ
    hum = sum(
        a * np.sin(2 * np.pi * h * t + rng.uniform(0, 6.28))
        for h, a in ((50, 1.0), (100, 0.5), (150, 0.25))
    )
    noise = pink / np.sqrt(np.mean(pink**2)) + 0.5 * hum / np.sqrt(np.mean(hum**2))
    p_sig = float(np.mean(y**2))
    noise *= np.sqrt(p_sig / 10 ** (NOISY_SNR_DB / 10) / float(np.mean(noise**2)))
    return y + noise


def render(p: Placed, raw: Path, clip_dir: Path) -> Path:
    """Write (once) the mono 16 kHz int16 clip for ``p`` into the content-addressed cache."""
    out = clip_dir / f"{p.key}.wav"
    if out.exists():
        return out
    y = downmix(raw / p.src.path)
    if p.noisy:
        y = add_noise(y, p.key)
    peak = float(np.max(np.abs(y))) if len(y) else 0.0
    if peak > 0.999:  # never clip: scale down only if the added noise would overflow
        y = y * (0.999 / peak)
    clip_dir.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp.wav")
    wavfile.write(tmp, SAMPLE_RATE_HZ, np.round(y * 32767).astype(np.int16))
    tmp.rename(out)
    return out


# --- Writing ---------------------------------------------------------------------------------
def source_ref(src: SourceClip) -> str:
    return (
        f"MIMII {SNR_DIR}_{src.machine_type}.zip :: {src.machine_type}/{src.machine_id}/<label withheld>/"
        f"{src.number} (sha256 {src.sha256[:16]}; full path in data/raw/mimii/manifest.json)"
    )


def transform(p: Placed) -> str:
    t = (
        f"8-ch 16 kHz 16-bit wav downmixed to mono (mean of channels), 16 kHz int16, {CLIP_S} s; "
        f"placed at plant time {_iso(p.ts)} on {p.asset_id}"
    )
    if p.noisy:
        t += "; plant background added (pink noise + 50 Hz hum, 3 dB SNR)"
    return t + "; licence CC BY-SA 4.0 (attribution in data/SOURCES.md)"


def write(
    scenario_dir: Path,
    placed: list[Placed],
    bucket: str,
    clip_dir: Path,
    raw: Path,
    hints: list[Hint],
) -> None:
    sid = scenario_dir.name
    index = {
        "scenario_id": sid,
        "clip_duration_s": CLIP_S,
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "channels": 1,
        "source": "MIMII (Zenodo 3384388), CC BY-SA 4.0; real machine sound mapped onto the synthetic line",
        "clips": [
            {
                "ts": _iso(p.ts),
                "asset_id": p.asset_id,
                "machine_type": p.src.machine_type,
                "machine_id": p.src.machine_id,
                "gs_uri": f"gs://{bucket}/{p.object_name(sid)}",
                "local_file": str(render(p, raw, clip_dir)),
            }
            for p in placed
        ],
    }
    truth = {
        "scenario_id": sid,
        "eval_only": "never load into the store; never read from agents/ or api/",
        "hints": [
            {"asset_id": h.asset_id, "machine_type": h.machine_type, "from_ts": _iso(h.from_ts)}
            for h in hints
        ],
        "clips": [
            {
                "ts": _iso(p.ts),
                "asset_id": p.asset_id,
                "label": p.src.label,
                "noisy_normal": p.noisy,
                "source_path": p.src.path,
                "source_sha256": p.src.sha256,
                "gs_uri": f"gs://{bucket}/{p.object_name(sid)}",
            }
            for p in placed
        ],
    }
    (scenario_dir / "audio_index.json").write_text(
        json.dumps(index, indent=1, sort_keys=True) + "\n"
    )
    (scenario_dir / "audio_truth.json").write_text(
        json.dumps(truth, indent=1, sort_keys=True) + "\n"
    )
    _write_provenance(scenario_dir, placed)


def _write_provenance(scenario_dir: Path, placed: list[Placed]) -> None:
    path = scenario_dir / "provenance.parquet"
    old = pq.read_table(path).to_pylist() if path.exists() else []
    rows = [r for r in old if r["tag"] != "audio"]
    for p in placed:
        rows.append(
            {
                "scenario_id": scenario_dir.name,
                "asset_id": p.asset_id,
                "tag": "audio",
                "t0": p.ts,
                "t1": p.ts + timedelta(seconds=CLIP_S),
                "source_id": "mimii",
                "source_ref": source_ref(p.src),
                "transform": transform(p),
            }
        )
    tbl = pa.table(
        {
            n: pa.array([r[n] for r in rows], TS if n in ("t0", "t1") else pa.string())
            for n in PROV_NAMES
        }
    )
    pq.write_table(tbl, path, compression="zstd", compression_level=6, write_statistics=True)


def place_scenario(
    scenario_dir: Path,
    pool: dict,
    noisy: bool,
    bucket: str = DEFAULT_BUCKET,
    clip_dir: Path = DEFAULT_CLIP_DIR,
    raw: Path = DEFAULT_RAW,
) -> list[Placed]:
    se = json.loads((scenario_dir / "stop_event.json").read_text())
    truth = json.loads((scenario_dir / "truth.json").read_text())
    meta = json.loads((scenario_dir / "sim_meta.json").read_text())
    hints = hints_from_meta(meta)
    placed = plan(
        scenario_dir.name,
        int(truth["seed"]),
        _parse(se["history_start"]),
        _parse(se["stop_ts"]),
        hints,
        pool,
        noisy,
    )
    write(scenario_dir, placed, bucket, clip_dir, raw, hints)
    return placed


# --- Upload ----------------------------------------------------------------------------------
def _md5_b64(path: Path) -> str:
    return base64.b64encode(hashlib.md5(path.read_bytes()).digest()).decode()


def upload(
    scenario_dirs: list[Path], bucket: str = DEFAULT_BUCKET, workers: int = 8
) -> dict[str, int]:
    """Upload clips + audio_index.json; skips objects whose MD5 already matches (idempotent)."""
    from google.cloud import storage

    client = storage.Client()
    bkt = client.bucket(bucket)
    jobs: list[tuple[Path, str, str]] = []
    for d in scenario_dirs:
        sid = d.name
        existing = {b.name: b.md5_hash for b in client.list_blobs(bucket, prefix=f"audio/{sid}/")}
        idx = json.loads((d / "audio_index.json").read_text())
        mine = [
            (Path(c["local_file"]), c["gs_uri"].split(f"gs://{bucket}/", 1)[1], "audio/wav")
            for c in idx["clips"]
        ]
        mine.append((d / "audio_index.json", f"audio/{sid}/audio_index.json", "application/json"))
        jobs += [j for j in mine if existing.get(j[1]) != _md5_b64(j[0])]

    def one(job: tuple[Path, str, str]) -> None:
        path, name, ctype = job
        blob = bkt.blob(name)
        blob.metadata = {
            "licence": "CC BY-SA 4.0",
            "source": "MIMII (Zenodo 3384388), see data/SOURCES.md",
        }
        blob.upload_from_filename(str(path), content_type=ctype, timeout=600)

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, jobs))
    return {"uploaded": len(jobs)}


# --- CLI -------------------------------------------------------------------------------------
def run(
    root: Path,
    ids: list[str] | None = None,
    raw: Path = DEFAULT_RAW,
    bucket: str = DEFAULT_BUCKET,
    clip_dir: Path = DEFAULT_CLIP_DIR,
    do_upload: bool = False,
) -> dict[str, Any]:
    pool = load_pool(raw)
    dirs = sorted(p for p in root.iterdir() if p.is_dir() and (p / "stop_event.json").exists())
    all_ids = [d.name for d in dirs]
    noisy = noisy_scenarios(all_ids)
    if ids:
        dirs = [d for d in dirs if d.name in set(ids)]
    n_clips = n_abn = n_noisy = 0
    for d in dirs:
        placed = place_scenario(d, pool, d.name in noisy, bucket, clip_dir, raw)
        n_clips += len(placed)
        n_abn += sum(p.src.label == "abnormal" for p in placed)
        n_noisy += sum(p.noisy for p in placed)
    res: dict[str, Any] = {
        "scenarios": len(dirs),
        "clips": n_clips,
        "abnormal": n_abn,
        "noisy_normal": n_noisy,
    }
    if do_upload:
        res.update(upload(dirs, bucket))
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--scenarios", type=Path, default=Path("data/scenarios"))
    ap.add_argument(
        "--ids", default="", help="comma-separated subset (noisy-clip blocks still use all ids)"
    )
    ap.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    ap.add_argument("--clip-dir", type=Path, default=DEFAULT_CLIP_DIR)
    ap.add_argument("--bucket", default=DEFAULT_BUCKET)
    ap.add_argument(
        "--upload", action="store_true", help="upload clips + index to GCS (idempotent)"
    )
    args = ap.parse_args(argv)
    if not (args.raw / "manifest.json").exists():
        print(
            f"no MIMII manifest under {args.raw}; run scripts/fetch_datasets.py --only mimii",
            file=sys.stderr,
        )
        return 2
    ids = [s.strip() for s in args.ids.split(",") if s.strip()] or None
    res = run(args.scenarios, ids, args.raw, args.bucket, args.clip_dir, args.upload)
    print(json.dumps(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
