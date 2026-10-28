"""python -m benchmark  (run from backend/)

Prints pass counts per category and writes results/benchmark.md. Exit code 1 if any case fails.
"""
from __future__ import annotations

import sys
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import cases as C

OUT = Path(__file__).resolve().parents[1] / "results" / "benchmark.md"


@dataclass
class Outcome:
    case: C.Case
    actual: Any
    passed: bool
    error: str | None = None


def run_case(case: C.Case) -> Outcome:
    try:
        actual = case.run()
    except Exception as e:  # noqa: BLE001 - a crash is a failed case, reported with its type
        return Outcome(case, None, False, f"{type(e).__name__}: {e}")
    return Outcome(case, actual, actual == case.expected)


def run_all() -> list[Outcome]:
    return [run_case(c) for c in C.CASES]


def by_category(outcomes: list[Outcome]) -> "OrderedDict[str, list[Outcome]]":
    groups: OrderedDict[str, list[Outcome]] = OrderedDict((k, []) for k in C.CATEGORIES)
    for o in outcomes:
        groups.setdefault(o.case.category, []).append(o)
    return groups


def _cell(v: Any) -> str:
    return str(v).replace("|", "\\|")


def markdown(outcomes: list[Outcome]) -> str:
    passed = sum(o.passed for o in outcomes)
    lines = [
        "# derm//os evidence benchmark",
        "",
        f"**{passed} of {len(outcomes)} cases pass.**",
        "",
        "Written and run by the derm//os team, so this is **not an independent evaluation**. "
        "Each case has an expected output written from the design doc before the engine was run. "
        "It shows the decision and evidence rules behave as designed; it says nothing about how accurate "
        "YouCam's skin scores are. No YouCam calls, no units spent. The LLM cases use a scripted stand-in "
        "provider (no network): they test the fallback and the claim validator, not any real model.",
        "",
        "Run: `cd backend; python -m benchmark` (also runs under `python -m pytest`).",
        "",
        "| Category | Passed |",
        "| --- | --- |",
    ]
    groups = by_category(outcomes)
    for cat, os_ in groups.items():
        lines.append(f"| {cat} | {sum(o.passed for o in os_)} / {len(os_)} |")
    if C.NOT_BUILT:
        lines += ["", "## Not benchmarked yet", "", "| Design row | Why |", "| --- | --- |"]
        lines += [f"| {_cell(r)} | {_cell(why)} |" for r, why in C.NOT_BUILT]
    fails = [o for o in outcomes if not o.passed]
    if fails:
        lines += ["", "## Failing cases", "", "| Case | Checks | Expected | Actual |", "| --- | --- | --- | --- |"]
        lines += [f"| {o.case.id} | {_cell(o.case.checks)} | {_cell(o.case.expected)} | "
                  f"{_cell(o.error or o.actual)} |" for o in fails]
    lines += ["", "## All cases", ""]
    for cat, os_ in groups.items():
        lines += [f"### {cat}", "", "| Case | Checks | Result |", "| --- | --- | --- |"]
        lines += [f"| {o.case.id} | {_cell(o.case.checks)} | {'pass' if o.passed else 'FAIL'} |" for o in os_]
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    outcomes = run_all()
    groups = by_category(outcomes)
    width = max(len(c) for c in groups)
    print("derm//os evidence benchmark (ours, not independent)\n")
    for cat, os_ in groups.items():
        print(f"  {cat:<{width}}  {sum(o.passed for o in os_):>2} / {len(os_)}")
    passed = sum(o.passed for o in outcomes)
    print(f"\n  {'Total':<{width}}  {passed:>2} / {len(outcomes)}")
    if C.NOT_BUILT:
        print(f"  Not benchmarked yet: {len(C.NOT_BUILT)} design rows")
    for o in outcomes:
        if not o.passed:
            print(f"\n  FAIL {o.case.id} ({o.case.category}): {o.case.checks}\n"
                  f"    expected: {o.case.expected!r}\n    actual:   {o.error or repr(o.actual)}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(markdown(outcomes) + "\n", encoding="utf-8")
    print(f"\nWrote {OUT}")
    return 0 if passed == len(outcomes) else 1


if __name__ == "__main__":
    sys.exit(main())
