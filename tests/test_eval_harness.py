"""Eval harness: sets, cost/ledger, systems (S2 stub, B1 mock, B2), independent checker, resume,
dry-run end to end, report outputs, frontend payload shape, guards. Offline, no Gemini."""

from __future__ import annotations

import ast
import asyncio
import json
import threading
from pathlib import Path

import pandas as pd
import pytest

import config
from agents import tools as T
from agents.llm import LLM
from eval import baselines, checker, cost, dryrun, gcs_sync, records, report, run_eval, sets
from tests.llm_replay import build_store

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    root = tmp_path_factory.mktemp("evalenv")
    store = build_store(root, "S801")
    # labels for B2's history: every background work order labelled with a fault class
    wo = pd.read_parquet(root / "work_orders.parquet")
    lab = pd.DataFrame({"wo_id": wo.wo_id, "cause_class": "sensor_drift"})
    lab.to_parquet(root / "work_orders_labels.parquet")
    yield root, store
    store.close()


# --- sets ----------------------------------------------------------------------------------------
def test_named_sets_and_ranges():
    assert len(sets.S_IDS) == 60 and len(sets.R_IDS) == 17
    assert sets.resolve("dev") == [f"S{i:03d}" for i in range(1, 21)]
    assert sets.resolve("heldout")[0] == "S051" and len(sets.resolve("heldout")) == 10
    assert sets.resolve("S001-S003,R002") == ["S001", "S002", "S003", "R002"]
    v = sets.resolve("variance15")
    assert len(v) == 15 and v[:3] == ["S001", "S006", "S011"] and v[-3:] == ["R002", "R010", "R016"]
    assert sets.resolve("S,R") == sets.S_IDS + sets.R_IDS
    with pytest.raises(ValueError):
        sets.resolve("nonsense")


def test_set_of_never_pools():
    assert sets.set_of("S010") == "S" and sets.set_of("R010") == "R"
    assert sets.set_of("C010") == "C"


def test_confirmation_set_is_registered_and_never_tunable():
    assert sets.resolve("C") == [f"C{i:03d}" for i in range(1, 11)] == sets.C_IDS
    assert sets.resolve("C002-C004") == ["C002", "C003", "C004"]
    assert not set(sets.C_IDS) & set(sets.S_IDS + sets.R_IDS)
    for spec in ("C", "C003", "dev,C001"):
        args = run_eval.build_parser().parse_args(["--sets", spec, "--purpose", "dev"])
        with pytest.raises(ValueError, match="never tune"):
            run_eval.resolve_plan(args)
    auto = run_eval.build_parser().parse_args(["--sets", "C"])
    run_eval.resolve_plan(auto)
    assert auto.purpose == "final"
    assert "C" in report.SET_TITLE


def test_dev_purpose_refuses_heldout_and_r(tmp_path):
    args = run_eval.build_parser().parse_args(["--sets", "S,R", "--purpose", "dev"])
    with pytest.raises(ValueError, match="never tune"):
        run_eval.resolve_plan(args)
    args = run_eval.build_parser().parse_args(["--sets", "dev", "--purpose", "dev"])
    run_eval.resolve_plan(args)
    auto = run_eval.build_parser().parse_args(["--sets", "S,R"])
    run_eval.resolve_plan(auto)
    assert auto.purpose == "final"


# --- systems and cost ----------------------------------------------------------------------------
def test_parse_system_pins_judge():
    s = baselines.parse_system("S2@flash", config.PRO_JUDGE)
    assert s.base == "S2" and s.judge_model == config.FLASH and s.name == "S2@flash"
    assert baselines.parse_system("S1", config.PRO_JUDGE).judge_model == config.PRO_JUDGE
    assert baselines.parse_system("B1", config.FLASH).judge_model is None
    with pytest.raises(ValueError):
        baselines.parse_system("B2@pro", config.FLASH)
    with pytest.raises(ValueError):
        baselines.parse_system("S9", config.FLASH)


def test_cost_estimate_and_ledger():
    pro = baselines.parse_system("S1", config.PRO_JUDGE)
    est = cost.estimate([(pro, 77), (baselines.parse_system("B2", config.FLASH), 77)])
    assert est.total == pytest.approx(77 * 0.56)
    assert cost.check_ledger(est).needs_confirmation  # > $25
    small = cost.estimate([(baselines.parse_system("S1", config.FLASH), 10)])
    assert not cost.check_ledger(small).needs_confirmation
    huge = cost.estimate([(pro, 100)], spent_before=100.0)
    v = cost.check_ledger(huge)
    assert not v.ok and "hard" in v.messages[0]


def test_cost_uses_observed_average_after_enough_runs():
    s1 = baselines.parse_system("S1", config.FLASH)
    est = cost.estimate([(s1, 10)], observed={"S1": (20, 4.0)})
    assert est.lines[0].per_run == pytest.approx(0.2) and "observed" in est.lines[0].basis


def test_budget_warning_mentions_env():
    assert run_eval.budget_warning(5, 8) is None
    assert "DAILY_BUDGET_USD" in run_eval.budget_warning(40, 8)


def test_b2_report_pure():
    prior = baselines.HistoryPrior()
    prior.counts = {"weld_controller": __import__("collections").Counter(
        {"weld_tip_wear": 5, "sensor_drift": 7, "servo_overheat": 2})}  # fmt: skip
    scores = {"ST10-PRS": 0.2, "ST20-WLD": 0.9, "ST30-WLD": 0.9, "UT-AIR": None}
    r = baselines.b2_report(scores, prior, "x", "ST20-WLD")
    assert r.hypotheses[0].asset_id == "ST20-WLD"  # tie -> alphabetical
    assert [h.cause_class.value for h in r.hypotheses] == [
        "sensor_drift",
        "weld_tip_wear",
        "servo_overheat",
    ]
    low = baselines.b2_report({"ST10-PRS": 0.2}, prior, "x", "ST20-WLD")
    assert low.hypotheses[0].cause_class.value == "no_fault"
    none = baselines.b2_report({"UT-AIR": None}, prior, "x", "ST20-WLD")
    assert none.status == "insufficient_evidence" and not none.hypotheses


def _rc(env, **kw):
    _root, store = env
    return baselines.RunContext(
        scenario_id="S801", repeat=0, store=store, lock=threading.RLock(), **kw
    )


def test_b1_with_mock_llm_and_independent_check(env):
    llm = LLM(transport=dryrun.MockB1Transport())
    spec = baselines.parse_system("B1", config.FLASH)
    row = asyncio.run(baselines.run_b1(spec, _rc(env, llm=llm)))
    assert row["status"] == "ok" and row["evidence"] and row["b1_prompt_version"].startswith("b1 v")
    assert row["cost"]["usd"] > 0 and row["duration_s"] is not None
    tools_used = {e["tool"] for e in row["evidence"]}
    assert tools_used <= set(T.TOOL_REGISTRY) - {"listen"}  # only read-only agent tools
    assert not any(T.TOOL_REGISTRY[t].read_only is False for t in tools_used)
    out = checker.check_report(row["report"], row["evidence"], env[1], "S801")
    assert out["error"] is None and out["n_claims"] == len(out["claims"]) > 0
    # the qualitative claim without evidence is unverifiable -> counted as unsupported
    q = next(c for c in out["claims"] if c["kind"] == "qualitative")
    assert q["verdict"] == "unverifiable"


def test_checker_catches_inflated_number_and_unknown_evidence(env):
    ev = baselines.b1_evidence(env[1], "S801", threading.RLock())
    a = next(
        e for e in ev if e["tool"] == "anomaly_score" and e["summary"].get("score") is not None
    )
    good = a["summary"]["score"]

    def claim(cid, val, eid):
        return {"claim_id": cid, "kind": "numeric", "evidence_ids": [eid], "asserted_value": val,
                "text": f"score {val} path: score"}  # fmt: skip

    rep = {"incident_id": "x", "status": "verified", "hypotheses": [{
        "cause_class": "air_pressure_drop", "asset_id": "UT-AIR", "confidence": 0.7,
        "causal_chain": ["UT-AIR"], "refuting_evidence_ids": [], "claims": [
            claim("c1", good, a["evidence_id"]),
            claim("c2", round(good * 3 + 1, 3), a["evidence_id"]),
            claim("c3", good, "ev_anomaly_score_999"),
        ]}]}  # fmt: skip
    out = checker.check_report(rep, ev, env[1], "S801")
    assert [c["verdict"] for c in out["claims"]] == ["pass", "fail", "fail"]
    # a tampered recorded summary is not reproducible
    ev2 = json.loads(json.dumps(ev))
    for e in ev2:
        if e["evidence_id"] == a["evidence_id"]:
            e["summary"]["score"] = 0.123
    out2 = checker.check_report(rep, ev2, env[1], "S801")
    assert out2["claims"][0]["verdict"] == "fail"


def test_checker_never_spends():
    with pytest.raises(Exception, match="budget"):
        asyncio.run(checker.no_spend_llm().generate(config.FLASH, "hi"))


def test_checker_error_is_reported_not_swallowed(env):
    out = checker.check_report({"not": "a report"}, [], env[1], "S801")
    assert out["error"] and out["n_claims"] == 0


def test_b2_runs_without_llm(env):
    prior = baselines.HistoryPrior.load(env[0])
    row = asyncio.run(
        baselines.run_b2(baselines.parse_system("B2", config.FLASH), _rc(env, history=prior))
    )
    assert row["status"] == "ok" and row["cost"]["usd"] == 0 and row["b2_scores"]


def test_always_pass_stub_matches_verifier_contract():
    from agents.graph import VERIFIER

    stub = baselines.always_pass_verifier(None)
    assert stub.name == VERIFIER


# --- fold / resume / gcs -------------------------------------------------------------------------
def test_resume_skips_completed_and_retries_errors(tmp_path):
    specs = [baselines.parse_system(t, config.FLASH) for t in ("S1", "B2")]
    ids = ["S001", "S002"]
    p = tmp_path / "results.jsonl"
    ok = {"run_key": "S1|S001|0", "status": "ok"}
    err = {"run_key": "B2|S001|0", "status": "error"}
    p.write_text(json.dumps(ok) + "\n" + json.dumps(err) + "\n{torn")
    rows = records.load_results(p)
    done = run_eval.completed_keys(rows)
    assert done == {"S1|S001|0"}
    tasks = run_eval.plan_tasks(specs, ids, 1, done)
    assert [(s.name, i) for s, i, _ in tasks] == [("B2", "S001"), ("S1", "S002"), ("B2", "S002")]
    assert run_eval.completed_keys(rows, retry_errors=False) == {"S1|S001|0", "B2|S001|0"}
    assert len(run_eval.plan_tasks(specs, ids, 3, set())) == 12


def test_gcs_sync_with_fake_client(tmp_path):
    class Blob:
        def __init__(self, name, store):
            self.name, self._s = name, store

        def download_to_filename(self, p):
            Path(p).write_text(self._s[self.name])

        def upload_from_filename(self, p):
            self._s[self.name] = Path(p).read_text()

    class Bucket:
        def __init__(self, s):
            self.s = s

        def blob(self, n):
            return Blob(n, self.s)

    class Client:
        def __init__(self):
            self.s = {"runs/x/results.jsonl": "a", "runs/x/../evil": "b"}

        def bucket(self, _):
            return Bucket(self.s)

        def list_blobs(self, _, prefix):
            return [Blob(n, self.s) for n in list(self.s) if n.startswith(prefix)]

    c = Client()
    assert gcs_sync.pull("gs://b/runs/x", tmp_path, c) == 1
    assert (tmp_path / "results.jsonl").read_text() == "a"
    (tmp_path / "new.txt").write_text("z")
    gcs_sync.push(tmp_path, "gs://b/out", names=["new.txt"], client=c)
    assert c.s["out/new.txt"] == "z"


# --- dry run end to end + report -----------------------------------------------------------------
@pytest.fixture(scope="module")
def dry(env, tmp_path_factory):
    root, _ = env
    out = tmp_path_factory.mktemp("dry") / "run"
    rc = run_eval.main([
        "--dry-run", "--systems", "S1,S2,S3,B1,B2", "--sets", "S801", "--out", str(out),
        "--db", str(root / "andon.duckdb"), "--scenarios-dir", str(root / "scenarios"),
        "--data-dir", str(root), "--concurrency", "2",
    ])  # fmt: skip
    return rc, out


def test_dry_run_writes_all_outputs(dry):
    rc, out = dry
    assert rc == 0
    for f in ("results.jsonl", "summary.json", "cost.json", "calibration.csv", "results_slide.png",
              "results_table.md", "latest.json", "run_meta.json"):  # fmt: skip
        assert (out / f).exists(), f
    s = json.loads((out / "summary.json").read_text())
    assert s["dry_run"] is True and s["git"]["sha"] and s["prompt_versions"]["b1"]
    assert s["models"]["pro_judge"] == config.PRO_JUDGE
    assert set(s["sets"]["S"]) == {"S1", "S2", "S3", "B1", "B2"} and "R" not in s["sets"]
    assert s["sets"]["S"]["S1"]["top1"]["n"] == 1
    assert json.loads((out / "cost.json").read_text())["dry_run"] is True
    assert (out / "results_slide.png").stat().st_size > 20_000


def test_dry_run_rows_have_independent_checks_and_no_truth(dry):
    _, out = dry
    rows = [json.loads(line) for line in (out / "results.jsonl").read_text().splitlines()]
    assert len(rows) == 5
    for r in rows:
        assert "truth" not in json.dumps(r).lower().replace("truth_", "")  # nothing graded inside
        if r["system"] in ("S1", "S2", "S3", "B1") and r["status"] == "ok":
            assert "independent" in r
    s2 = next(r for r in rows if r["system"] == "S2")
    assert s2["verifier"]["iterations"] == 1  # always-PASS: no repair loop


def test_resume_is_a_noop(env, dry):
    root, _ = env
    _, out = dry
    before = (out / "results.jsonl").read_text()
    run_eval.main([
        "--dry-run", "--systems", "S1,S2,S3,B1,B2", "--sets", "S801", "--out", str(out),
        "--db", str(root / "andon.duckdb"), "--scenarios-dir", str(root / "scenarios"),
        "--data-dir", str(root), "--no-report",
    ])  # fmt: skip
    assert (out / "results.jsonl").read_text() == before


def test_latest_json_matches_frontend_reader(dry):
    _, out = dry
    p = json.loads((out / "latest.json").read_text())
    assert p["dry_run"] is True and set(p["sets"]) == {"S"}
    for r in p["sets"]["S"]:
        assert isinstance(r["system"], str) and isinstance(r["n"], int)
        for k, v in r.items():
            if k in ("system", "n"):
                continue
            ok = (
                v is None
                or isinstance(v, int | float)
                or (isinstance(v, dict) and {"value", "lo", "hi"} <= set(v))
            )
            assert ok, (k, v)
    # tests live outside `sets` so the reader does not render them as a table
    assert "tests" in p and "tests" not in p["sets"]


def test_publish_refuses_dry_run(dry, tmp_path):
    _, out = dry
    with pytest.raises(SystemExit):
        report.publish(out, tmp_path / "latest.json")


# --- guards --------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", ["baselines", "checker", "run_eval", "dryrun", "records", "cost"])
def test_systems_and_run_loop_never_touch_truth(name):
    """Truth is read only by eval/sets.py (loader) and eval/report.py (grader)."""
    src = (ROOT / "eval" / f"{name}.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module] + [a.name for a in node.names]
        elif isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        for n in names:
            assert "truth_schema" not in n and n != "load_truth", (name, n)
    assert "truth.json" not in src and "GroundTruth" not in src


def test_agents_and_api_do_not_import_eval():
    for pkg in ("agents", "api"):
        for f in (ROOT / pkg).rglob("*.py"):
            for node in ast.walk(ast.parse(f.read_text())):
                mods = []
                if isinstance(node, ast.ImportFrom) and node.module:
                    mods = [node.module]
                elif isinstance(node, ast.Import):
                    mods = [a.name for a in node.names]
                assert not any(m == "eval" or m.startswith("eval.") for m in mods), f
