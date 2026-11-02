"""Logged-in baskets read the saved profile; guest and demo baskets never do.

Same no-network setup as test_accounts.py (local RSA key, replaced JWKS fetch, SQLite).
"""
import json
import re

from tests.test_accounts import A, B, bearer, demo_basket, env, tok  # noqa: F401  (env is a fixture)

H = bearer(tok())
# A link to YouCam or its storage, a stored file, inline image data, or a picture.
YOUCAM_OR_IMAGE = re.compile(r"youcam|perfectcorp|amazonaws|/media/|^data:|^blob:|\.(png|jpe?g|webp)\b", re.I)
LINKISH = re.compile(r"\"((?:https?://|/media/|data:|blob:)[^\"]*)\"")


def picks(b: dict) -> set[str]:
    return {j["pick"]["product"]["id"] for j in b["jobs"] if j.get("pick")}


def me_basket(c, headers=H, **body) -> dict:
    r = c.post("/api/me/basket", headers=headers, json={"persona": "riya", **body})
    assert r.status_code == 200, r.text
    return r.json()


def profile(c, headers=H, **p) -> dict:
    body = {"display_name": "Asha", "finish_goal": "matte", "budget": "under_1000", "beginner": False, **p}
    return c.put("/api/me/profile", headers=headers, json=body).json()


def a_picked_ingredient(m, b: dict) -> tuple[str, str]:
    for pid in sorted(picks(b)):
        for ing in m.CATALOG[pid].inci:
            if ing.lower() not in ("water", "aqua", "glycerin"):
                return pid, ing
    raise AssertionError("no picked product with an ingredient")


# ---------------------------------------------------------------- prefill + reads the profile
def test_logged_in_basket_reads_the_profile_history_and_shelf(env):
    c, m = env["c"], env["m"]
    profile(c)
    c.put("/api/me/chips", headers=H, json={"chips": [{"chip": "niacinamide", "reaction": "suited"}]})
    shelf_pid = next(iter(m.CATALOG))
    c.put("/api/me/shelf", headers=H, json={"product_ids": [shelf_pid]})
    b = me_basket(c, answers={"finish": "matte", "budget": "under_1000", "history": "use"})
    assert b["from_profile"] is True
    assert b["inputs"]["shelf"] == [shelf_pid]
    assert [ch["chip"] for ch in b["inputs"]["chips"]] == ["niacinamide"]
    assert b["inputs"]["finish"] == "matte"


def test_profile_basket_ignores_the_guest_and_demo_history(env):
    c = env["c"]
    c.post("/api/demo/scene/riya-basket")  # Riya's guest history and shelf
    guest = demo_basket(c)
    assert guest["inputs"]["shelf"] or guest["inputs"]["chips"] or guest["inputs"]["records"]
    mine = me_basket(c, answers={"history": "use"})
    assert mine["inputs"]["shelf"] == [] and mine["inputs"]["chips"] == [] and mine["inputs"]["records"] == []


def test_profile_basket_needs_a_token(env):
    assert env["c"].post("/api/me/basket", json={"answers": {}}).status_code == 401
    r = env["c"].post("/api/basket/scan", data={"answers": "{}", "profile": "{}"})
    assert r.status_code == 401


# ---------------------------------------------------------------- edit for this basket only
def test_changing_answers_for_this_basket_leaves_the_profile_alone(env):
    c = env["c"]
    before = profile(c)
    me_basket(c, answers={"finish": "dewy", "budget": "any", "history": "new"})
    after = c.get("/api/me", headers=H).json()["profile"]
    assert (after["finish_goal"], after["budget"], after["beginner"]) == ("matte", "under_1000", False)
    assert after["updated_at"] == before["updated_at"]


def test_unticked_items_are_left_out_of_this_basket_only(env):
    c, m = env["c"], env["m"]
    c.put("/api/me/chips", headers=H, json={"chips": [{"chip": "niacinamide", "reaction": "suited"}]})
    c.put("/api/me/shelf", headers=H, json={"product_ids": [next(iter(m.CATALOG))]})
    b = me_basket(c, answers={"history": "use"}, use={"chips": [], "shelf": []})
    assert b["inputs"]["chips"] == [] and b["inputs"]["shelf"] == []
    h = c.get("/api/me/history", headers=H).json()
    assert len(h["chips"]) == 1 and c.get("/api/me/shelf", headers=H).json()["product_ids"]


def test_update_my_profile_too_writes_the_answers(env):
    c = env["c"]
    profile(c)
    me_basket(c, answers={"finish": "dewy", "budget": "under_700", "history": "new"}, update_profile=True)
    p = c.get("/api/me", headers=H).json()["profile"]
    assert (p["finish_goal"], p["budget"], p["beginner"], p["display_name"]) == ("dewy", "under_700", True, "Asha")


# ---------------------------------------------------------------- clinician-confirmed = hard block
def test_clinician_confirmed_record_is_a_hard_block_even_unticked_or_skipped(env):
    c, m = env["c"], env["m"]
    first = me_basket(c, answers={"history": "use"})
    pid, ing = a_picked_ingredient(m, first)
    r = c.post("/api/me/history", headers=H,
               json={"type": "avoid", "ingredient": ing, "note": "", "clinician_confirmed": True})
    assert r.status_code == 200, r.text
    for answers, use in (({"history": "use"}, {}), ({"history": "use"}, {"records": []}),
                         ({"history": "ignore"}, {}), ({"history": "new"}, {"records": []})):
        b = me_basket(c, answers=answers, use=use)
        assert pid not in picks(b), (answers, use)
        assert any(rec["ingredient"] == ing and rec["type"] == "confirmed_allergy" for rec in b["inputs"]["records"])


def test_a_plain_avoid_note_can_be_left_out_for_this_basket(env):
    c, m = env["c"], env["m"]
    first = me_basket(c, answers={"history": "use"})
    pid, ing = a_picked_ingredient(m, first)
    c.post("/api/me/history", headers=H, json={"type": "avoid", "ingredient": ing, "note": ""})
    assert pid not in picks(me_basket(c, answers={"history": "use"}))
    assert pid in picks(me_basket(c, answers={"history": "use"}, use={"records": []}))


# ---------------------------------------------------------------- isolation
def test_user_b_never_gets_user_a_history_or_basket(env):
    c, m = env["c"], env["m"]
    hb = bearer(tok(B))
    c.put("/api/me/chips", headers=H, json={"chips": [{"chip": "niacinamide", "reaction": "suited"}]})
    c.put("/api/me/shelf", headers=H, json={"product_ids": [next(iter(m.CATALOG))]})
    a_basket = me_basket(c, answers={"history": "use"})
    b_basket = me_basket(c, headers=hb, answers={"history": "use"})
    assert b_basket["inputs"]["chips"] == [] and b_basket["inputs"]["shelf"] == []
    # B can't save A's profile basket, and ids from A's history do nothing for B.
    assert c.post("/api/me/baskets", headers=hb, json={"basket_id": a_basket["id"]}).status_code == 404
    a_ids = [x["id"] for x in c.get("/api/me/history", headers=H).json()["chips"]]
    assert me_basket(c, headers=hb, answers={"history": "use"}, use={"chips": a_ids})["inputs"]["chips"] == []
    assert c.post("/api/me/baskets", headers=H, json={"basket_id": a_basket["id"]}).status_code == 200


def test_guests_never_read_a_profile_basket(env):
    c = env["c"]
    c.put("/api/me/shelf", headers=H, json={"product_ids": [next(iter(env["m"].CATALOG))]})
    mine = me_basket(c, answers={"history": "use"})
    r = c.post("/api/pastecheck", json={"text": "Water, Glycerin", "job": "moisturiser", "basket_id": mine["id"]})
    assert r.status_code == 200
    assert mine["id"] not in json.dumps(r.json())


# ---------------------------------------------------------------- guest + demo unchanged
def test_guest_and_demo_baskets_are_unchanged(env):
    c = env["c"]
    c.post("/api/demo/scene/riya-basket")
    a = demo_basket(c)
    b = c.post("/api/basket", headers=H, json={"answers": {}, "persona": "riya"}).json()  # token ignored
    assert "from_profile" not in a and "from_profile" not in b
    assert a["inputs"]["records"] == b["inputs"]["records"] and a["inputs"]["shelf"] == b["inputs"]["shelf"]
    scan = c.post("/api/basket/scan", data={"answers": "{}", "persona": "riya"}).json()
    assert "from_profile" not in scan and scan["inputs"]["shelf"] == a["inputs"]["shelf"]


def test_demo_personas_write_nothing_to_the_profile(env):
    c = env["c"]
    profile(c)
    before = c.get("/api/me/export", headers=H).json()
    c.post("/api/demo/scene/riya-basket")
    c.post("/api/demo/scene/beginner")
    demo_basket(c)
    after = c.get("/api/me/export", headers=H).json()
    assert before == after


# ---------------------------------------------------------------- saved start plans keep source links
def test_saved_basket_keeps_curated_source_links_and_no_youcam_or_image_url(env):
    c, m = env["c"], env["m"]
    from app.accounts import curated_links
    built = demo_basket(c)
    row = m.get("baskets", built["id"])
    # Stand-ins for what a live basket carries: a try-on render, a YouCam output link, a stored file.
    row["basket"]["tryon"]["looks"][0]["image"] = "/media/abc/tryon_day.jpg"
    row["basket"]["tryon"]["output_url"] = "https://yce-us.s3.amazonaws.com/youcam/out.png"
    row["basket"]["start_plan"]["sources"].append({"id": "x", "text": "t", "url": "https://youcam.example/a.jpg"})
    m.put("baskets", row, id=row["id"])
    saved = c.post("/api/me/baskets", headers=H, json={"basket_id": built["id"]}).json()
    again = c.get(f"/api/me/baskets/{saved['id']}", headers=H).json()
    for plan in (again["start_plan"], again["basket"]["start_plan"]):
        urls = [s.get("url") for s in plan["sources"]]
        assert urls[:2] and all(u in curated_links() for u in urls[:2]), urls
        assert all(u.startswith("https://") for u in urls[:2])
    text = json.dumps(again)
    links = LINKISH.findall(text)
    assert links and not [u for u in links if YOUCAM_OR_IMAGE.search(u)], links
    assert '"image"' not in text
    found = set(re.findall(r"https?://[^\"\s]+", text))
    assert found and found <= curated_links()
