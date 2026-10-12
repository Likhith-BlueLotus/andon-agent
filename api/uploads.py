"""Bring-your-own-CSV (stretch item 1, ADR-028): upload -> proposed mapping -> human confirm ->
a temporary scenario ``U###`` that agents investigate through the same store path as every other.

* Parsing is bounded (20 MB, 500k rows, 50 columns), uses pyarrow's CSV reader only (no formulas,
  no Excel) and never executes anything from the file.
* The mapping proposal is ONE ``gemini-3.1-flash-lite`` call through ``agents.llm`` that sees column
  names, dtypes, <= 5 samples and min/max/mean per column, never the file. All of that is untrusted
  text: it goes inside an ``<untrusted_data>`` block, and the answer is validated against the plant
  allowlist, so the file cannot widen what the model may select. If the call fails there is a
  name-matching heuristic (confidence <= 0.3). The human always confirms.
* Confirm builds the scenario with ``simulator.load.load_duckdb`` (the real loader, no fork); the
  provenance rows say ``user_upload`` so a user's data can never pass as a real public dataset.
* Storage is per process: at most 5 uploads, 2 h TTL, LRU eviction, directories deleted on eviction,
  never written to GCS or git.
"""

from __future__ import annotations

import atexit
import contextlib
import csv
import difflib
import json
import logging
import math
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.parquet as pq
from google.genai import types
from pydantic import BaseModel, Field

import config
from agents.untrusted import NOTICE, wrap
from simulator import plant
from simulator.load import DuckDBStore, TelemetryStore, load_duckdb

log = logging.getLogger("andon.uploads")

MAX_BYTES = 20 * 1024 * 1024
MAX_ROWS = 500_000
MAX_COLS = 50
MAX_UPLOADS = 5
TTL_S = 2 * 3600.0
PREVIEW_ROWS = 10
MAX_SAMPLES = 5
SOURCE_ID = "user_upload"
UPLOAD_ID_RE = re.compile(r"^U\d{3}$")
PROMPT_FILE = Path(__file__).parent / "prompts" / "upload_mapping.md"
_CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f]+")
_TIME_NAME = re.compile(r"(time|date|stamp|epoch|(^|[^a-z])ts([^a-z]|$))", re.IGNORECASE)


class UploadError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def clean(text: Any, limit: int) -> str:
    """One line of printable text, cut to ``limit`` characters."""
    return _CTRL.sub(" ", str(text)).strip()[:limit]


# ---- allowlist ------------------------------------------------------------------------------
def targets() -> list[dict[str, Any]]:
    return [
        {
            "asset_id": a.asset_id,
            "name": a.name,
            "tags": [
                {
                    "tag": t.tag,
                    "unit": t.unit or None,
                    "normal_lo": t.normal_lo,
                    "normal_hi": t.normal_hi,
                }
                for t in a.tags
            ],
        }
        for a in plant.ASSETS
    ]


def allowlist() -> dict[tuple[str, str], plant.TagSpec]:
    return dict(plant.TAG_SPECS)


# ---- CSV analysis ---------------------------------------------------------------------------
@dataclass
class ColumnInfo:
    name: str
    dtype: str  # number | time | text
    sample: list[str]
    stats: dict[str, float] = field(default_factory=dict)  # min / max / mean (numbers only)


@dataclass
class CsvInfo:
    filename: str
    delimiter: str
    n_rows: int
    columns: list[ColumnInfo]
    preview: list[dict[str, str | None]]


def _sniff(head: str) -> str:
    first = head.split("\n", 1)[0]
    counts = {d: first.count(d) for d in (",", ";", "\t", "|")}
    best = max(counts, key=lambda d: counts[d])
    return best if counts[best] else ","


def _header(path: Path) -> tuple[str, list[str]]:
    with path.open("rb") as fh:
        raw = fh.read(65536)
    if b"\x00" in raw:
        raise UploadError(400, "bad_csv", "this does not look like a text CSV file")
    try:
        head = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            head = raw[:-4].decode("utf-8-sig")  # a multi-byte character cut by the read size
        except UnicodeDecodeError:
            raise UploadError(400, "bad_csv", "the file must be UTF-8 text") from None
    delim = _sniff(head)
    line = head.split("\n", 1)[0].rstrip("\r")
    try:
        names = next(csv.reader([line], delimiter=delim))
    except (csv.Error, StopIteration):
        raise UploadError(400, "bad_csv", "cannot read the header row") from None
    if not line.strip():
        raise UploadError(400, "bad_csv", "the first row must be the column names")
    if len(names) > MAX_COLS:
        raise UploadError(400, "too_many_columns", f"more than {MAX_COLS} columns; trim the export first")  # fmt: skip
    out: list[str] = []
    for i, n in enumerate(names):
        n = clean(n, 80) or f"column_{i + 1}"
        out.append(n)
    if len(set(out)) != len(out):
        raise UploadError(400, "bad_csv", "duplicate column names")
    return delim, out


def _read(path: Path, delim: str, names: list[str], *, include: list[str] | None = None,
          as_string: bool = False) -> pa.Table:  # fmt: skip
    opts = pacsv.ConvertOptions(
        strings_can_be_null=True,
        include_columns=include,
        column_types={n: pa.string() for n in (include or names)} if as_string else None,
    )
    try:
        tbl = pacsv.read_csv(
            path,
            read_options=pacsv.ReadOptions(skip_rows=1, column_names=names, block_size=1 << 22),
            parse_options=pacsv.ParseOptions(delimiter=delim, newlines_in_values=False),
            convert_options=opts,
        )
    except (
        pa.ArrowInvalid,
        pa.ArrowKeyError,
        UnicodeDecodeError,
        pa.ArrowNotImplementedError,
    ) as exc:
        raise UploadError(400, "bad_csv", f"cannot parse the file as CSV: {clean(exc, 120)}") from None  # fmt: skip
    return tbl


def _fmt(v: Any) -> str:
    if isinstance(v, datetime):
        return v.isoformat().replace("+00:00", "Z")
    if isinstance(v, float):
        return f"{v:.6g}"
    return clean(v, 40)


def analyse(path: Path, filename: str) -> CsvInfo:
    delim, names = _header(path)
    tbl = _read(path, delim, names)
    if tbl.num_rows == 0:
        raise UploadError(400, "bad_csv", "the file has a header but no data rows")
    if tbl.num_rows > MAX_ROWS:
        raise UploadError(413, "too_large", f"more than {MAX_ROWS} rows")
    cols: list[ColumnInfo] = []
    for name in names:
        arr = tbl[name]
        t = arr.type
        nonnull = arr.drop_null()
        sample = [_fmt(v) for v in nonnull.slice(0, MAX_SAMPLES).to_pylist()]
        stats: dict[str, float] = {}
        if pa.types.is_integer(t) or pa.types.is_floating(t):
            dtype = "number"
            if len(nonnull):
                mm = pc.min_max(nonnull).as_py()
                mean = pc.mean(nonnull).as_py()
                for k, v in (("min", mm["min"]), ("max", mm["max"]), ("mean", mean)):
                    if v is not None and math.isfinite(float(v)):
                        stats[k] = float(f"{float(v):.6g}")
                if _TIME_NAME.search(name) and stats.get("min", 0) >= 1e8:
                    dtype = "time"  # epoch seconds / milliseconds
        elif pa.types.is_timestamp(t) or pa.types.is_date(t):
            dtype = "time"
        else:
            dtype = "text"
        cols.append(ColumnInfo(name, dtype, sample, stats))
    head = tbl.slice(0, PREVIEW_ROWS)
    preview = [
        {n: (None if row[n] is None else _fmt(row[n])) for n in names} for row in head.to_pylist()
    ]
    return CsvInfo(filename, delim, tbl.num_rows, cols, preview)


# ---- mapping proposal -----------------------------------------------------------------------
class LLMColumn(BaseModel):
    column: str
    asset_id: str | None = None
    tag: str | None = None
    scale: float = 1.0
    confidence: float = 0.0
    reason: str = ""


class LLMMapping(BaseModel):
    timestamp_column: str | None = None
    columns: list[LLMColumn] = Field(default_factory=list)


def _targets_text() -> str:
    lines = ["asset_id | tag | unit | normal range"]
    for (aid, tag), t in plant.TAG_SPECS.items():
        lines.append(f"{aid} | {tag} | {t.unit} | {t.normal_lo} to {t.normal_hi}")
    return "\n".join(lines)


def _describe(info: CsvInfo) -> str:
    cols = []
    for c in info.columns:
        cols.append({"name": clean(c.name, 60), "dtype": c.dtype,
                     "samples": [clean(s, 40) for s in c.sample], **c.stats})  # fmt: skip
    return json.dumps({"n_rows": info.n_rows, "columns": cols}, ensure_ascii=False)


def _norm_scale(x: Any) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 1.0
    return v if math.isfinite(v) and 1e-9 <= abs(v) <= 1e9 else 1.0


def _clamp(x: Any, hi: float = 1.0) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return min(hi, max(0.0, v)) if math.isfinite(v) else 0.0


def validate_proposal(info: CsvInfo, raw: LLMMapping, *, max_conf: float = 1.0) -> dict[str, Any]:
    """Make a model (or heuristic) answer safe to show: only real columns, only allowlisted
    (asset, tag) pairs, each pair at most once, numeric columns only, clamped numbers."""
    allow = allowlist()
    by_name = {c.name: c for c in info.columns}
    ts = raw.timestamp_column if raw.timestamp_column in by_name else None
    if ts is None:
        ts = next((c.name for c in info.columns if c.dtype == "time"), None)
    given = {c.column: c for c in raw.columns if c.column in by_name}
    out: list[dict[str, Any]] = []
    taken: dict[tuple[str, str], int] = {}
    for c in info.columns:
        if c.name == ts:
            continue
        g = given.get(c.name)
        row: dict[str, Any] = {"column": c.name, "asset_id": None, "tag": None, "unit": None,
                               "scale": 1.0, "confidence": 0.0, "reason": "not mapped"}  # fmt: skip
        if g is not None:
            row["reason"] = clean(g.reason, 120) or "no reason given"
            key = (g.asset_id or "", g.tag or "")
            if key in allow and c.dtype == "number":
                row.update(asset_id=key[0], tag=key[1], unit=allow[key].unit or None,
                           scale=_norm_scale(g.scale), confidence=min(max_conf, _clamp(g.confidence)))  # fmt: skip
            elif g.asset_id or g.tag:
                row["reason"] = clean(f"proposal outside the allowed targets ({row['reason']})", 120)  # fmt: skip
        out.append(row)
        if row["tag"] is not None:
            k = (row["asset_id"], row["tag"])
            prev = taken.get(k)
            if prev is None or row["confidence"] > out[prev]["confidence"]:
                if prev is not None:
                    _unmap(out[prev], "duplicate target")
                taken[k] = len(out) - 1
            else:
                _unmap(row, "duplicate target")
    return {"timestamp_column": ts, "columns": out}


def _unmap(row: dict[str, Any], why: str) -> None:
    row.update(asset_id=None, tag=None, unit=None, scale=1.0, confidence=0.0, reason=why)


_SYN = {
    "p": "pressure", "press": "pressure", "prs": "pressure", "psi": "pressure",
    "temp": "temperature", "tmp": "temperature",
    "amps": "current", "amp": "current", "ampere": "current", "i": "current",
    "vib": "vibration", "rms": "vibration", "cyc": "cycle", "ct": "cycle",
    "weld": "weld", "wld": "weld", "air": "air", "hyd": "hydraulic",
}  # fmt: skip
_UNIT_WORDS = {"a", "c", "s", "ka", "bar", "lpm", "mm", "mms", "pct", "mohm", "ccm", "mpm"}


def _tokens(name: str) -> set[str]:
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    raw = [t for t in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if t]
    return set(raw) | {_SYN[t] for t in raw if t in _SYN}


def heuristic(info: CsvInfo) -> dict[str, Any]:
    """Name matching only; confidence <= 0.3. Used when the model call fails."""
    allow = allowlist()
    tag_owners: dict[str, int] = {}
    for _aid, tag in allow:
        tag_owners[tag] = tag_owners.get(tag, 0) + 1
    picks: list[LLMColumn] = []
    for c in info.columns:
        if c.dtype != "number":
            continue
        toks = _tokens(c.name)
        best: tuple[float, str, str] | None = None
        for (aid, tag), _spec in allow.items():
            words = {w for w in tag.split("_") if w not in _UNIT_WORDS}
            if not words:
                continue
            frac = len(words & toks) / len(words)
            station = plant.asset(aid).station.lower()
            asset_hit = station in toks or aid.lower().replace("-", "") in toks
            if frac < 0.5 and not (frac > 0 and asset_hit):
                continue
            if tag_owners[tag] > 1 and not asset_hit:
                continue  # ambiguous: several assets have this tag and the name names none
            score = frac + (0.5 if asset_hit else 0.0)
            if (
                best is None
                or score > best[0]
                or (
                    difflib.SequenceMatcher(None, c.name.lower(), tag).ratio() > 0.9
                    and score >= best[0]
                )
            ):
                best = (score, aid, tag)
        if best is not None:
            picks.append(LLMColumn(column=c.name, asset_id=best[1], tag=best[2],
                                   confidence=min(0.3, 0.1 + 0.1 * best[0]), reason="heuristic"))  # fmt: skip
    prop = validate_proposal(info, LLMMapping(timestamp_column=None, columns=picks), max_conf=0.3)
    for r in prop["columns"]:
        r["reason"] = "heuristic"
    return prop


def _prompt() -> str:
    raw = PROMPT_FILE.read_text(encoding="utf-8")
    return re.sub(r"\A<!--.*?-->\s*", "", raw, flags=re.S).strip()


async def propose(info: CsvInfo, llm: Any) -> tuple[dict[str, Any], float]:
    """(proposal, cost_usd). Never raises: any model failure becomes the heuristic proposal."""
    contents = f"Allowed targets:\n{_targets_text()}\n\n{NOTICE}\nCSV description:\n{wrap(_describe(info))}"
    cfg = types.GenerateContentConfig(
        system_instruction=_prompt(),
        response_mime_type="application/json",
        response_schema=LLMMapping,
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
    )
    try:
        res = await llm.generate(config.FLASH_LITE, contents, cfg, agent="upload.mapping",
                                 timeout_s=30.0)  # fmt: skip
        text = getattr(res.response, "text", None)
        if not text:
            raise ValueError("model returned no text")
        raw = LLMMapping.model_validate_json(text)
        return validate_proposal(info, raw), round(float(res.usage.usd or 0.0), 6)
    except Exception as exc:
        log.warning("upload mapping fell back to the heuristic: %s: %.200s", type(exc).__name__, exc)  # fmt: skip
        return heuristic(info), 0.0


# ---- confirm: build the scenario ------------------------------------------------------------
class ColumnMap(BaseModel):
    column: str = Field(max_length=120)
    asset_id: str = Field(max_length=32)
    tag: str = Field(max_length=64)
    scale: float = 1.0


class ConfirmBody(BaseModel):
    timestamp_column: str = Field(max_length=120)
    columns: list[ColumnMap] = Field(min_length=1, max_length=MAX_COLS)
    stopped_station: str = Field(max_length=32)
    stop_ts: str | None = Field(None, max_length=40)
    stop_text: str = Field("", max_length=200)


def parse_timestamps(raw: pd.Series) -> pd.Series:
    """Strings -> UTC datetimes. ISO 8601 (naive = UTC) or epoch seconds / milliseconds, detected
    from the magnitude. Empty cells give NaT; any other unparseable cell is an error."""
    s = raw.astype("string").str.strip()
    present = s.notna() & (s != "")
    if not present.any():
        raise UploadError(400, "bad_timestamps", "the timestamp column is empty")
    num = pd.to_numeric(s.where(present), errors="coerce")
    if num[present].notna().all():
        med = float(num[present].abs().median())
        if 1e8 <= med < 1e11:
            unit = "s"
        elif 1e11 <= med < 1e14:
            unit = "ms"
        else:
            raise UploadError(400, "bad_timestamps", "numeric timestamps must be epoch seconds or milliseconds")  # fmt: skip
        out = pd.to_datetime(num, unit=unit, utc=True, errors="coerce")
    else:
        try:
            out = pd.to_datetime(s.where(present), utc=True, format="ISO8601", errors="coerce")
        except (ValueError, TypeError):
            raise UploadError(400, "bad_timestamps", "timestamps must be ISO 8601 or epoch seconds/milliseconds") from None  # fmt: skip
    if out[present].isna().any():
        raise UploadError(400, "bad_timestamps", "some timestamps cannot be parsed (use ISO 8601 or epoch seconds/milliseconds)")  # fmt: skip
    ok = out.dropna()
    if ok.dt.year.min() < 2000 or ok.dt.year.max() > 2100:
        raise UploadError(400, "bad_timestamps", "timestamps outside 2000-2100")
    return out


def _parse_stop(v: str) -> datetime:
    try:
        d = datetime.fromisoformat(v.strip().replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        raise UploadError(400, "bad_timestamps", "stop_ts must be ISO 8601") from None
    return d.astimezone(UTC) if d.tzinfo else d.replace(tzinfo=UTC)


def _z(d: Any) -> str:
    return pd.Timestamp(d).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def _empty(schema: pa.Schema) -> pa.Table:
    return schema.empty_table()


TS = pa.timestamp("ms", tz="UTC")
ALARMS = pa.schema([("scenario_id", pa.string()), ("ts", TS), ("line_id", pa.string()),
                    ("station", pa.string()), ("asset_id", pa.string()), ("code", pa.string()),
                    ("severity", pa.string()), ("text", pa.string())])  # fmt: skip
NOTES = pa.schema([("scenario_id", pa.string()), ("note_id", pa.string()), ("ts", TS),
                   ("line_id", pa.string()), ("author_role", pa.string()), ("text", pa.string())])  # fmt: skip
WORK_ORDERS = pa.schema([("wo_id", pa.string()), ("date", TS), ("asset_id", pa.string()),
                         ("symptom", pa.string()), ("action", pa.string()), ("outcome", pa.string()),
                         ("technician_role", pa.string()), ("scenario_id", pa.string()),
                         ("source_id", pa.string())])  # fmt: skip


@dataclass
class Built:
    scenario_id: str
    row: dict[str, Any]
    db: Path
    response: dict[str, Any]


def build_scenario(entry: UploadEntry, body: ConfirmBody, scenario_id: str) -> Built:
    """Validate the mapping and write the scenario through ``simulator.load.load_duckdb``."""
    allow = allowlist()
    names = {c.name for c in entry.info.columns}
    if body.timestamp_column not in names:
        raise UploadError(400, "bad_mapping", "timestamp_column is not a column of the file")
    if body.stopped_station not in plant.SERIES:
        raise UploadError(400, "bad_mapping", "stopped_station must be one of " + ", ".join(plant.SERIES))  # fmt: skip
    seen_t: set[tuple[str, str]] = set()
    seen_c: set[str] = set()
    for m in body.columns:
        if m.column not in names or m.column == body.timestamp_column:
            raise UploadError(400, "bad_mapping", f"column {clean(m.column, 40)!r} cannot be mapped")  # fmt: skip
        if (m.asset_id, m.tag) not in allow:
            raise UploadError(400, "bad_mapping", f"{clean(m.asset_id, 32)}/{clean(m.tag, 40)} is not an allowed target")  # fmt: skip
        if (m.asset_id, m.tag) in seen_t or m.column in seen_c:
            raise UploadError(400, "bad_mapping", "each column and each (asset, tag) may be mapped once")  # fmt: skip
        if not math.isfinite(m.scale) or not 1e-9 <= abs(m.scale) <= 1e9:
            raise UploadError(400, "bad_mapping", "scale must be a finite non-zero number")
        seen_t.add((m.asset_id, m.tag))
        seen_c.add(m.column)
    stop_ts = _parse_stop(body.stop_ts) if body.stop_ts else None

    include = [body.timestamp_column, *[m.column for m in body.columns]]
    tbl = _read(entry.csv, entry.info.delimiter, [c.name for c in entry.info.columns],
                include=include, as_string=True)  # fmt: skip
    df = pd.DataFrame({"row": np.arange(2, tbl.num_rows + 2)})  # file line numbers (header = 1)
    df["ts"] = parse_timestamps(tbl[body.timestamp_column].to_pandas()).to_numpy()
    for m in body.columns:
        df[m.column] = pd.to_numeric(tbl[m.column].to_pandas(), errors="coerce").to_numpy()
    df = df[df["ts"].notna()].sort_values("ts", kind="stable").drop_duplicates("ts", keep="first")
    if len(df) < 2:
        raise UploadError(400, "bad_timestamps", "need at least two rows with distinct timestamps")
    last = pd.Timestamp(df["ts"].iloc[-1])
    stop = pd.Timestamp(stop_ts) if stop_ts else last
    df = df[df["ts"] <= stop]
    if len(df) < 2:
        raise UploadError(400, "bad_timestamps", "stop_ts is before the data (fewer than two rows)")
    t0, t1 = pd.Timestamp(df["ts"].iloc[0]), pd.Timestamp(df["ts"].iloc[-1])

    frames, prov, mapped = [], [], []
    safe_name = clean(entry.info.filename, 80) or "upload.csv"
    for m in body.columns:
        v = df[m.column].to_numpy(dtype=np.float64) * m.scale
        ok = np.isfinite(v)
        if not ok.any():
            raise UploadError(400, "bad_mapping", f"column {clean(m.column, 40)!r} has no numeric values")  # fmt: skip
        sub = df[ok]
        frames.append(pd.DataFrame({"scenario_id": scenario_id, "asset_id": m.asset_id,
                                    "tag": m.tag, "ts": sub["ts"].to_numpy(),
                                    "value": v[ok].astype(np.float32)}))  # fmt: skip
        r0, r1 = int(sub["row"].min()), int(sub["row"].max())
        prov.append({"scenario_id": scenario_id, "asset_id": m.asset_id, "tag": m.tag,
                     "t0": pd.Timestamp(sub["ts"].iloc[0]), "t1": pd.Timestamp(sub["ts"].iloc[-1]),
                     "source_id": SOURCE_ID,
                     "source_ref": f"{safe_name} rows {r0}-{r1}, column {clean(m.column, 60)}",
                     "transform": f"user-mapped column x {m.scale:g}; timestamps as UTC"})  # fmt: skip
        mapped.append({"asset_id": m.asset_id, "tag": m.tag, "column": m.column, "n": int(ok.sum())})  # fmt: skip
    tel = pd.concat(frames, ignore_index=True)
    text = clean(body.stop_text, 200).replace("<", "").replace(">", "") or "stop reported by user upload"  # fmt: skip
    stop_rec = {
        "scenario_id": scenario_id, "line_id": plant.LINE_ID,
        "stopped_station": body.stopped_station,
        "stop_ts": _z(stop), "history_start": _z(t0), "history_end": _z(stop),
        "plant_utc_offset": "+00:00", "shift": "unknown", "product_model": "unknown",
        "stop_code": "USER-REPORTED",
        "stop_text": f"User-reported stop at {body.stopped_station}: {text}",
    }  # fmt: skip

    root = entry.dir / "scenarios"
    sdir = root / scenario_id
    shutil.rmtree(root, ignore_errors=True)
    sdir.mkdir(parents=True)
    tel_schema = pa.schema([("scenario_id", pa.string()), ("asset_id", pa.string()),
                            ("tag", pa.string()), ("ts", TS), ("value", pa.float32())])  # fmt: skip
    pq.write_table(pa.Table.from_pandas(tel, schema=tel_schema, preserve_index=False),
                   sdir / "telemetry.parquet")  # fmt: skip
    pq.write_table(_empty(ALARMS), sdir / "alarms.parquet")
    pq.write_table(_empty(NOTES), sdir / "shift_notes.parquet")
    pq.write_table(_empty(WORK_ORDERS), sdir / "work_orders.parquet")
    prov_schema = pa.schema([("scenario_id", pa.string()), ("asset_id", pa.string()),
                             ("tag", pa.string()), ("t0", TS), ("t1", TS), ("source_id", pa.string()),
                             ("source_ref", pa.string()), ("transform", pa.string())])  # fmt: skip
    pq.write_table(pa.Table.from_pylist(prov, schema=prov_schema), sdir / "provenance.parquet")
    (sdir / "stop_event.json").write_text(json.dumps(stop_rec))
    db = entry.dir / "andon.duckdb"
    for suffix in ("", ".wal"):
        Path(str(db) + suffix).unlink(missing_ok=True)
    load_duckdb(root, db, telemetry="table").close()  # the real loader; table mode = self-contained

    row = {"scenario_id": scenario_id, "line_id": plant.LINE_ID,
           "stopped_station": body.stopped_station, "stop_ts": stop_rec["stop_ts"],
           "sources": [SOURCE_ID]}  # fmt: skip
    resp = {"scenario_id": scenario_id, "line_id": plant.LINE_ID,
            "stopped_station": body.stopped_station, "stop_ts": stop_rec["stop_ts"],
            "n_points": len(tel), "t0": _z(t0), "t1": _z(t1), "mapped": mapped,
            "provenance_source_id": SOURCE_ID}  # fmt: skip
    return Built(scenario_id, row, db, resp)


# ---- registry -------------------------------------------------------------------------------
@dataclass
class UploadEntry:
    upload_id: str
    info: CsvInfo
    dir: Path
    created: float
    last_used: float
    csv: Path = field(init=False)
    scenario_id: str | None = None
    row: dict[str, Any] | None = None
    db: Path | None = None

    def __post_init__(self) -> None:
        self.csv = self.dir / "source.csv"


class UploadRegistry:
    """At most ``max_uploads`` uploads per process, each deleted after ``ttl_s`` or when it is
    the least recently used and a new one needs room. Scenario ids ``U001``... are per process."""

    def __init__(self, base: Path | None = None, *, max_uploads: int = MAX_UPLOADS,
                 ttl_s: float = TTL_S, clock: Callable[[], float] = time.monotonic) -> None:  # fmt: skip
        self._base = base
        self.max_uploads, self.ttl_s, self._clock = max_uploads, ttl_s, clock
        self._items: OrderedDict[str, UploadEntry] = OrderedDict()  # LRU order, oldest first
        self._lock = threading.RLock()
        self._root: Path | None = None
        self._counter = 0
        self.evicted: list[str] = []

    @property
    def root(self) -> Path:
        with self._lock:
            if self._root is None:
                base = self._base or Path(os.environ.get("STORE_CACHE_DIR", config.STORE_CACHE_DIR))
                base.mkdir(parents=True, exist_ok=True)
                self._root = Path(tempfile.mkdtemp(prefix="uploads-", dir=base))
                atexit.register(shutil.rmtree, self._root, True)
            return self._root

    def _drop(self, uid: str) -> None:
        e = self._items.pop(uid, None)
        if e is not None:
            shutil.rmtree(e.dir, ignore_errors=True)
            self.evicted.append(uid)

    def _expire(self) -> None:
        now = self._clock()
        for uid in [u for u, e in self._items.items() if now - e.created > self.ttl_s]:
            self._drop(uid)

    def new_dir(self) -> tuple[str, Path]:
        """Reserve room (evicting the LRU upload if full) and a directory for a new upload."""
        with self._lock:
            self._expire()
            while len(self._items) >= self.max_uploads:
                self._drop(next(iter(self._items)))
            uid = f"up_{uuid.uuid4().hex[:12]}"
            d = self.root / uid
            d.mkdir()
            return uid, d

    def add(self, uid: str, d: Path, info: CsvInfo) -> UploadEntry:
        now = self._clock()
        with self._lock:
            e = UploadEntry(uid, info, d, now, now)
            self._items[uid] = e
            self._expire()
            while len(self._items) > self.max_uploads:
                self._drop(next(iter(self._items)))
            return e

    def discard_dir(self, d: Path) -> None:
        shutil.rmtree(d, ignore_errors=True)

    def get(self, uid: str) -> UploadEntry | None:
        with self._lock:
            self._expire()
            e = self._items.get(uid)
            if e is not None:
                e.last_used = self._clock()
                self._items.move_to_end(uid)
            return e

    def next_scenario_id(self) -> str:
        with self._lock:
            live = {e.scenario_id for e in self._items.values()}
            for _ in range(999):
                self._counter = self._counter % 999 + 1
                sid = f"U{self._counter:03d}"
                if sid not in live:
                    return sid
            raise UploadError(503, "busy", "no free scenario id")

    def confirm(self, uid: str, body: ConfirmBody) -> dict[str, Any]:
        e = self.get(uid)
        if e is None:
            raise UploadError(404, "unknown_upload", "unknown or expired upload")
        with self._lock:  # one build at a time per process: they are CPU/disk heavy
            sid = e.scenario_id or self.next_scenario_id()
            built = build_scenario(e, body, sid)
            e.scenario_id, e.row, e.db = sid, built.row, built.db
        return built.response

    def scenario(self, sid: str) -> UploadEntry | None:
        """The live upload that owns scenario ``sid`` (touches the LRU), else None."""
        if not UPLOAD_ID_RE.match(sid):
            return None
        with self._lock:
            self._expire()
            for uid, e in self._items.items():
                if e.scenario_id == sid and e.db is not None:
                    e.last_used = self._clock()
                    self._items.move_to_end(uid)
                    return e
        return None

    def row(self, sid: str) -> dict[str, Any] | None:
        e = self.scenario(sid)
        return dict(e.row) if e and e.row else None

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def clear(self) -> None:
        with self._lock:
            for uid in list(self._items):
                self._drop(uid)


class UploadOverlayProvider:
    """Wraps the real provider: ``U###`` scenarios open their own DuckDB, the rest pass through.
    ``list_scenarios`` is untouched: uploads are never listed (the UI navigates by id)."""

    def __init__(self, inner: Any, registry: UploadRegistry) -> None:
        self.inner, self.registry = inner, registry

    def list_scenarios(self) -> list[dict[str, Any]]:
        return self.inner.list_scenarios()

    def open(self, scenario_id: str) -> AbstractContextManager[TelemetryStore]:
        e = self.registry.scenario(scenario_id)
        if e is None or e.db is None:
            if UPLOAD_ID_RE.match(scenario_id):
                raise KeyError(f"unknown scenario {scenario_id!r}")
            return self.inner.open(scenario_id)
        return _open_db(e.db)


@contextlib.contextmanager
def _open_db(path: Path) -> Iterator[TelemetryStore]:
    store = DuckDBStore(path)
    try:
        yield store
    finally:
        store.close()
