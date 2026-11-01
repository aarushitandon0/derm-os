"""What to look for (app/lookfor.py, lookfor-1.0)."""
from app.scenes import RIYA_CHIPS
from benchmark import cases as C
from scripts.claim_lint import BRANDS


def blocks(b):
    return {j["job"] + ":" + j["zone"]: j["look_for"] for j in b["jobs"]}


def test_no_brand_or_product_names():
    b = C.basket_of(chips=RIYA_CHIPS)
    names = {p.name for p in C.IDX.values()} | {p.brand for p in C.IDX.values() if p.brand}
    for lf in blocks(b).values():
        text = " ".join(lf["lines"])
        assert not [n for n in names | set(BRANDS) if n and n in text], text


def test_base_excludes_exfoliants():
    b = C.basket_of(chips=RIYA_CHIPS)
    base = next(j["look_for"] for j in b["jobs"] if j["job"] == "base")
    assert not {"salicylic acid (BHA)", "lactic acid (AHA)"} & set(base["ingredients"])
    assert base["shade"] and "family" in base["shade"]


def test_avoid_lists_the_users_own_reasons():
    b = C.basket_of(chips=RIYA_CHIPS)
    avoid = next(j["look_for"] for j in b["jobs"] if j["job"] == "moisturiser")["avoid"]
    whys = {a["what"]: a["why"] for a in avoid}
    assert whys["vitamin C"] == "itched, stung or burned on you before"
    assert whys["azelaic acid as a key active"] == "broke you out before"
    assert whys["fragrance"] == "you chose to avoid it"
    assert "snail mucin" not in whys                     # "suited me" is never an avoid


def test_deterministic():
    assert blocks(C.basket_of(chips=RIYA_CHIPS)) == blocks(C.basket_of(chips=RIYA_CHIPS))
