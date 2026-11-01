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


# The words added for the three moments (docs/STRATEGY.md section 4, rule 9).
@pytest.mark.parametrize("text,rule", [
    ("This causes breakouts", "cause"), ("Redness caused by the toner", "cause"),
    ("You have an allergy to linalool", "allergy"), ("You're allergic to this", "allergy"),
    ("This product is safe for you", "safe"), ("Safe to use daily", "safe"),
    ("Honestly, it works", "works"), ("This worked for her", "works"),
    ("It will work on your skin", "works"), ("The serum works", "works"),
    ("Works for you", "works"), ("It does work", "works"),
    ("Proven to help", "prove"), ("It treats acne", "treat"), ("Cures dryness", "cure"),
    ("We diagnose your skin type", "diagnose"),
    ("This fixes your skin", "fixes"), ("It fixed my acne", "fixes"),
    ("Will fix it in two weeks", "fixes"), ("Fixes pores", "fixes"),
])
def test_linter_catches_the_added_words(text, rule):
    findings, _ = CL.lint([("frontend/src/x.ts", [(1, text)])])
    assert rule in {f.rule for f in findings}, f"{text!r} should trip [{rule}]"


@pytest.mark.parametrize("text", [
    # "Fix" as the retake instruction, and "fixed" as the trial design, are not claims.
    "fixes: string[];", "The fixes are listed below.", "Holding fixed",
    "Everything else is held fixed, and 3 scans set her own range.",
    "fixed, tested rules decide what the numbers mean",
    "Scans will be refused until you fix or clear it.",
    # "Works best" is advice about a photo; "worked out" is what the engine did.
    "The spot where you took them works best.", "The original photo works best.",
    "every verdict is worked out by the same engine as a real trial",
    # The user's own question is one of the three moments, not an answer we give.
    "Is my product working?", "Is it working? See what your scans can and can't say",
    # Different words.
    "unsafe", "safety", "safely", "Not for safekeeping",
])
def test_linter_leaves_the_non_claim_uses_alone(text):
    findings, _ = CL.lint([("frontend/src/x.ts", [(1, text)])])
    assert findings == [], f"{text!r} is not a claim: {findings}"


def test_the_added_rules_are_all_registered():
    for rule in ("allergy", "safe", "works", "fixes"):
        assert rule in {name for name, _ in CL.RULES}


@pytest.mark.parametrize("text", [
    # Nothing the new engines say may trip the linter.
    "No conflicts with your history", "Repeats a pattern", "Patch-test first", "Blocked",
    "Ingredient list incomplete → unknown",
    "Aimed at pores. Pores is your 2nd lowest YouCam score of the 3 we measured.",
    "“Aimed at” is what the product is for. It is not a reading of what it will do to your skin.",
    "No scan yet: scan to see if this is aimed at your skin's top concerns.",
    "One product can't tell us which of its 6 ingredients did it.",
    "Not a purge. It lists no ingredient that speeds up cell turnover.",
    "Consistent with purging rather than a breakout.",
    "You said it suited you, but that is 2 weeks of use.",
    "Too early to say", "Suited me", "Not sure", "Broke me out",
])
def test_the_new_engine_wording_passes_the_linter(text):
    findings, _ = CL.lint([("frontend/src/x.ts", [(1, text)])])
    assert findings == [], f"{text!r}: {findings}"


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


# ---- Strategy v2: the shopping flow never shows a score and never says "can't tell".
@pytest.mark.parametrize("text,rule", [
    ("Your oiliness score is 48", "score shown"), ("You earned 12 points", "score shown"),
    ("Skin health 72/100", "score shown"), ("We can't tell yet", "can't tell"),
    ("We cannot tell from this photo", "can't tell"), ("Can’t tell", "can't tell"),
])
@pytest.mark.parametrize("file", sorted(CL.SHOPPING_FILES))
def test_shopping_flow_rules(file, text, rule):
    findings, _ = CL.lint([(file, [(1, text)])])
    assert rule in {f.rule for f in findings}, f"{text!r} in {file} should trip [{rule}]"


@pytest.mark.parametrize("text", ["raw_score", "Your T-zone reads oily", "from your answers",
                                  "Preview appears on a live scan"])
def test_shopping_flow_rules_leave_plain_words_alone(text):
    findings, _ = CL.lint([("frontend/src/screens/Basket.tsx", [(1, text)])])
    assert findings == []


def test_shopping_rules_are_scoped_to_the_basket_flow():
    # The optional check-in keeps its own measured wording, including its "can't tell yet" verdict.
    findings, _ = CL.lint([("frontend/src/screens/Results.tsx", [(1, "We can't tell yet")])])
    assert findings == []


def test_every_shopping_file_exists():
    for f in CL.SHOPPING_FILES:
        assert (ROOT / f).is_file(), f
