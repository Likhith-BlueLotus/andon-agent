"""Grade a run directory and write every output of EVAL_PLAN §8.

    uv run python -m eval.report eval/results/<run> [--slide path.png] [--truth-dir data/scenarios]
                                                    [--publish]

Reads ``results.jsonl`` (+ ``run_meta.json``) and the ground truth (grader only), then writes
``summary.json`` (metrics with Wilson intervals, McNemar tests, calibration, variance, provenance of
the run), ``cost.json``, ``calibration.csv``, ``results_table.md`` and ``results_slide.png``.
``--publish`` copies the frontend payload to ``eval/results/latest.json`` (refused for dry runs).
S-set and R-set are always separate tables and separate bars; they are never pooled.
"""

from __future__ import annotations

import argparse
import csv
import json
import textwrap
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from eval import metrics, sets, stats
from eval.records import load_results

ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "eval" / "results" / "latest.json"

BASE_LABEL = {
    "S1": "S1 full pipeline",
    "S2": "S2 no verifier",
    "S3": "S3 no audio/spectrum",
    "B1": "B1 single prompt",
    "B2": "B2 classical",
}
BASE_ORDER = ["S1", "S2", "S3", "B1", "B2"]
JUDGE_SHORT = {"gemini-3.1-pro-preview": "Pro judge", "gemini-3.8-flash": "Flash judge"}
SET_TITLE = {
    "S": "S-set · synthetic line, injected truth",
    "R": "R-set · real signals on the synthetic line",
    "C": "C-set · pre-registered confirmation, real signals (unused source segments)",
}
FOOTNOTE = (
    "S-set: {n_s} synthetic scenarios with injected ground truth. R-set: real compressor "
    "(MetroPT-3), hydraulic rig (UCI) and bearing (IMS) signals with the source's own labels; "
    "surrounding plant context synthetic. Run {run}, {date}."
)
CONVENTIONS = (
    "95% Wilson intervals; failed runs count as misses; unsupported-claim rate pools claims "
    "re-checked independently by eval/checker.py (clustered by run, so read it with the run-level "
    "rate in summary.json). Sets are never pooled."
)


# --- naming ------------------------------------------------------------------------------------
def base_of(system: str) -> str:
    return system.partition("@")[0]


def sort_key(system: str) -> tuple:
    b = base_of(system)
    return (BASE_ORDER.index(b) if b in BASE_ORDER else 99, system)


def label(system: str, judge_by_system: dict[str, str | None]) -> str:
    b = base_of(system)
    name = BASE_LABEL.get(b, system)
    j = judge_by_system.get(system)
    if b in ("S1", "S2", "S3") and j:
        name += f" ({JUDGE_SHORT.get(j, j)})"
    return name


def jsonable(o: Any) -> Any:
    if isinstance(o, stats.Interval):
        return o.to_dict()
    if isinstance(o, dict):
        return {k: jsonable(v) for k, v in o.items()}
    if isinstance(o, list | tuple):
        return [jsonable(v) for v in o]
    return o


# --- loading and grading -----------------------------------------------------------------------
def all_lines(path: Path) -> list[dict]:
    """Every line of results.jsonl including superseded ones (they still cost money)."""
    out = []
    if path.exists():
        for line in path.read_text("utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def grade_rows(rows: list[dict], truth: dict) -> list[dict]:
    return [
        metrics.grade_run(r, truth[r["scenario_id"]]) for r in rows if r["scenario_id"] in truth
    ]


def cost_json(lines: list[dict], meta: dict) -> dict:
    by_sys: dict[str, dict] = defaultdict(lambda: {"runs": 0, "usd": 0.0, "by_model": {}})
    by_model: dict[str, float] = defaultdict(float)
    total = 0.0
    for r in lines:
        c = r.get("cost") or {}
        usd = float(c.get("usd") or 0.0)
        s = by_sys[r["system"]]
        s["runs"] += 1
        s["usd"] += usd
        total += usd
        for m, v in (c.get("by_model") or {}).items():
            s["by_model"][m] = s["by_model"].get(m, 0.0) + v
            by_model[m] += v
    for s in by_sys.values():
        s["mean_usd"] = round(s["usd"] / s["runs"], 5) if s["runs"] else None
        s["usd"] = round(s["usd"], 5)
        s["by_model"] = {k: round(v, 5) for k, v in s["by_model"].items()}
    est = meta.get("estimate") or {}
    return {
        "run_id": meta.get("run_id"),
        "dry_run": bool(meta.get("dry_run")),
        "total_usd": round(total, 5),
        "n_calls_rows": len(lines),
        "by_system": dict(sorted(by_sys.items(), key=lambda kv: sort_key(kv[0]))),
        "by_model": {k: round(v, 5) for k, v in sorted(by_model.items())},
        "estimated_usd": est.get("total_usd"),
        "note": "includes superseded rows (retried errors); a dry run bills nothing",
    }


# --- summary -----------------------------------------------------------------------------------
def build_summary(out: Path, truth_dir: Path | str) -> tuple[dict, list[dict], list[dict]]:
    """Returns (summary, graded headline+repeat rows, all results lines)."""
    meta_p = out / "run_meta.json"
    meta = json.loads(meta_p.read_text("utf-8")) if meta_p.exists() else {}
    meta.setdefault("run_id", out.name)
    lines = all_lines(out / "results.jsonl")
    rows = list(load_results(out / "results.jsonl").values())
    ids = sorted({r["scenario_id"] for r in rows})
    truth = sets.load_truth(ids, truth_dir)
    graded = grade_rows(rows, truth)
    head = metrics.headline(graded)
    systems = sorted({g["system"] for g in graded}, key=sort_key)
    judge = {r["system"]: r.get("judge_model") for r in rows}

    expected_ids = {
        "S": [i for i in (meta.get("ids") or ids) if i.startswith("S")],
        "R": [i for i in (meta.get("ids") or ids) if i.startswith("R")],
        "C": [i for i in (meta.get("ids") or ids) if i.startswith("C")],
    }
    coverage: dict[str, dict] = {}
    sets_out: dict[str, dict] = {}
    for sname in ("S", "R", "C"):
        sel = [g for g in head if g["set"] == sname]
        if not sel and not expected_ids[sname]:
            continue
        sets_out[sname] = {}
        for sysname in systems:
            rs = [g for g in sel if g["system"] == sysname]
            if not rs:
                continue
            sets_out[sname][sysname] = metrics.summarize(rs)
            coverage.setdefault(sysname, {})[sname] = {
                "expected": len(expected_ids[sname]),
                "completed": len(rs),
                "errors": sum(1 for g in rs if g["status"] != "ok"),
            }
    tests: dict[str, list] = {}
    for sname in sets_out:
        sel = [g for g in head if g["set"] == sname]
        t = []
        first = next((s for s in systems if base_of(s) == "S1"), None)
        if first:
            for other in systems:
                if other != first:
                    c = metrics.compare(sel, first, other)
                    if c:
                        t.append(c)
        tests[sname] = t
    first = next((s for s in systems if base_of(s) == "S1"), None)
    variance = {}
    for s in systems:
        v = metrics.variance(graded, s)
        if v:
            variance[s] = v
    gap = None
    if first and "S" in sets_out and any(base_of(s) == "B1" for s in systems):
        b1 = next(s for s in systems if base_of(s) == "B1")
        a, b = sets_out["S"].get(first), sets_out["S"].get(b1)
        if a and b and a["top1"].p is not None and b["top1"].p is not None:
            gap = round(a["top1"].p - b["top1"].p, 4)
    notes = _notes(meta, sets_out, tests, variance, gap, head)
    summary = {
        "run_id": meta["run_id"],
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "created_at": meta.get("created_at"),
        "dry_run": bool(meta.get("dry_run")),
        "purpose": meta.get("purpose"),
        "git": meta.get("git"),
        "models": meta.get("models"),
        "judge_model_by_system": judge,
        "prompt_versions": meta.get("prompt_versions"),
        "scenario_seeds": {sid: t.seed for sid, t in truth.items()},
        "seed_note": "Scenario seeds are the simulator's; Gemini calls are not seedable "
        "(temperature/top_p/top_k are never sent), hence the variance runs.",
        "systems": systems,
        "n_scenarios": {k: len(v) for k, v in expected_ids.items()},
        "heldout_ids_included": sets.heldout_in(ids),
        "coverage": coverage,
        "sets": sets_out,
        "tests": tests,
        "variance": variance,
        "s1_minus_b1_top1_gap_S": gap,
        "stopped_budget": bool(meta.get("stopped_budget")),
        "notes": notes,
        "conventions": metrics.__doc__,
    }
    meta["lines"] = len(lines)
    return jsonable(summary), graded, lines


def _notes(meta, sets_out, tests, variance, gap, head) -> list[str]:
    notes = []
    if meta.get("dry_run"):
        notes.append("DRY RUN: mocked LLM fixtures; none of these numbers is a result.")
    if meta.get("stopped_budget"):
        notes.append(
            "Run stopped by the daily kill switch: incomplete; resume with the same --out."
        )
    for sname, tl in tests.items():
        for t in tl:
            if not t["significant_at_0.05"]:
                notes.append(
                    f"{sname}-set {t['a']} vs {t['b']}: not significant (discordant {t['a_only']}/"
                    f"{t['b_only']}, exact McNemar p = {t['p']:.3f}); do not claim a difference."
                )
    for s, v in variance.items():
        r = v["spread"]["range"]
        if gap is not None and r is not None and r >= abs(gap):
            notes.append(
                f"{s}: run-to-run top-1 range {r:.2f} is at least the S1-B1 gap {abs(gap):.2f} on the S-set."
            )
    if gap is not None and gap <= 0:
        notes.append(
            "S1 does not beat B1 on S-set top-1: stop and fix before submission, or say so plainly (EVAL_PLAN §9)."
        )
    if "S" in sets_out:
        for s, m in sets_out["S"].items():
            if m["n_error"]:
                notes.append(f"{s}: {m['n_error']} failed run(s) counted as misses.")
    return notes


# --- calibration.csv ---------------------------------------------------------------------------
def write_calibration_csv(summary: dict, path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            ["set", "system", "bin", "lo", "hi", "n", "mean_confidence", "accuracy", "brier", "ece"]
        )
        for sname, per in summary["sets"].items():
            for s, m in per.items():
                if base_of(s) not in ("S1", "B1"):
                    continue
                cal = m["calibration"]
                for b in cal["bins"]:
                    w.writerow(
                        [
                            sname,
                            s,
                            b["bin"],
                            b["lo"],
                            b["hi"],
                            b["n"],
                            b["mean_confidence"],
                            b["accuracy"],
                            cal["brier"],
                            cal["ece"],
                        ]
                    )


# --- frontend payload --------------------------------------------------------------------------
def latest_payload(summary: dict) -> dict:
    """What ``/api/eval/latest`` serves and ``web/src/lib/evalData.ts`` parses: ``sets.S`` / ``sets.R``
    are arrays of flat rows ``{system, n, <metric>: {value, lo, hi} | number}``; every other
    top-level scalar becomes a meta chip."""
    judge = summary.get("judge_model_by_system") or {}
    sets_out: dict[str, list] = {}
    for sname, per in summary["sets"].items():
        rows = []
        for s in sorted(per, key=sort_key):
            m = per[s]
            rows.append(
                {
                    "system": label(s, judge),
                    "n": m["n"],
                    "top1": _cell(m["top1"]),
                    "top3": _cell(m["top3"]),
                    "unsupported_claim_rate": _cell(m["unsupported_claim_rate"]),
                    "median_time_s": _round(m["time_s"]["median"], 1),
                    "cost_per_run_usd": _round(m["cost"]["mean_usd"], 3),
                }
            )
        sets_out[sname] = rows
    return {
        "run_id": summary["run_id"],
        "generated_at": summary["generated_at"],
        "git_sha": (summary.get("git") or {}).get("sha"),
        "dry_run": summary["dry_run"],
        "purpose": summary.get("purpose"),
        "note": "S-set and R-set are never pooled. Intervals are 95% Wilson. "
        + ("DRY RUN: not a result." if summary["dry_run"] else ""),
        "sets": sets_out,
        "tests": summary["tests"],
    }


def _cell(iv: dict) -> dict | None:
    return {"value": iv["value"], "lo": iv["lo"], "hi": iv["hi"]}


def _round(x: float | None, nd: int) -> float | None:
    return None if x is None else round(x, nd)


# --- markdown ----------------------------------------------------------------------------------
def _fmt_iv(iv: dict, ci: bool = True) -> str:
    if iv["value"] is None:
        return "n/a"
    return f"{iv['value']:.2f} [{iv['lo']:.2f}, {iv['hi']:.2f}]" if ci else f"{iv['value']:.2f}"


def markdown(summary: dict) -> str:
    judge = summary.get("judge_model_by_system") or {}
    lines = []
    if summary["dry_run"]:
        lines += ["> **DRY RUN: mocked LLM fixtures. Not a result.**", ""]
    for sname, per in summary["sets"].items():
        lines += [
            f"**{SET_TITLE[sname]}** (95% Wilson intervals; failed runs count as misses)",
            "",
            "| System | n | Top-1 [95% CI] | Top-3 | Unsupported claims | Median time (s) | $/run |",
            "|---|---|---|---|---|---|---|",
        ]
        for s in sorted(per, key=sort_key):
            m = per[s]
            unsup = _fmt_iv(m["unsupported_claim_rate"], ci=False)
            if m["unsupported_claim_rate"]["n"]:
                unsup += f" ({m['unsupported_claim_rate']['k']}/{m['unsupported_claim_rate']['n']})"
            t = m["time_s"]["median"]
            lines.append(
                f"| {label(s, judge)} | {m['n']} | {_fmt_iv(m['top1'])} | {_fmt_iv(m['top3'], False)} | "
                f"{unsup} | {'n/a' if t is None else f'{t:.1f}'} | {m['cost']['mean_usd']:.3f} |"
            )
        for t in summary["tests"].get(sname, []):
            lines.append("")
            lines.append(
                f"- {t['a']} vs {t['b']} top-1, exact McNemar: {t['a']}-only right {t['a_only']}, "
                f"{t['b']}-only right {t['b_only']}, p = {t['p']:.3f}"
                + (" (not significant)" if not t["significant_at_0.05"] else "")
            )
        lines.append("")
    for n in summary["notes"]:
        lines.append(f"- {n}")
    return "\n".join(lines) + "\n"


def _bar_iv(summary: dict, key: str, system: str) -> dict | None:
    if key == "H":
        m = (summary["sets"].get("S", {}).get(system) or {}).get("by_heldout", {}).get("heldout")
    else:
        m = summary["sets"].get(key, {}).get(system)
    iv = m["top1"] if m else None
    return iv if iv and iv["value"] is not None and iv["n"] else None


# --- slide -------------------------------------------------------------------------------------
def render_slide(summary: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    judge = summary.get("judge_model_by_system") or {}
    fig = plt.figure(figsize=(19.2, 10.8), dpi=100, facecolor="white")
    ink, muted = "#16202a", "#5a6772"
    s_col, r_col, h_col = "#1f6feb", "#e07b00", "#0b3d91"
    fig.text(
        0.025,
        0.955,
        "Andon Agent: does verification and tool use beat a single long prompt?",
        fontsize=27,
        fontweight="bold",
        color=ink,
        va="center",
    )
    fig.text(
        0.025,
        0.915,
        "Manufacturing: Intelligent Operations & Industrial Efficiency  ·  "
        "top-1 = right cause class AND right asset",
        fontsize=15,
        color=muted,
        va="center",
    )
    if summary["dry_run"]:
        fig.text(
            0.5,
            0.5,
            "DRY RUN\nmocked LLM, not a result",
            fontsize=54,
            color="#cc0000",
            alpha=0.13,
            ha="center",
            va="center",
            rotation=22,
            fontweight="bold",
        )

    def table(ax, sname: str, fs: int, row_h: float) -> None:
        per = summary["sets"].get(sname, {})
        ax.set_axis_off()
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        cols = [
            ("System", 0.0, "left"),
            ("n", 0.34, "right"),
            ("Top-1 [95% CI]", 0.365, "left"),
            ("Top-3", 0.63, "right"),
            ("Unsupported\nclaims", 0.80, "right"),
            ("Median\ntime", 0.905, "right"),
            ("$/run", 1.0, "right"),
        ]
        ax.text(
            0,
            1.0,
            SET_TITLE[sname]
            + (
                f"  ·  n = {summary['n_scenarios'][sname]}"
                if summary["n_scenarios"].get(sname)
                else ""
            ),
            fontsize=fs + 4,
            fontweight="bold",
            color=ink,
            va="top",
        )
        y = 1.0 - 2.1 * row_h
        for name, x, ha in cols:
            ax.text(x, y, name, fontsize=fs - 2, color=muted, ha=ha, va="center", fontweight="bold")
        y -= 1.15 * row_h
        for i, s in enumerate(sorted(per, key=sort_key)):
            m = per[s]
            if i % 2 == 0:
                ax.add_patch(
                    Rectangle((-0.01, y - row_h / 2), 1.02, row_h, color="#f1f4f8", zorder=0)
                )
            bold = "bold" if base_of(s) == "S1" else "normal"
            u = m["unsupported_claim_rate"]
            unsup = "n/a" if u["n"] == 0 else f"{100 * u['value']:.1f}% ({u['k']}/{u['n']})"
            t = m["time_s"]["median"]
            vals = [
                label(s, judge).replace(" judge", ""),
                str(m["n"]),
                _fmt_iv(m["top1"]),
                _fmt_iv(m["top3"], False),
                unsup,
                "n/a" if t is None else f"{t:.0f} s" if t >= 10 else f"{t:.1f} s",
                f"${m['cost']['mean_usd']:.2f}",
            ]
            for (_, x, ha), v in zip(cols, vals, strict=True):
                ax.text(x, y, v, fontsize=fs, color=ink, ha=ha, va="center", fontweight=bold)
            y -= row_h

    n_s = max(len(summary["sets"].get("S", {})), 1)
    n_r = max(len(summary["sets"].get("R", {})), 1)
    ax_s = fig.add_axes((0.025, 0.58, 0.60, 0.28))
    table(ax_s, "S", 16, 1 / (n_s + 3.4))
    r_key = "R" if "R" in summary["sets"] else "C" if "C" in summary["sets"] else None
    if r_key:  # a C-only (confirmation) run shows its table in the R slot
        n_r = max(len(summary["sets"][r_key]), 1)
        ax_r = fig.add_axes((0.025, 0.285, 0.60, 0.23))
        table(ax_r, r_key, 14, 1 / (n_r + 3.4))
    else:
        fig.text(0.025, 0.4, "R-set not in this run", fontsize=16, color=muted)

    # ---- bar chart: top-1 with whiskers, S / S held-out / R ----
    ax = fig.add_axes((0.67, 0.30, 0.31, 0.56))
    systems = [s for s in summary["systems"]]
    groups = [
        ("S", s_col, "S-set (all)", None),
        ("H", h_col, "S held-out S051-S060", "///"),
        ("R", r_col, "R-set (real signals)", None),
        ("C", "#7a3fb0", "C-set (confirmation)", None),
    ]
    width = 0.26
    drawn = set()
    present = [g for g in groups if any(_bar_iv(summary, g[0], s) for s in systems)]
    for gi, (key, color, lab, hatch) in enumerate(present):
        for xi, s in enumerate(systems):
            if key == "H":
                m = (summary["sets"].get("S", {}).get(s) or {}).get("by_heldout", {}).get("heldout")
            else:
                m = summary["sets"].get(key, {}).get(s)
            iv = m["top1"] if m else None
            if not iv or iv["value"] is None or (key == "H" and iv["n"] == 0):
                continue
            x = xi + (gi - (len(present) - 1) / 2) * width
            ax.bar(
                x,
                iv["value"],
                width * 0.92,
                color=color,
                hatch=hatch,
                edgecolor="white" if not hatch else "#dbe6ff",
                linewidth=0,
                label=lab if lab not in drawn else None,
                alpha=0.95,
            )
            drawn.add(lab)
            ax.errorbar(
                x,
                iv["value"],
                yerr=[[iv["value"] - iv["lo"]], [iv["hi"] - iv["value"]]],
                color="black",
                capsize=5,
                linewidth=2,
            )
            ax.text(
                x,
                min(iv["hi"] + 0.02, 1.02),
                f"{iv['value']:.2f}",
                ha="center",
                va="bottom",
                fontsize=11,
                rotation=90,  # adjacent bars near 100% would otherwise print over each other
                color=ink,
            )
    ax.set_xticks(range(len(systems)))
    ax.set_xticklabels(
        [
            base_of(s)
            + (
                "\n" + JUDGE_SHORT.get(judge.get(s) or "", "").replace(" judge", "")
                if judge.get(s) and base_of(s)[0] == "S"
                else ""
            )
            for s in systems
        ],
        fontsize=15,
    )
    ax.set_ylim(0, 1.2)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_yticklabels(["0", "25%", "50%", "75%", "100%"], fontsize=14)
    ax.set_title(
        "Top-1 accuracy, 95% Wilson whiskers", fontsize=18, fontweight="bold", color=ink, loc="left"
    )
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.25)
    # one row in the free space under the tables: inside the axes it covers bars near 100%
    handles, labels = ax.get_legend_handles_labels()
    ax.figure.legend(handles, labels, fontsize=14, loc="lower left", bbox_to_anchor=(0.025, 0.15),
                     frameon=False, ncol=len(labels), title="Bars (right):", title_fontsize=13)  # fmt: skip

    # ---- tests + footnote ----
    tests = []
    for sname in ("S", "R", "C"):
        for t in summary["tests"].get(sname, []):
            if t["a"].startswith("S1") and base_of(t["b"]) in ("B1", "S2"):
                tests.append(
                    f"{sname}: {t['a']} vs {t['b']} McNemar b={t['a_only']}, c={t['b_only']}, "
                    f"p={t['p']:.3f}"
                )
    fig.text(
        0.67,
        0.22,
        "Paired exact McNemar (discordant pairs):\n" + ("\n".join(tests) or "n/a"),
        fontsize=13,
        color=ink,
        va="top",
    )
    date = (summary.get("created_at") or summary["generated_at"])[:10]
    foot = FOOTNOTE.format(n_s=summary["n_scenarios"].get("S", 0), run=summary["run_id"], date=date)
    foot += " " + CONVENTIONS
    fig.text(
        0.025, 0.115, "\n".join(textwrap.wrap(foot, 190)), fontsize=11.5, color=muted, va="top"
    )
    if summary["notes"]:
        n = [x for x in summary["notes"] if not x.startswith("DRY RUN")][:2]
        if n:
            fig.text(
                0.025,
                0.045,
                "\n".join(textwrap.wrap("Note: " + " ".join(n), 190)),
                fontsize=11.5,
                color="#a15c00",
                va="top",
            )
    fig.savefig(path, dpi=100, facecolor="white")
    plt.close(fig)


# --- orchestration -----------------------------------------------------------------------------
def build_all(
    out: Path,
    truth_dir: Path | str = sets.DEFAULT_SCENARIOS,
    slide: bool = True,
    slide_path: Path | None = None,
) -> dict:
    summary, _, lines = build_summary(out, truth_dir)
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str) + "\n", "utf-8")
    meta_p = out / "run_meta.json"
    meta = json.loads(meta_p.read_text("utf-8")) if meta_p.exists() else {}
    meta.setdefault("run_id", out.name)
    (out / "cost.json").write_text(json.dumps(cost_json(lines, meta), indent=1) + "\n", "utf-8")
    write_calibration_csv(summary, out / "calibration.csv")
    (out / "results_table.md").write_text(markdown(summary), "utf-8")
    (out / "latest.json").write_text(json.dumps(latest_payload(summary), indent=1) + "\n", "utf-8")
    if slide:
        render_slide(summary, slide_path or out / "results_slide.png")
    return summary


def publish(out: Path, dest: Path = LATEST) -> Path:
    payload = json.loads((out / "latest.json").read_text("utf-8"))
    if payload.get("dry_run"):
        raise SystemExit("refusing to publish a dry run as eval/results/latest.json")
    dest.write_text(json.dumps(payload, indent=1) + "\n", "utf-8")
    return dest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.report", description=__doc__.split("\n\n")[0])
    ap.add_argument("run_dir")
    ap.add_argument(
        "--slide", default=None, help="slide PNG path (default <run>/results_slide.png)"
    )
    ap.add_argument("--truth-dir", default=str(sets.DEFAULT_SCENARIOS))
    ap.add_argument("--publish", action="store_true", help="copy latest.json to eval/results/")
    ap.add_argument("--no-slide", action="store_true")
    a = ap.parse_args(argv)
    out = Path(a.run_dir)
    build_all(
        out, Path(a.truth_dir), slide=not a.no_slide, slide_path=Path(a.slide) if a.slide else None
    )
    print(f"wrote outputs in {out}")
    if a.publish:
        print(f"published {publish(out)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
