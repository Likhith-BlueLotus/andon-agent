"""Guard tests: ground truth is unreachable from the agents and the API."""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARDED = ["agents", "api"]
FORBIDDEN_MODULES = ("simulator.truth_schema", "simulator.generate", "eval")


def _py_files():
    for pkg in GUARDED:
        yield from (ROOT / pkg).rglob("*.py")


@pytest.mark.parametrize("path", list(_py_files()), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_truth_access_from_agents_or_api(path):
    src = path.read_text()
    assert "truth.json" not in src, f"{path} mentions truth.json"
    for node in ast.walk(ast.parse(src)):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        for n in names:
            assert not n.startswith(FORBIDDEN_MODULES), f"{path} imports {n}"
