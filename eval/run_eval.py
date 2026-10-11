"""The eval harness (EVAL_PLAN §6).

    uv run python -m eval.run_eval --systems S1,S2,B1,B2 --sets S,R --concurrency 4 --out eval/results/<id>
    uv run python -m eval.run_eval --systems S1 --subset variance15 --repeats 3 --judge flash --out ...
    uv run python -m eval.run_eval --dry-run --systems S1,S2,S3,B1,B2 --sets dev --out /tmp/dry

* **systems** ``S1,S2,S3,B1,B2``; ``S2@flash`` pins a system's judge; ``--judge flash|pro`` sets the
  default for the graph systems. **sets** ``S``, ``R``, ``dev`` (S001-S020), ``heldout``,
  ``variance15``, ``audio`` or ids/ranges (``S001-S010``).
* **Resumable**: rows are appended to ``results.jsonl`` as they finish; a re-run skips every
  completed (system, scenario, repeat) and retries errored ones (``--no-retry-errors`` to keep them).
* **Cost**: the estimate is printed first and checked against the DEVELOPMENT.md §7 eval ledger;
  above $25 it asks for confirmation (``--yes`` skips). Every Gemini call goes through
  ``agents/llm.py`` (daily kill switch: see ``--daily-budget``); the run stops cleanly when it trips
  and can be resumed.
* **Truth is never given to a system.** It is read once, after the runs, by the grader
  (``eval/report.py``).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import threading
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import config
from eval import baselines, checker, cost, sets
from eval.baselines import RunContext, SystemSpec
from eval.records import load_results

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "eval" / "results"
DEFAULT_DB = ROOT / "data" / "andon.duckdb"
RUN_TIMEOUT_S = 900.0  # one diagnosis; the API's own cap is the same order


# --- results.jsonl -----------------------------------------------------------------------------
def completed_keys(rows: dict[str, dict], retry_errors: bool = True) -> set[str]:
    return {k for k, r in rows.items() if r.get("status") == "ok" or not retry_errors}


def plan_tasks(
    specs: list[SystemSpec], ids: list[str], repeats: int, done: set[str]
) -> list[tuple[SystemSpec, str, int]]:
    """Order: repeat, scenario, system, so that an interrupted run is balanced across systems."""
    from eval.records import run_key

    out = []
    for rep in range(repeats):
        for sid in ids:
            for sp in specs:
                if run_key(sp.name, sid, rep) not in done:
                    out.append((sp, sid, rep))
    return out


# --- environment facts for summary.json --------------------------------------------------------
def git_state() -> dict:
    import subprocess

    def run(*a: str) -> str:
        try:
            return subprocess.run(
                ["git", *a], cwd=ROOT, capture_output=True, text=True, timeout=20, check=False
            ).stdout.strip()
        except Exception:
            return ""

    return {
        "sha": run("rev-parse", "HEAD") or "unknown",
        "dirty": bool(
            run(
                "status",
                "--porcelain",
                "--",
                "agents",
                "eval",
                "config.py",
                "simulator",
                "analytics",
            )
        ),
    }


def prompt_versions() -> dict[str, str]:
    from agents import prompts

    out = {}
    for p in sorted(prompts.PROMPT_DIR.glob("*.md")):
        try:
            out[p.stem] = prompts.version(p.stem)
        except Exception:
            out[p.stem] = "unversioned"
    out["b1"] = baselines.b1_prompt()[0]
    return out


def model_ids(judge: str) -> dict[str, str]:
    return {
        "default_judge": judge,
        "flash": config.FLASH,
        "flash_lite": config.FLASH_LITE,
        "pro_judge": config.PRO_JUDGE,
        "b1": baselines.B1_MODEL,
    }


# --- budget helpers ----------------------------------------------------------------------------
def install_daily_budget(usd: float | None) -> None:
    """Explicit opt-in to a different kill-switch limit for THIS process (never silent)."""
    if usd is None:
        return
    from agents.llm import LLM, SpendTracker, get_llm, set_default_llm

    prev = get_llm()
    set_default_llm(LLM(spend=SpendTracker(daily_budget_usd=usd), credentials=prev.credentials))
    print(
        f"NOTE: daily kill switch for this process set to ${usd:.2f} by --daily-budget "
        f"(config.DAILY_BUDGET_USD is ${config.DAILY_BUDGET_USD:.2f})."
    )


def budget_warning(est_total: float, remaining: float) -> str | None:
    if est_total <= remaining:
        return None
    return (
        f"WARNING: estimated ${est_total:.2f} exceeds today's remaining kill-switch budget "
        f"${remaining:.2f} (DAILY_BUDGET_USD=${config.DAILY_BUDGET_USD:.2f}). The run will stop "
        "cleanly when the switch trips and can be resumed (same --out) after the IST day rolls "
        f"over, or re-run with DAILY_BUDGET_USD>={est_total + 1:.0f} / --daily-budget "
        f"{est_total + 1:.0f} if you accept that spend."
    )


def confirm(prompt: str, input_fn: Any = input) -> bool:
    if not sys.stdin.isatty() and input_fn is input:
        print("No terminal to confirm on; pass --yes to proceed.")
        return False
    return input_fn(f"{prompt} [y/N] ").strip().lower() in ("y", "yes")


# --- the run loop ------------------------------------------------------------------------------
class Runner:
    def __init__(
        self,
        *,
        open_store: Any,
        out: Path,
        concurrency: int,
        mode: str,
        fixture_root: Path | None,
        b1_llm: Any,
        history: Any,
        truth_free_check: bool = True,
        sync: Any = None,
    ) -> None:
        self.open_store, self.out = open_store, out
        self.sem = asyncio.Semaphore(concurrency)
        self.mode, self.fixture_root, self.b1_llm, self.history = (
            mode,
            fixture_root,
            b1_llm,
            history,
        )
        self.write_lock = asyncio.Lock()
        self.stop = asyncio.Event()
        self.n_done = 0
        self.total = 0
        self.spent = 0.0
        self.sync = sync
        self.results_path = out / "results.jsonl"

    async def one(self, spec: SystemSpec, sid: str, rep: int) -> dict | None:
        async with self.sem:
            if self.stop.is_set():
                return None
            lock = threading.RLock()  # one DuckDB connection per run (like the API); tools share it
            cm = self.open_store(sid)
            store = await asyncio.to_thread(cm.__enter__)
            try:
                rc = RunContext(
                    scenario_id=sid,
                    repeat=rep,
                    store=store,
                    lock=lock,
                    mode=self.mode,
                    fixture_root=self.fixture_root,
                    llm=self.b1_llm,
                    history=self.history,
                )
                t0 = time.perf_counter()
                try:
                    row = await asyncio.wait_for(baselines.run_system(spec, rc), RUN_TIMEOUT_S)
                except TimeoutError:
                    from eval.records import error_row

                    row = error_row(
                        system=spec.name,
                        scenario_id=sid,
                        repeat=rep,
                        judge_model=spec.judge_model,
                        mode=self.mode,
                        code="timeout",
                        message=f"no result in {RUN_TIMEOUT_S:.0f} s",
                        wall_s=time.perf_counter() - t0,
                    )
                if row["status"] == "ok" and row.get("report"):
                    row["independent"] = await asyncio.to_thread(
                        checker.check_report,
                        row["report"],
                        row["evidence"],
                        store,
                        sid,
                        lock=lock,
                    )
            finally:
                await asyncio.to_thread(cm.__exit__, None, None, None)
            if row.pop("budget_exhausted", False):
                self.stop.set()  # the kill switch tripped: stop launching runs; rows stay resumable
                row["error"] = {**(row.get("error") or {}), "code": "budget_exhausted"}
            await self.record(row)
            return row

    async def record(self, row: dict) -> None:
        async with self.write_lock:
            with self.results_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            self.n_done += 1
            self.spent += float((row.get("cost") or {}).get("usd") or 0.0)
            top = ((row.get("report") or {}).get("hypotheses") or [{}])[0]
            print(
                f"[{self.n_done}/{self.total}] {row['system']:<9} {row['scenario_id']} r{row['repeat']} "
                f"{row['status']:<5} top={top.get('cause_class', '-')}@{top.get('asset_id', '-')} "
                f"${(row.get('cost') or {}).get('usd', 0):.3f} (run total ${self.spent:.2f})"
                + (f" ERR {row['error'].get('code')}" if row["status"] != "ok" else ""),
                flush=True,
            )
            if self.sync is not None and self.n_done % 10 == 0:
                await asyncio.to_thread(self.sync)

    async def run(self, tasks: list[tuple[SystemSpec, str, int]]) -> list[dict]:
        self.total = len(tasks)
        res = await asyncio.gather(*(self.one(*t) for t in tasks))
        return [r for r in res if r is not None]


# --- CLI ---------------------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m eval.run_eval", description=__doc__.split("\n\n")[0]
    )
    p.add_argument("--systems", default="S1,S2,B1,B2")
    p.add_argument(
        "--sets", default="S,R", help="S, R, dev, heldout, audio, ids or ranges, comma list"
    )
    p.add_argument("--subset", default=None, help="named subset (replaces --sets), e.g. variance15")
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument(
        "--judge",
        choices=["flash", "pro"],
        default=None,
        help="default judge for graph systems (default: config.JUDGE_MODEL)",
    )
    p.add_argument("--out", default=None, help="output dir (default eval/results/<YYYYMMDD_HHMM>)")
    p.add_argument("--yes", action="store_true", help="skip the >$25 confirmation")
    p.add_argument(
        "--dry-run", action="store_true", help="mocked LLMs/fixtures, $0, stamped DRY RUN"
    )
    p.add_argument("--estimate-only", action="store_true")
    p.add_argument("--limit", type=int, default=None, help="first N scenarios only (smoke)")
    p.add_argument("--no-retry-errors", action="store_true")
    p.add_argument(
        "--override-ledger",
        action="store_true",
        help="proceed although the projection passes the §7 hard stop",
    )
    p.add_argument(
        "--daily-budget",
        type=float,
        default=None,
        help="explicitly set THIS process's daily kill switch (USD); default config",
    )
    p.add_argument(
        "--purpose",
        choices=["dev", "final"],
        default=None,
        help="dev = tuning run: refuses held-out and R-set scenarios",
    )
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--scenarios-dir", default=str(sets.DEFAULT_SCENARIOS))
    p.add_argument(
        "--truth-dir", default=None, help="ground-truth dir for the grader (default scenarios-dir)"
    )
    p.add_argument(
        "--sync-to", default=None, help="gs://bucket/prefix: resume from and push results"
    )
    p.add_argument(
        "--store",
        choices=["local", "gcs"],
        default="local",
        help="local DuckDB (--db) or the published GCS store (Cloud Run job)",
    )
    p.add_argument(
        "--data-dir", default=None, help="dir with work_orders(_labels).parquet (B2 history)"
    )
    p.add_argument("--no-report", action="store_true")
    return p


def resolve_plan(args: argparse.Namespace) -> tuple[list[SystemSpec], list[str]]:
    default_judge = baselines.JUDGES[args.judge] if args.judge else config.JUDGE_MODEL
    specs = [baselines.parse_system(t, default_judge) for t in args.systems.split(",") if t.strip()]
    if len({s.name for s in specs}) != len(specs):
        raise ValueError("duplicate system in --systems")
    ids = sets.resolve(args.subset or args.sets, Path(args.scenarios_dir))
    if args.limit:
        ids = ids[: args.limit]
    if not ids:
        raise ValueError("no scenarios selected")
    purpose = args.purpose or ("dev" if all(i in sets.DEV_IDS for i in ids) else "final")
    if args.purpose == "dev":
        bad = [i for i in ids if i in sets.HELDOUT or i.startswith("R")]
        if bad:
            raise ValueError(
                f"--purpose dev refuses held-out/R-set scenarios ({', '.join(bad[:5])} ...): "
                "never tune on S051-S060 or the R-set (EVAL_PLAN §9)"
            )
    args.purpose = purpose
    return specs, ids


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        specs, ids = resolve_plan(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return asyncio.run(_main(args, specs, ids))


async def _main(args: argparse.Namespace, specs: list[SystemSpec], ids: list[str]) -> int:
    from simulator.load import DuckDBStore

    out = Path(args.out) if args.out else RESULTS / datetime.now().strftime("%Y%m%d_%H%M")
    if args.dry_run and not args.out:
        out = RESULTS / ("dry_" + out.name)
    out.mkdir(parents=True, exist_ok=True)
    sync_fn = None
    if args.sync_to:
        from eval import gcs_sync

        try:
            gcs_sync.pull(args.sync_to, out)
        except Exception as exc:
            print(f"note: nothing to resume from {args.sync_to} ({exc})")

        def sync_fn() -> None:
            gcs_sync.push(out, args.sync_to)

    existing = load_results(out / "results.jsonl")
    done = completed_keys(existing, retry_errors=not args.no_retry_errors)
    tasks = plan_tasks(specs, ids, args.repeats, done)
    heldout = sets.heldout_in(ids)
    print(
        f"run {out.name}: systems {[s.name for s in specs]} x {len(ids)} scenarios x "
        f"{args.repeats} repeat(s) = {len(specs) * len(ids) * args.repeats} runs; "
        f"{len(done)} already complete, {len(tasks)} to do. purpose={args.purpose}"
        + (
            f"; held-out in this run: {len(heldout)} (report only, never tune on them)"
            if heldout
            else ""
        )
    )

    store = DuckDBStore(args.db)  # sizing, dry-run fixtures and the grader's helpers only
    opener = store_opener(args)
    try:
        # ---- estimate and checks ----
        b1_chars = _b1_chars(store, ids) if any(s.base == "B1" for s in specs) else None
        per_system_runs = Counter(s.name for s, _, _ in tasks)
        observed = cost.observed_per_run(RESULTS)
        est = cost.estimate(
            [(s, per_system_runs.get(s.name, 0)) for s in specs],
            b1_prompt_chars=b1_chars,
            observed=observed,
            spent_before=cost.ledger_spent(RESULTS, exclude=out),
        )
        print(
            "\n"
            + (
                "LIVE-EQUIVALENT estimate (this is a dry run, nothing will be billed)"
                if args.dry_run
                else "Cost estimate"
            )
            + "\n"
            + est.render()
        )
        verdict = cost.check_ledger(est)
        for m in verdict.messages:
            print(m)
        if args.estimate_only:
            return 0
        if not args.dry_run:
            if not verdict.ok and not args.override_ledger:
                return 3
            install_daily_budget(args.daily_budget)
            from agents.llm import get_spend

            w = budget_warning(est.total, get_spend().remaining())
            if w:
                print(w)
            if (
                verdict.needs_confirmation
                and not args.yes
                and not confirm(
                    f"Estimated ${est.total:.2f} exceeds ${cost.CONFIRM_ABOVE_USD:.0f}. Proceed?"
                )
            ):
                print("aborted; nothing was run.")
                return 1
        if not tasks:
            print("nothing to run; finalising from existing rows.")
        # ---- run ----
        mode, fixture_root, b1_llm = "live", None, None
        if args.dry_run:
            from agents.llm import LLM
            from eval import dryrun

            mode, fixture_root = "replay", out / "dryrun_fixtures"
            ok = dryrun.prepare_fixtures(store, ids, fixture_root)
            print(f"dry run: fixtures resolved for {len(ok)}/{len(ids)} scenarios")
            b1_llm = LLM(transport=dryrun.MockB1Transport())
        history = None
        if any(s.base == "B2" for s in specs):
            history = baselines.HistoryPrior.load(
                Path(args.data_dir or Path(args.scenarios_dir).parent)
            )
        runner = Runner(
            open_store=opener,
            out=out,
            concurrency=args.concurrency,
            mode=mode,
            fixture_root=fixture_root,
            b1_llm=b1_llm,
            history=history,
            sync=sync_fn,
        )
        t0 = time.perf_counter()
        await runner.run(tasks)
        print(
            f"\nfinished {runner.n_done}/{len(tasks)} runs in {time.perf_counter() - t0:.0f} s; "
            f"spent ${runner.spent:.2f}"
        )
        stopped = runner.stop.is_set()
        if stopped:
            print("STOPPED: the daily kill switch tripped. Re-run the same command to resume.")
        meta = {
            "args": {k: v for k, v in vars(args).items()},
            "dry_run": args.dry_run,
            "git": git_state(),
            "models": model_ids(
                config.JUDGE_MODEL if not args.judge else baselines.JUDGES[args.judge]
            ),
            "prompt_versions": prompt_versions(),
            "ids": ids,
            "systems": [s.name for s in specs],
            "purpose": args.purpose,
            "stopped_budget": stopped,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "estimate": est.to_dict(),
            "daily_budget_usd": config.DAILY_BUDGET_USD,
        }
        (out / "run_meta.json").write_text(json.dumps(meta, indent=1, default=str) + "\n", "utf-8")
        if not args.no_report:
            from eval import report

            truth_dir = Path(args.truth_dir or args.scenarios_dir)
            report.build_all(out, truth_dir=truth_dir, slide=True)
            print(f"wrote summary.json, cost.json, calibration.csv, results_slide.png in {out}")
        if sync_fn is not None:
            await asyncio.to_thread(sync_fn)
        return 4 if stopped else 0
    finally:
        store.close()


def store_opener(args: argparse.Namespace) -> Any:
    """``sid -> context manager yielding a TelemetryStore``: one connection per run."""
    if getattr(args, "store", "local") == "gcs":
        from agents import store_cache

        return store_cache.get_store

    @contextlib.contextmanager
    def local(sid: str) -> Any:
        from simulator.load import DuckDBStore

        st = DuckDBStore(args.db)
        try:
            yield st
        finally:
            st.close()

    return local


def _b1_chars(store: Any, ids: list[str]) -> int | None:
    """Prompt size of B1 for the first scenario (the manuals dominate; scenario size is stable)."""
    try:
        ev = baselines.b1_evidence(store, ids[0], threading.RLock())
        return len(baselines.b1_user_prompt(ids[0], ev))
    except Exception as exc:
        print(f"note: could not size the B1 prompt ({exc}); using the EVAL_PLAN price")
        return None


if __name__ == "__main__":
    raise SystemExit(main())
