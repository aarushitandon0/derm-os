"""Check any product (app/pastecheck.py, pastecheck-1.0). Nothing is stored, no brand is shown."""
from app import cartcheck as CC
from app import pastecheck as PC
from app.scenes import RIYA_CHIPS
from benchmark import cases as C

SUSPECT = "Water, Glycerin, Alcohol Denat., Niacinamide, Zinc PCA, Dimethicone, Phenoxyethanol."
CLEAN = "Water, Glycerin, Squalane, Panthenol, Allantoin, Sodium Hyaluronate, Phenoxyethanol."
CUT = "Water, Glycerin, Squalane..."
BRANDED = "Glowmaker Daily Gel by Ferncove™ Ingredients: Aqua, Glycerin, HydraSilk™ Complex, Squalane, Panthenol, Allantoin."


def run(text, job="moisturiser", nickname=None, chips=RIYA_CHIPS):
    return PC.check(text=text, job=job, nickname=nickname, finish=None, records=C.RIYA_RECS,
                    outcomes=C.RIYA_OUT, chips=chips, catalog=C.IDX, zones=None, measured=None,
                    goal_finish=None)


def test_suspect_repeats_a_pattern():
    r = run(SUSPECT)
    assert r["rung"] == CC.Rung.REPEATS_A_PATTERN.value
    assert r["verdict_line"].startswith("Repeats a pattern")


def test_clean_list_has_no_conflicts():
    r = run(CLEAN)
    assert r["rung"] == CC.Rung.NO_CONFLICTS.value and r["verdict_line"].startswith("No conflicts")
    assert not r["unknown"]


def test_truncated_list_is_unknown_never_clean():
    r = run(CUT)
    assert not r["complete"] and r["unknown"]
    assert CC.UNKNOWN_LABEL in r["verdict_line"]


def test_alcohol_denat_keeps_its_period():
    lines, complete, _ = PC.parse(SUSPECT)
    assert "Alcohol Denat." in lines and lines[-1] == "Phenoxyethanol" and complete


def test_brand_and_trademark_text_dropped_and_nickname_used():
    r = run(BRANDED, nickname="gel from the pharmacy")
    shown = " ".join(r["lines"]) + r["name"] + str(r["sources"])
    assert "Ferncove" not in shown and "Glowmaker" not in shown and "HydraSilk" not in shown
    assert r["name"] == "gel from the pharmacy" and r["lines"][0] == "Aqua"
    assert run(CLEAN)["name"] == PC.DEFAULT_NAME


def test_chip_rung_sits_below_product_level_history():
    vit_c = CLEAN.replace("Allantoin", "Ascorbic Acid")
    assert run(vit_c)["rung"] == PC.TRIED_RUNG
    assert run(SUSPECT.replace("Zinc PCA", "Ascorbic Acid"))["rung"] == CC.Rung.REPEATS_A_PATTERN.value


def test_nothing_is_stored(tmp_path, monkeypatch):
    monkeypatch.setenv("DERMOS_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("DERMOS_MEDIA", str(tmp_path / "media"))
    import importlib
    from fastapi.testclient import TestClient
    import app.main as m
    importlib.reload(m)
    before = {k: len(m.all_(k)) for k in m.KINDS}
    r = TestClient(m.app).post("/api/pastecheck", json={"text": BRANDED, "job": "serum"})
    assert r.status_code == 200 and r.json()["stored"] is False
    assert {k: len(m.all_(k)) for k in m.KINDS} == before
