"""Load generated scenarios into a ``TelemetryStore`` (DuckDB locally, BigQuery in the cloud).

    uv run python -m simulator.load --scenarios data/scenarios --target duckdb      # data/andon.duckdb
    uv run python -m simulator.load --scenarios data/scenarios --target bigquery    # dataset `andon`

What is loaded: telemetry, alarms, shift notes, work orders (historical + per-scenario), provenance,
stop events, the asset list and the spec limits. What is **never** loaded: ``truth.json``,
``sim_meta.json`` and ``work_orders_labels.parquet`` (the store is what agents read).

Both backends implement the same read API with the same parameterised SQL (``@name`` params; the
DuckDB backend rewrites them to ``$name``). Only SQL both engines support is used.

DuckDB telemetry modes: ``view`` (default) reads the per-scenario Parquet files in place via a
view created at connect time (no copy, ~10 MB/scenario on disk); ``table`` copies rows into the
database file (self-contained, larger).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

import config
from simulator import plant

SCENARIO_FILES = ("alarms", "shift_notes", "work_orders", "provenance")
NEVER_LOAD = ("truth.json", "sim_meta.json", "work_orders_labels.parquet")
TABLES = (
    "telemetry",
    "alarms",
    "shift_notes",
    "work_orders",
    "provenance",
    "stop_events",
    "assets",
    "spec_limits",
)
TimeLike = str | datetime


def _ts(t: TimeLike) -> datetime:
    if isinstance(t, datetime):
        return t.astimezone(UTC) if t.tzinfo else t.replace(tzinfo=UTC)
    s = t.strip().replace("Z", "+00:00")
    d = datetime.fromisoformat(s)
    return d.astimezone(UTC) if d.tzinfo else d.replace(tzinfo=UTC)


def scenario_num(scenario_id: str) -> int:
    """Integer partition key: S001 -> 1, R001 -> 1001, U001 -> 2001."""
    base = {"S": 0, "R": 1000, "U": 2000}[scenario_id[0]]
    return base + int(scenario_id[1:])


# --- Interface -------------------------------------------------------------------------------
@runtime_checkable
class TelemetryStore(Protocol):
    """Read API used by the agent tools. All reads are scoped to one scenario."""

    def list_scenarios(self) -> list[str]: ...
    def get_stop_event(self, scenario_id: str) -> dict[str, Any]: ...
    def list_assets(
        self, line_id: str = plant.LINE_ID, upstream_of: str | None = None
    ) -> list[dict[str, Any]]: ...
    def spec_limits(self, asset_id: str | None = None) -> list[dict[str, Any]]: ...
    def query_telemetry(
        self, scenario_id: str, asset_id: str, tags: Sequence[str], t0: TimeLike, t1: TimeLike
    ) -> pd.DataFrame: ...
    def get_alarms(
        self, scenario_id: str, t0: TimeLike, t1: TimeLike, codes: Sequence[str] | None = None,
        asset_ids: Sequence[str] | None = None,
    ) -> pd.DataFrame: ...  # fmt: skip
    def get_shift_notes(self, scenario_id: str, t0: TimeLike, t1: TimeLike) -> pd.DataFrame: ...
    def get_work_orders(
        self, scenario_id: str, asset_id: str, since: TimeLike, limit: int | None = None
    ) -> pd.DataFrame: ...
    def get_provenance(
        self, scenario_id: str, asset_id: str | None = None, tags: Sequence[str] | None = None,
        t0: TimeLike | None = None, t1: TimeLike | None = None,
    ) -> pd.DataFrame: ...  # fmt: skip


# Shared SQL. {t} = table prefix, {in_tags}/{in_codes}/{in_assets} = dialect list membership.
SQL = {
    "scenarios": "SELECT scenario_id FROM {t}stop_events ORDER BY scenario_id",
    "stop_event": "SELECT * FROM {t}stop_events WHERE scenario_id = @sid",
    "assets": "SELECT * FROM {t}assets WHERE line_id = @line ORDER BY position NULLS LAST, asset_id",
    "spec": "SELECT * FROM {t}spec_limits ORDER BY asset_id, tag",
    "telemetry": (
        "SELECT ts, tag, value FROM {t}telemetry WHERE scenario_id = @sid AND asset_id = @asset "
        "AND {in_tags} AND ts >= @t0 AND ts < @t1 ORDER BY tag, ts"
    ),
    "alarms": (
        "SELECT ts, station, asset_id, code, severity, text FROM {t}alarms WHERE scenario_id = @sid "
        "AND ts >= @t0 AND ts < @t1 {codes_clause} {assets_clause} ORDER BY ts, asset_id, code"
    ),
    "notes": (
        "SELECT ts, note_id, author_role, text FROM {t}shift_notes WHERE scenario_id = @sid "
        "AND ts >= @t0 AND ts < @t1 ORDER BY ts, note_id"
    ),
    "work_orders": (
        "SELECT w.wo_id, w.date, w.asset_id, w.symptom, w.action, w.outcome, w.technician_role, w.source_id "
        "FROM {t}work_orders w, {t}stop_events s WHERE s.scenario_id = @sid AND w.asset_id = @asset "
        "AND (w.scenario_id IS NULL OR w.scenario_id = @sid) AND w.date >= @since AND w.date < s.stop_ts "
        "ORDER BY w.date DESC, w.wo_id {limit_clause}"
    ),
    "provenance": (
        "SELECT asset_id, tag, t0, t1, source_id, source_ref, transform FROM {t}provenance "
        "WHERE scenario_id = @sid {asset_clause} {tags_clause} {window_clause} ORDER BY asset_id, tag, t0"
    ),
}


def _clean(v: Any) -> Any:
    """Plain Python values for dict-returning methods (no NaN, ndarray or pandas types)."""
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if hasattr(v, "tolist") and not isinstance(v, str):
        return v.tolist()
    if isinstance(v, float) and v != v:
        return None
    return v


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    return [{k: _clean(v) for k, v in r.items()} for r in df.to_dict("records")]


class _SqlStore:
    """Dialect-neutral read API; subclasses implement ``_q`` and list membership."""

    prefix = ""

    def _q(self, sql: str, params: dict[str, Any]) -> pd.DataFrame:  # pragma: no cover
        raise NotImplementedError

    def _in(self, col: str, param: str) -> str:  # pragma: no cover
        raise NotImplementedError

    def _sql(self, key: str, **fmt: str) -> str:
        return SQL[key].format(t=self.prefix, **fmt)

    def list_scenarios(self) -> list[str]:
        return self._q(self._sql("scenarios"), {})["scenario_id"].tolist()

    def get_stop_event(self, scenario_id: str) -> dict[str, Any]:
        df = self._q(self._sql("stop_event"), {"sid": scenario_id})
        if df.empty:
            raise KeyError(f"unknown scenario {scenario_id!r}")
        return _records(df)[0]

    def list_assets(
        self, line_id: str = plant.LINE_ID, upstream_of: str | None = None
    ) -> list[dict[str, Any]]:
        rows = _records(self._q(self._sql("assets"), {"line": line_id}))
        for r in rows:
            if r.get("position") is not None:
                r["position"] = int(r["position"])
        if upstream_of is None:
            return rows
        ups = plant.upstream_of(upstream_of)
        order = {a: i for i, a in enumerate(ups)}
        return sorted(
            (r for r in rows if r["asset_id"] in order), key=lambda r: order[r["asset_id"]]
        )

    def spec_limits(self, asset_id: str | None = None) -> list[dict[str, Any]]:
        rows = _records(self._q(self._sql("spec"), {}))
        return [r for r in rows if asset_id is None or r["asset_id"] == asset_id]

    def query_telemetry(
        self, scenario_id: str, asset_id: str, tags: Sequence[str], t0: TimeLike, t1: TimeLike
    ) -> pd.DataFrame:
        sql = self._sql("telemetry", in_tags=self._in("tag", "tags"))
        return self._q(
            sql,
            {
                "sid": scenario_id,
                "asset": asset_id,
                "tags": list(tags),
                "t0": _ts(t0),
                "t1": _ts(t1),
            },
        )

    def get_alarms(
        self, scenario_id: str, t0: TimeLike, t1: TimeLike, codes: Sequence[str] | None = None,
        asset_ids: Sequence[str] | None = None,
    ) -> pd.DataFrame:  # fmt: skip
        params: dict[str, Any] = {"sid": scenario_id, "t0": _ts(t0), "t1": _ts(t1)}
        cc = ac = ""
        if codes:
            cc, params["codes"] = "AND " + self._in("code", "codes"), list(codes)
        if asset_ids:
            ac, params["assets"] = "AND " + self._in("asset_id", "assets"), list(asset_ids)
        return self._q(self._sql("alarms", codes_clause=cc, assets_clause=ac), params)

    def get_shift_notes(self, scenario_id: str, t0: TimeLike, t1: TimeLike) -> pd.DataFrame:
        return self._q(self._sql("notes"), {"sid": scenario_id, "t0": _ts(t0), "t1": _ts(t1)})

    def get_work_orders(
        self, scenario_id: str, asset_id: str, since: TimeLike, limit: int | None = None
    ) -> pd.DataFrame:
        lc = ""
        params: dict[str, Any] = {"sid": scenario_id, "asset": asset_id, "since": _ts(since)}
        if limit is not None:
            lc, params["lim"] = "LIMIT @lim", int(limit)
        return self._q(self._sql("work_orders", limit_clause=lc), params)

    def get_provenance(
        self, scenario_id: str, asset_id: str | None = None, tags: Sequence[str] | None = None,
        t0: TimeLike | None = None, t1: TimeLike | None = None,
    ) -> pd.DataFrame:  # fmt: skip
        params: dict[str, Any] = {"sid": scenario_id}
        a = tg = w = ""
        if asset_id is not None:
            a, params["asset"] = "AND asset_id = @asset", asset_id
        if tags:
            tg, params["tags"] = "AND " + self._in("tag", "tags"), list(tags)
        if t0 is not None and t1 is not None:
            w = "AND t1 > @w0 AND t0 < @w1"
            params["w0"], params["w1"] = _ts(t0), _ts(t1)
        return self._q(
            self._sql("provenance", asset_clause=a, tags_clause=tg, window_clause=w), params
        )


# --- DuckDB ----------------------------------------------------------------------------------
class DuckDBStore(_SqlStore):
    def __init__(self, path: str | Path = "data/andon.duckdb", read_only: bool = True) -> None:
        import duckdb

        self.path = Path(path)
        self.con = duckdb.connect(str(self.path), read_only=read_only)
        self.con.execute("SET TimeZone = 'UTC'")
        self._attach_telemetry()

    def _attach_telemetry(self) -> None:
        try:
            meta = dict(self.con.execute("SELECT key, value FROM _meta").fetchall())
        except Exception:
            return
        if meta.get("telemetry_mode") == "view":
            root = (self.path.parent / meta["telemetry_root"]).resolve()
            glob = str(root / "*" / "telemetry.parquet").replace("'", "''")
            self.con.execute(
                f"CREATE OR REPLACE TEMP VIEW telemetry AS SELECT * FROM read_parquet('{glob}')"
            )

    def _in(self, col: str, param: str) -> str:
        return f"list_contains(@{param}, {col})"

    def _q(self, sql: str, params: dict[str, Any]) -> pd.DataFrame:
        sql = re.sub(r"@(\w+)", r"$\1", sql)
        used = set(re.findall(r"\$(\w+)", sql))
        return self.con.execute(sql, {k: v for k, v in params.items() if k in used}).df()

    def close(self) -> None:
        self.con.close()


# --- BigQuery --------------------------------------------------------------------------------
class BigQueryStore(_SqlStore):
    """Same API on BigQuery. Every query is parameterised and capped by ``maximum_bytes_billed``."""

    MAX_BYTES_BILLED = 2 * 1024**3

    def __init__(
        self, project: str | None = None, dataset: str = config.BQ_DATASET, client: Any = None
    ) -> None:
        if client is None:
            from google.cloud import bigquery

            client = bigquery.Client(
                project=project or config.PROJECT or None, location=config.APP_REGION
            )
        self.client = client
        self.project = project or client.project
        self.dataset = dataset
        self.prefix = f"`{self.project}.{dataset}`."

    def _in(self, col: str, param: str) -> str:
        return f"{col} IN UNNEST(@{param})"

    @staticmethod
    def _param(name: str, v: Any) -> Any:
        from google.cloud import bigquery as bq

        if isinstance(v, list):
            return bq.ArrayQueryParameter(name, "STRING", v)
        if isinstance(v, datetime):
            return bq.ScalarQueryParameter(name, "TIMESTAMP", v)
        if isinstance(v, bool):
            return bq.ScalarQueryParameter(name, "BOOL", v)
        if isinstance(v, int):
            return bq.ScalarQueryParameter(name, "INT64", v)
        if isinstance(v, float):
            return bq.ScalarQueryParameter(name, "FLOAT64", v)
        return bq.ScalarQueryParameter(name, "STRING", v)

    def _q(self, sql: str, params: dict[str, Any]) -> pd.DataFrame:
        from google.cloud import bigquery as bq

        used = set(re.findall(r"@(\w+)", sql))
        cfg = bq.QueryJobConfig(
            query_parameters=[self._param(k, v) for k, v in params.items() if k in used],
            maximum_bytes_billed=self.MAX_BYTES_BILLED,
        )
        rows = self.client.query(sql, job_config=cfg).result()
        return pd.DataFrame([dict(r.items()) for r in rows], columns=[f.name for f in rows.schema])


# --- Loading ---------------------------------------------------------------------------------
def scenario_dirs(root: Path) -> list[Path]:
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / "stop_event.json").exists())


def _stop_events(dirs: Iterable[Path]) -> pa.Table:
    recs = [json.loads((d / "stop_event.json").read_text()) for d in dirs]
    for r in recs:
        for k in ("stop_ts", "history_start", "history_end"):
            r[k] = _ts(r[k])
    return pa.Table.from_pylist(recs).cast(
        pa.schema(
            [
                (
                    f.name,
                    pa.timestamp("s", tz="UTC")
                    if f.name in ("stop_ts", "history_start", "history_end")
                    else f.type,
                )
                for f in pa.Table.from_pylist(recs).schema
            ]
        )
    )


def _concat(dirs: Iterable[Path], name: str) -> pa.Table:
    tables = [
        pq.read_table(d / f"{name}.parquet") for d in dirs if (d / f"{name}.parquet").exists()
    ]
    return pa.concat_tables(tables, promote_options="default") if tables else pa.table({})


def _static_tables() -> dict[str, pa.Table]:
    return {
        "assets": pa.Table.from_pylist(plant.assets_table()),
        "spec_limits": pa.Table.from_pylist(plant.spec_limits()),
    }


def gather(root: Path, data_dir: Path) -> dict[str, pa.Table]:
    dirs = scenario_dirs(root)
    if not dirs:
        raise FileNotFoundError(f"no scenarios under {root}")
    out = {name: _concat(dirs, name) for name in SCENARIO_FILES}
    hist = data_dir / "work_orders.parquet"
    if hist.exists():
        out["work_orders"] = pa.concat_tables(
            [pq.read_table(hist), out["work_orders"]], promote_options="default"
        )
    out["stop_events"] = _stop_events(dirs)
    out.update(_static_tables())
    return out


def load_duckdb(root: Path, db: Path, telemetry: Literal["view", "table"] = "view") -> DuckDBStore:
    import duckdb

    data_dir = root.parent
    tables = gather(root, data_dir)
    tmp = db.with_suffix(".tmp.duckdb")
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    con.execute("SET TimeZone = 'UTC'")
    for name, tbl in tables.items():
        con.register("_src", tbl)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM _src")
        con.unregister("_src")
    rel_root = Path(_relpath(root.resolve(), db.resolve().parent))
    if telemetry == "table":
        for d in scenario_dirs(root):
            f = str(d / "telemetry.parquet").replace("'", "''")
            exists = con.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name='telemetry'"
            ).fetchone()
            verb = "INSERT INTO telemetry" if exists and exists[0] else "CREATE TABLE telemetry AS"
            con.execute(f"{verb} SELECT scenario_id::VARCHAR AS scenario_id, asset_id::VARCHAR AS asset_id, "
                        f"tag::VARCHAR AS tag, ts, value FROM read_parquet('{f}')")  # fmt: skip
    con.execute("CREATE TABLE _meta (key VARCHAR, value VARCHAR)")
    con.execute(
        "INSERT INTO _meta VALUES ('telemetry_mode', $m), ('telemetry_root', $r), ('loaded_at', $t), ('sim', $s)",
        {
            "m": telemetry,
            "r": str(rel_root),
            "t": datetime.now(UTC).isoformat(timespec="seconds"),
            "s": "andon",
        },
    )
    con.close()
    db.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", ".wal"):
        Path(str(db) + suffix).unlink(missing_ok=True)
    tmp.rename(db)
    return DuckDBStore(db)


def _relpath(target: Path, start: Path) -> str:
    import os

    return os.path.relpath(target, start)


def load_bigquery(root: Path, project: str | None = None, dataset: str = config.BQ_DATASET) -> None:
    """Load into BigQuery. Telemetry is integer-range partitioned on ``scenario_num`` and clustered
    by (scenario_id, asset_id, tag); each scenario replaces only its own partition, so reloads
    are idempotent. Small tables are replaced wholesale and clustered by scenario_id."""
    import tempfile

    from google.cloud import bigquery as bq

    client = bq.Client(project=project or config.PROJECT or None, location=config.APP_REGION)
    ds_id = f"{client.project}.{dataset}"
    ds = bq.Dataset(ds_id)
    ds.location = config.APP_REGION
    client.create_dataset(ds, exists_ok=True)
    pq_opts = bq.ParquetOptions()
    pq_opts.enable_list_inference = True

    tel_id = f"{ds_id}.telemetry"
    schema = [
        bq.SchemaField("scenario_id", "STRING", "REQUIRED"), bq.SchemaField("asset_id", "STRING", "REQUIRED"),
        bq.SchemaField("tag", "STRING", "REQUIRED"), bq.SchemaField("ts", "TIMESTAMP", "REQUIRED"),
        bq.SchemaField("value", "FLOAT64"), bq.SchemaField("scenario_num", "INT64", "REQUIRED"),
    ]  # fmt: skip
    tel = bq.Table(tel_id, schema=schema)
    tel.range_partitioning = bq.RangePartitioning(
        field="scenario_num", range_=bq.PartitionRange(0, 4000, 1)
    )
    tel.clustering_fields = ["scenario_id", "asset_id", "tag"]
    client.create_table(tel, exists_ok=True)

    with tempfile.TemporaryDirectory() as tmpd:
        for d in scenario_dirs(root):
            sid = d.name
            t = pq.read_table(d / "telemetry.parquet")
            t = pa.table({
                "scenario_id": t["scenario_id"].cast(pa.string()), "asset_id": t["asset_id"].cast(pa.string()),
                "tag": t["tag"].cast(pa.string()), "ts": t["ts"], "value": t["value"].cast(pa.float64()),
                "scenario_num": pa.array([scenario_num(sid)] * t.num_rows, pa.int64()),
            })  # fmt: skip
            f = Path(tmpd) / f"{sid}.parquet"
            pq.write_table(t, f, compression="zstd")
            job_cfg = bq.LoadJobConfig(
                source_format=bq.SourceFormat.PARQUET, write_disposition=bq.WriteDisposition.WRITE_TRUNCATE,
                schema=schema,
            )  # fmt: skip
            with f.open("rb") as fh:
                client.load_table_from_file(
                    fh, f"{tel_id}${scenario_num(sid)}", job_config=job_cfg
                ).result()
            f.unlink()
            print(f"  bigquery telemetry {sid}: {t.num_rows:,} rows", flush=True)

        for name, tbl in gather(root, root.parent).items():
            f = Path(tmpd) / f"{name}.parquet"
            pq.write_table(tbl, f)
            job_cfg = bq.LoadJobConfig(
                source_format=bq.SourceFormat.PARQUET,
                write_disposition=bq.WriteDisposition.WRITE_TRUNCATE,
                parquet_options=pq_opts,
            )
            if "scenario_id" in tbl.column_names:
                job_cfg.clustering_fields = ["scenario_id"]
            with f.open("rb") as fh:
                client.load_table_from_file(fh, f"{ds_id}.{name}", job_config=job_cfg).result()
            print(f"  bigquery {name}: {tbl.num_rows:,} rows", flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--scenarios", type=Path, default=Path("data/scenarios"))
    ap.add_argument("--target", choices=["duckdb", "bigquery"], default="duckdb")
    ap.add_argument("--db", type=Path, default=Path("data/andon.duckdb"))
    ap.add_argument("--telemetry", choices=["view", "table"], default="view")
    ap.add_argument("--project", default=None)
    ap.add_argument("--dataset", default=config.BQ_DATASET)
    args = ap.parse_args(argv)
    t0 = time.time()
    if args.target == "duckdb":
        store = load_duckdb(args.scenarios, args.db, args.telemetry)
        n = len(store.list_scenarios())
        store.close()
        print(
            f"duckdb: {n} scenarios -> {args.db} ({args.db.stat().st_size / 1e6:.1f} MB, telemetry={args.telemetry})"
        )
    else:
        load_bigquery(args.scenarios, args.project, args.dataset)
        print(f"bigquery: loaded into {args.dataset}")
    print(f"done in {time.time() - t0:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
