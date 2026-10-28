"""Honesty engineered: the claim linter over every user-facing string, the not-diagnosis line on
the screens that show results, and no real brand or retailer names. See scripts/claim_lint.py."""
from pathlib import Path

import pytest

from scripts import claim_lint as CL

ROOT = Path(__file__).resolve().parents[2]


def test_no_overclaiming_in_any_user_facing_string():
    findings, _ = CL.lint()
    assert findings == [], "Overclaiming wording found:\n" + "\n".join(map(str, findings))


def test_every_exception_has_a_reason_and_is_still_needed():
    _, excused = CL.lint()
    used = {a for _, a in excused}
    for a in CL.ALLOW:
        assert len(a.reason) > 20, f"Allow entry without a real reason: {a}"
        assert a in used, f"Stale allowlist entry (nothing matches it any more): {a}"


@pytest.mark.parametrize("text,rule", [
    ("This serum caused the change.", "cause"), ("Results caused by the product", "cause"),
    ("It cures redness.", "cure"), ("Treats breakouts fast", "treat"), ("We diagnose your skin", "diagnose"),
    ("Clinically tested formula", "clinically"), ("Proven to work", "prove"), ("This proves it", "prove"),
    ("Guaranteed results", "guarantee"), ("Honestly, it works!", "it works"),
    ("30% fewer breakouts", "% improvement"), ("Reduces redness by 20%", "% improvement"),
    ("improves texture by 12.5 %", "% improvement"),
])
def test_linter_catches(text, rule):
    findings, _ = CL.lint([("frontend/src/x.ts", [(1, text)])])
    assert rule in {f.rule for f in findings}


@pytest.mark.parametrize("text", [
    "Decision support, not diagnosis.", "Treatment step", "because the light changed",
    "Niacinamide 10%", "Changed beyond your normal range during this trial.", "derm//os",
    "This alone can't show the product was the reason: seasons, sleep and cycles move skin too.",
])
def test_linter_leaves_accurate_wording_alone(text):
    findings, _ = CL.lint([("frontend/src/x.ts", [(1, text)])])
    assert findings == []


def test_comments_are_not_user_facing_but_jsx_text_is():
    src = 'const a = 1; // this caused nothing\n/* proven */\n<p>derm//os never says caused by</p>\n'
    code = CL.strip_ts_comments(src)
    assert "caused nothing" not in code and "proven" not in code and "derm//os never says caused by" in code
    assert code.count("\n") == src.count("\n")


def test_backend_template_sentences_are_checked_and_docstrings_are_not(tmp_path):
    p = tmp_path / "m.py"
    p.write_text('"""This module never claims a cure."""\nMSG = "Clinically proven."\n')
    texts = CL.py_texts(p)
    assert [t for _, t in texts] == ["Clinically proven."]


@pytest.mark.parametrize("screen", ["Home.tsx", "Results.tsx", "Brief.tsx"])
def test_not_diagnosis_line_on_home_evidence_and_brief(screen):
    src = (ROOT / "frontend" / "src" / "screens" / screen).read_text(encoding="utf-8")
    assert "{NOT_DIAGNOSIS}" in src


def test_not_diagnosis_wording():
    copy = (ROOT / "frontend" / "src" / "copy.ts").read_text(encoding="utf-8")
    assert 'export const NOT_DIAGNOSIS = "Decision support, not diagnosis.";' in copy


def test_no_real_brand_or_retailer_names():
    hits = CL.brand_hits()
    assert hits == [], "\n".join(map(str, hits))
