"""needs-1.0 and undertone-1.0 on synthetic dicts of the documented shapes."""
import pytest

from app import needs as N
from app import undertone as U


@pytest.mark.parametrize("payload", [
    {"t_zone": "Oily", "u_zone": "Dry"},
    {"skin_type": {"whole": {"skin_type": "Combination"}, "t_zone": {"skin_type": "Oily"},
                   "u_zone": {"skin_type": "Dry"}}},
    {"data": {"results": {"output": [{"type": "skin_type", "t_zone": {"type": "oily"},
                                       "u_zone": {"type": "dry"}}]}}},
    {"data": {"results": {"output": [{"type": "skin_type", "t_zone": {"label": "Oily"},
                                       "u_zone": {"label": ["Dry"]}}]}}},
])
def test_parse_zones_documented_shapes(payload):
    z = N.parse_zones(payload)
    assert (z["t_zone"].type, z["u_zone"].type) == ("oily", "dry")
    assert z["t_zone"].source == "face" and z["t_zone"].label == "From your face (YouCam)"


def test_redness_suffix_is_read_and_adds_a_calm_need():
    z = N.parse_zones({"t_zone": "Oily", "u_zone": "Dry & Redness"})
    assert z["u_zone"].type == "dry" and z["u_zone"].redness and not z["t_zone"].redness
    assert z["u_zone"].line() == "Cheeks: dry, with some redness"
    needs = N.build_needs(z, {})
    calm = next(n for n in needs if n.key == "calm")
    assert calm.zone == "u_zone" and "fragrance" in calm.avoid


def test_nothing_readable_gives_empty_and_answers_fill_in():
    assert N.parse_zones({"data": {"results": {"output": [{"type": "pore", "raw_score": 50}]}}}) == {}
    z = N.read_zones(None, {"midday": "shiny_all"})
    assert {r.type for r in z.values()} == {"oily"} and {r.label for r in z.values()} == {"from your answers"}
    z = N.read_zones(None, {})
    assert {r.type for r in z.values()} == {"normal"}


def test_needs_lines_are_words_only():
    z = N.parse_zones({"t_zone": "Oily", "u_zone": "Dry"})
    needs = N.build_needs(z, {"radiance": 52.0, "moisture": 44.0, "acne": 72.0, "pore": 55.0})
    line = N.needs_line(needs)
    assert line.startswith("Needs: oil control on T-zone, hydration on cheeks")
    assert not any(ch.isdigit() for ch in line)
    # Moisture merged into the cheeks' hydration need instead of being listed twice.
    assert sum(1 for n in needs if n.key == "hydration") == 1
    assert all(n.key != "breakouts" for n in needs)        # acne 72 is over the threshold


def test_same_zone_types_give_one_whole_face_need():
    z = N.parse_zones({"t_zone": "Dry", "u_zone": "Dry"})
    needs = N.build_needs(z, {"moisture": 40.0})
    assert [(n.key, n.zone) for n in needs] == [("hydration", "whole")]


def test_acne_need_carries_the_see_a_dermatologist_line():
    z = N.parse_zones({"t_zone": "Oily", "u_zone": "Oily"})
    needs = N.build_needs(z, {"acne": 40.0})
    acne = next(n for n in needs if n.key == "breakouts")
    assert "salicylic acid" in acne.targets and "dermatologist" in acne.see_doctor


def test_vitamin_c_is_kept_out_when_it_is_a_history_suspect():
    z = N.parse_zones({"t_zone": "Normal", "u_zone": "Normal"})
    glow = next(n for n in N.build_needs(z, {"radiance": 40.0}, suspects={"vitamin c"}) if n.key == "glow")
    assert "vitamin c" in glow.avoid and "vitamin c" not in glow.targets


def test_needs_data_is_versioned_with_sources():
    d = N.data()
    assert d["version"] == "needs-1.0" == N.RULE_VERSION
    ids = {s["id"] for s in d["sources"]}
    for spec in list(d["zone_needs"].values()) + list(d["concern_needs"].values()):
        assert spec["source"] in ids


# ---------------------------------------------------------------- undertone
@pytest.mark.parametrize("hex_,tone,depth", [
    ("#b9947c", "warm-neutral", "medium"),
    ("#c8a07c", "warm", "light"),
    ("#c8a7a0", "cool", "light"),
    ("#b9a07c", "olive", "light"),
    ("#5a3a2a", "neutral", "deep"),
])
def test_classify(hex_, tone, depth):
    t, d, lab = U.classify(hex_)
    assert (t, d) == (tone, depth) and set(lab) == {"L", "a", "b", "hue"}


def test_from_documented_payload_is_derived_and_says_so():
    ut = U.from_payload({"data": {"task_status": "success", "results": {
        "face_quality": {"has_face": True}, "color": {"skin_color": "#b9947c", "eye_color": "#62432e"}}}})
    assert ut.source == "face" and ut.skin_color == "#b9947c" and ut.family == ["warm", "neutral"]
    assert "worked out from that colour" in ut.note and ut.line() == "Undertone: warm-neutral"


def test_fallbacks_are_labelled():
    a = U.from_payload(None, {"undertone": "cool", "depth": "tan"})
    assert (a.tone, a.depth, a.source, a.label) == ("cool", "tan", "answers", "from your answers")
    d = U.from_payload({"data": {"results": {"color": {"skin_color": "not-a-colour"}}}}, {})
    assert d.source == "default" and d.tone == "neutral" and "middle of the range" in d.label


def test_match_shade_primary_then_neutral_then_none():
    shades = [{"depth": "medium", "undertone": "neutral", "hex": "#bb8f78"},
              {"depth": "light", "undertone": "warm", "hex": "#d9b08c"}]
    ut = U.from_payload(None, {"undertone": "warm", "depth": "medium"})
    assert U.match_shade(shades, ut)["undertone"] == "neutral"
    ut2 = U.from_payload(None, {"undertone": "cool", "depth": "deep"})
    assert U.match_shade(shades, ut2) is None


def test_bad_hex_raises():
    with pytest.raises(ValueError):
        U.hex_to_lab("#12")
