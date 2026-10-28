"""The evidence benchmark (backend/benchmark/) under pytest: one test per case.
A failure here means the engine and the design disagree. Report it; don't edit the engine to pass."""
import pytest

from benchmark import cases as C
from benchmark.__main__ import markdown, run_case


@pytest.mark.parametrize("case", C.CASES, ids=[c.id for c in C.CASES])
def test_case(case):
    o = run_case(case)
    assert o.passed, f"{case.checks}: expected {case.expected!r}, got {o.error or repr(o.actual)}"


def test_every_category_has_cases_and_report_says_not_independent():
    assert {c.category for c in C.CASES} == set(C.CATEGORIES)
    assert len(C.CASES) >= 40
    md = markdown([run_case(c) for c in C.CASES[:3]])
    assert "not an independent evaluation" in md
