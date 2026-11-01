"""Start here: the quiz, the tolerant skin_type parser, and the checked 3-step starter.

The parser tests run on synthetic dicts on purpose. SD skin_type's response shape has not been
seen (finding out costs a unit), so there is deliberately no skin_type fixture file: a made-up
fixture would sit next to the real recorded ones and look like recorded data.

New cases only.
"""
import pytest

from app import beginner as B
from app import products as PRD

CAT = PRD.index()

DRY = {"midday": "tight", "reacts": "rarely", "breakouts": "rarely", "using": "nothing"}
OILY = {"midday": "shiny_all", "reacts": "rarely", "breakouts": "weekly", "using": "cleanser"}
COMBO = {"midday": "shiny_tzone", "reacts": "rarely", "breakouts": "monthly", "using": "few"}
NORMAL = {"midday": "comfortable", "reacts": "rarely", "breakouts": "rarely", "using": "nothing"}
SENSITIVE = {**NORMAL, "reacts": "often"}


# ---------------------------------------------------------------- the quiz
def test_there_are_four_questions_each_with_choices_and_a_why():
    assert len(B.QUESTIONS) == 4
    for q in B.QUESTIONS:
        assert q["id"] and q["text"] and q["why"] and len(q["choices"]) >= 3
        for c in q["choices"]:
            assert c["value"] and c["label"]


@pytest.mark.parametrize("answers,expected", [
    (DRY, "dry"), (OILY, "oily"), (COMBO, "combination"), (NORMAL, "normal"),
])
def test_the_quiz_reads_a_skin_type(answers, expected):
    assert B.skin_type_from_answers(answers).value == expected


def test_the_quiz_answer_is_labelled_as_coming_from_the_answers():
    st = B.skin_type_from_answers(DRY)
    assert st.source == "answers"
    assert st.label == "from your answers" == B.FROM_ANSWERS_LABEL


def test_no_answers_gives_no_skin_type_rather_than_a_guess():
    st = B.skin_type_from_answers({})
    assert st.value is None
    assert "don't point clearly to one skin type" in st.line


def test_sensitivity_changes_the_pace_not_the_type():
    st = B.skin_type_from_answers(SENSITIVE)
    assert st.value == "normal" and st.sensitive is True
    assert "changes the pace" in st.line
    assert "One new product at a time" in st.line


def test_every_skin_type_has_a_plain_sentence():
    for t in B.SKIN_TYPES:
        assert B.TYPE_LINE[t]


# ---------------------------------------------------------------- the tolerant parser
@pytest.mark.parametrize("payload", [
    "oily",
    {"skin_type": "oily"},
    {"skin_type": {"value": "Oily"}},
    {"data": {"results": {"skin_type": "OILY"}}},
    {"data": {"results": {"output": [{"type": "skin_type", "label": "oily"}]}}},
    {"data": {"results": {"output": [{"type": "skin_type", "whole": {"class": "oily"}}]}}},
    {"result": {"skin_type": {"category": "Oil"}}},
    {"skin_type": ["oily"]},
])
def test_the_parser_copes_with_every_shape_we_can_imagine(payload):
    assert B.parse_skin_type(payload).value == "oily"


def test_the_parser_reads_a_per_zone_split_when_there_is_one():
    st = B.parse_skin_type({"data": {"results": {"skin_type": {
        "t_zone": {"value": "oily"}, "u_zone": {"value": "dry"}}}}})
    assert st.zones == {"T-zone": "oily", "U-zone": "dry"}
    assert "T-zone: oily" in st.line and "U-zone: dry" in st.line


def test_a_whole_face_reading_wins_over_a_zone_one():
    st = B.parse_skin_type({"skin_type": {"whole": "combination", "t_zone": "oily"}})
    assert st.value == "combination"


def test_combination_spellings_normalise():
    for spelling in ("combination", "Combo", "COMBINATION", "combo"):
        assert B.parse_skin_type({"skin_type": spelling}).value == "combination"


@pytest.mark.parametrize("payload", [
    {}, None, {"skin_type": None}, {"skin_type": "unrecognised-value"},
    {"data": {"results": {"output": []}}}, {"redness": {"raw_score": 61.0}}, 42, [],
])
def test_an_unreadable_response_returns_no_value_rather_than_a_guess(payload):
    st = B.parse_skin_type(payload)
    assert st.value is None
    assert "still from your answers" in st.line


def test_a_scan_reading_is_labelled_as_coming_from_the_scan():
    st = B.parse_skin_type({"skin_type": "dry"})
    assert st.source == "scan" and st.label == "from your scan" == B.FROM_SCAN_LABEL


def test_the_parser_never_raises_on_odd_input():
    for payload in ({"a": {"b": {"c": [1, 2, {"d": None}]}}}, [[[["oily"]]]], {"x": object()}):
        B.parse_skin_type(payload)


# ---------------------------------------------------------------- the starter
def test_the_starter_is_three_steps_cleanse_moisturise_protect():
    p = B.plan(COMBO, CAT)
    assert [s["role"] for s in p.steps] == list(B.STARTER_ROLES)


def test_every_starter_step_carries_its_own_cart_check():
    p = B.plan(COMBO, CAT)
    for s in p.steps:
        assert s["check"]["rule_version"] == "cartcheck-1.0"
        assert len(s["check"]["sources"]) == 3
        assert s["check"]["next_step"]


def test_the_starter_has_no_active_in_it():
    """A beginner has no baseline to read an active against, so none is offered."""
    for answers in (DRY, OILY, COMBO, NORMAL, SENSITIVE):
        for s in B.plan(answers, CAT).steps:
            assert s["role"] in B.STARTER_ROLES
            assert "treatment" != s["role"] and "serum" != s["role"]


def test_a_sensitive_answer_changes_the_starter():
    assert B.starter_ids(B.skin_type_from_answers(SENSITIVE)) == B.SENSITIVE_STARTER
    assert B.starter_ids(B.skin_type_from_answers(NORMAL)) != B.SENSITIVE_STARTER


def test_every_starter_product_exists_in_the_index():
    ids = set(B.SENSITIVE_STARTER)
    for v in B.STARTER_BY_TYPE.values():
        ids |= set(v)
    missing = [i for i in ids if i not in CAT]
    assert missing == []


def test_start_one_at_a_time_is_said():
    p = B.plan(COMBO, CAT)
    assert "Start one at a time" in p.one_at_a_time
    assert "only one thing it could be" in p.one_at_a_time


def test_there_is_exactly_one_next_step_and_it_opens_a_trial():
    p = B.plan(COMBO, CAT)
    assert "\n" not in p.next_step
    assert "day 14 and day 28 check-ins" in p.next_step


# ---------------------------------------------------------------- concerns
def test_with_no_scan_there_are_no_measured_concerns():
    p = B.plan(COMBO, CAT)
    assert p.concerns == []
    assert p.skin_type.source == "answers"


def test_with_a_scan_the_top_three_concerns_each_get_one_plain_sentence():
    measured = {"redness": 62.1, "texture": 58.6, "acne": 72.2, "pore": 55.2,
                "oiliness": 48.1, "moisture": 63.2}
    p = B.plan(COMBO, CAT, measured=measured)
    assert [c["concern"] for c in p.concerns] == ["oiliness", "pore", "texture"]
    for c in p.concerns:
        assert c["sentence"] and ":" in c["sentence"]
        assert "fixes" not in c["sentence"].lower()


def test_every_concern_the_app_scans_has_a_sentence():
    for c in ("redness", "acne", "texture", "pore", "oiliness", "moisture"):
        assert c in B.CONCERN_SENTENCE


# ---------------------------------------------------------------- the scan overrides the quiz
def test_a_readable_scan_replaces_the_quiz_answer():
    p = B.plan(DRY, CAT, scan_payload={"skin_type": "oily"})
    assert p.skin_type.value == "oily" and p.skin_type.source == "scan"


def test_an_unreadable_scan_leaves_the_quiz_answer_in_place():
    p = B.plan(DRY, CAT, scan_payload={"redness": 61.0})
    assert p.skin_type.value == "dry" and p.skin_type.source == "answers"


def test_sensitivity_survives_a_scan_reading():
    p = B.plan(SENSITIVE, CAT, scan_payload={"skin_type": "oily"})
    assert p.skin_type.sensitive is True
    assert "changes the pace" in p.skin_type.line
