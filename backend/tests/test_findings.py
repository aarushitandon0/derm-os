"""What your scan found (app/findings.py, findings-1.0): words from values already in the scan,
direction per concern, no numbers, a missing concern leaves no line, and the wording passes the
claim linter's rules (including the shopping rules: no score or points, never "can't tell")."""
import json
import re

import pytest

from app import basket as BK
from app import demo_faces as DF
from app import findings as F
from app import needs as N
from app.youcam import normalize
from scripts import claim_lint as CL

D = F.data()
ALL_CONCERNS = ("acne", "pore", "redness", "oiliness", "moisture", "texture", "radiance")


def test_version_and_every_concern_has_three_bands_and_a_direction():
    assert F.RULE_VERSION == "findings-1.0"
    assert set(D["concerns"]) == set(ALL_CONCERNS) == set(D["order"])
    for spec in D["concerns"].values():
        assert {"high", "mid", "low", "higher_means"} <= set(spec)
    # The low band starts where a concern becomes a need, so the two never disagree.
    assert D["bands"]["low"] == N.data()["concern_threshold"]


@pytest.mark.parametrize("value,band", [(100, "high"), (80, "high"), (79.99, "mid"), (60, "mid"),
                                        (59.99, "low"), (1, "low")])
def test_band_edges(value, band):
    assert F.band(value) == band


# Higher raw_score = healthier-looking on every concern (app/evidence.py MOVE_WORDS). For a
# problem concern that means LESS of it at the top; for a quality, MORE of it.
@pytest.mark.parametrize("concern,high,low", [
    ("acne", "Blemishes: hardly any", "Breakouts: noticeable"),
    ("pore", "Pores: barely visible", "Pores: more visible"),
    ("redness", "Redness: very little", "Redness: noticeable"),
    ("oiliness", "Oiliness: little shine", "Oiliness: shiny"),
    ("moisture", "Moisture: well hydrated", "Moisture: on the low side"),
    ("texture", "Texture: smooth", "Texture: uneven"),
    ("radiance", "Radiance: bright", "Radiance: on the dull side"),
])
def test_direction_per_concern(concern, high, low):
    assert [l["line"] for l in F.lines({concern: 95.0})] == [high]
    assert [l["line"] for l in F.lines({concern: 20.0})] == [low]


def test_missing_concern_is_omitted_never_unknown():
    ls = F.lines({"pore": 70.0, "redness": None, "acne": "n/a"})
    assert [l["concern"] for l in ls] == ["pore"]
    assert F.block({}) is None and F.block(None) is None
    text = " ".join(l["line"] for l in F.lines({"moisture": 50.0})).lower()
    assert "can't tell" not in text and "unknown" not in text


def _riya_block() -> dict:
    face = DF.load_face("riya")
    measured = normalize(face["skin"], "sd", DF.BASKET_ACTIONS).raw_scores()
    zones = N.read_zones(face["skin"], {})
    return F.block(measured, N.build_needs(zones, measured))


def test_riya_lines_and_links():
    b = _riya_block()
    assert b["label"] == "Measured by YouCam AI Skin Analysis"
    got = {l["concern"]: (l["line"], l["need"] and l["need"]["key"]) for l in b["lines"]}
    assert got["moisture"] == ("Moisture: on the low side", "hydration")
    assert got["oiliness"] == ("Oiliness: some shine", "oil_control")
    acne = next(l for l in b["lines"] if l["concern"] == "acne")
    assert acne["see_doctor"] == N.data()["concern_needs"]["acne"]["see_doctor"]


def _every_text(block: dict) -> list[str]:
    out = [block["label"]]
    for l in block["lines"]:
        out += [l["line"], l["see_doctor"] or ""]
        if l["need"]:
            out.append(l["need"]["line"])
    return [t for t in out if t]


def test_no_numbers_in_rendered_text():
    blocks = [_riya_block(), F.block({c: v for c, v in zip(ALL_CONCERNS, (12.3, 45, 61.7, 79, 80, 99.9, 5))})]
    for b in blocks:
        for t in _every_text(b):
            assert not re.search(r"\d", t), t


def test_every_word_passes_the_claim_linter_and_shopping_rules():
    texts = [D["measured_by"]] + [spec[k] for spec in D["concerns"].values() for k in ("high", "mid", "low")]
    for t in texts:
        for name, rx in CL.RULES + CL.SHOPPING_RULES:
            assert not rx.search(t), f"[{name}] {t}"
        assert "diagnos" not in t.lower()
    findings, _ = CL.lint()
    assert findings == []


def test_face_map_carries_the_block_and_answers_only_has_none():
    face = DF.load_face("riya")
    measured = normalize(face["skin"], "sd", DF.BASKET_ACTIONS).raw_scores()
    zones = N.read_zones(face["skin"], {})
    from app import undertone as U
    ut = U.from_payload(face["tone"], {})
    fm = BK.face_map(zones, N.build_needs(zones, measured), ut, demo=True, measured=measured)
    assert fm["findings"]["rule_version"] == "findings-1.0" and len(fm["findings"]["lines"]) == 7
    fm2 = BK.face_map(N.zones_from_answers({}), [], ut)
    assert fm2["findings"] is None
    json.dumps(fm)  # serialisable


def test_saved_scan_rebuilds_the_same_links():
    b = F.from_saved({"t_zone": "oily", "u_zone": "normal"}, {"moisture": 58.2, "oiliness": 70.2})
    assert {l["concern"]: l["need"]["key"] for l in b["lines"]} == {"moisture": "hydration", "oiliness": "oil_control"}
    assert F.from_saved({}, {"pore": 90})["lines"][0]["need"] is None
