"""Start plan (app/startplan.py, startplan-1.0)."""
from datetime import date, timedelta

from app import startplan as SP
from benchmark import cases as C

TODAY = date(2026, 11, 2)


def job(title, job_, pid, status="pick"):
    return {"title": title, "job": job_, "status": status, "pick": {"product": {"id": pid}}}


# Deliberately out of order: an active first, the owned cleanser in the middle.
JOBS = [job("Serum", "serum", "sr-01"), job("Sunscreen / skin tint", "base", "tt-02"),
        job("Cleanser", "cleanser", "cl-01", "owned"), job("Cheek moisturiser", "moisturiser", "mo-14")]


def test_patch_week_then_one_new_product_every_14_days():
    p = SP.plan(JOBS, C.IDX, TODAY)
    starts = [date.fromisoformat(s["start_on"]) for s in p["steps"]]
    assert starts[0] == TODAY + timedelta(days=7)
    assert all((b - a).days == 14 for a, b in zip(starts, starts[1:]))
    for s in p["steps"]:
        assert (date.fromisoformat(s["start_on"]) - date.fromisoformat(s["patch_from"])).days == 7
    assert "inner arm or behind the ear" in p["patch_line"]


def test_order_is_gentle_then_base_then_actives():
    p = SP.plan(JOBS, C.IDX, TODAY)
    assert [s["product_id"] for s in p["steps"]] == ["mo-14", "tt-02", "sr-01"]
    assert [s["group"] for s in p["steps"]] == ["gentlest first", "sunscreen next", "actives last"]


def test_owned_is_listed_as_keep_using_not_dated():
    p = SP.plan(JOBS, C.IDX, TODAY)
    assert "cl-01" not in {s["product_id"] for s in p["steps"]}
    assert p["keep"][0]["line"].startswith("Keep using ")


def test_exactly_one_plan_per_basket_with_sources_and_stop_line():
    b = C.basket_of()
    assert isinstance(b["start_plan"], dict) and b["start_plan"]["title"] == "Your start plan"
    assert len({s["product_id"] for s in b["start_plan"]["steps"]}) == len(b["start_plan"]["steps"])
    assert {s["id"] for s in b["start_plan"]["sources"]} == {"patch-test", "one-at-a-time"}
    assert all(s["url"].startswith("https://") for s in b["start_plan"]["sources"])
    assert "itches, stings or burns" in b["start_plan"]["if_reacts"]
    assert SP.plan(JOBS, C.IDX, TODAY) == SP.plan(JOBS, C.IDX, TODAY)        # deterministic
