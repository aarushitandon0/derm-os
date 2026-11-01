"""Start plan (startplan-1.0): every basket ends with a dated plan, not "start one at a time".

The rules, from the sources in app/needs.json "facts" (patch-test before full-face use; one new
product at a time, a week or two apart):

* Each NEW product is patch-tested first, on the inner arm or behind the ear, for the 7 days just
  before its start date.
* Then ONE new product starts every 14 days.
* Order: the gentlest first (cleanser, then moisturisers), sunscreen / skin tint next, actives last
  (a serum or treatment, or a leave-on product built around a retinoid, AHA, BHA, benzoyl peroxide
  or vitamin C).
* Products you already own carry on unchanged and are not in the dated list.
* If something itches, stings or burns: stop it, and open the stop card and the dermatologist brief.

Deterministic: the same basket and the same `today` always give the same dates.
"""
from __future__ import annotations

from datetime import date, timedelta

from . import chips as CH
from . import needs as N
from .decision import Product

RULE_VERSION = "startplan-1.0"
SPACING_DAYS = 14
PATCH_DAYS = 7
PATCH_WHERE = "inner arm or behind the ear"

GROUP_GENTLE, GROUP_BASE, GROUP_ACTIVE = 0, 1, 2
GROUP_WORD = {GROUP_GENTLE: "gentlest first", GROUP_BASE: "sunscreen next", GROUP_ACTIVE: "actives last"}
ACTIVE_ROLES = ("serum", "treatment")
ACTIVE_CHIPS = ("retinoids", "aha", "bha", "benzoyl_peroxide", "vitamin_c", "azelaic_acid")

IF_REACTS = ("If anything itches, stings or burns: stop that product, rinse it off, and don't start the "
             "next one until your skin has settled. Open the stop card and the dermatologist brief.")
PATCH_LINE = (f"Patch-test each new product first: a small amount on your {PATCH_WHERE}, twice a day for "
              f"{PATCH_DAYS} days. Only then use it on your face.")
SPACING_LINE = "One new product every 2 weeks, so if something bothers you there is only one thing it could be."


def _fmt(d: date) -> str:
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')}"


def group_of(job: str, product: Product) -> int:
    if product.role in ACTIVE_ROLES:
        return GROUP_ACTIVE
    if product.leave_on:
        specs = [CH.spec_of(c) for c in ACTIVE_CHIPS]
        for spec in specs:
            if any(m["key_active"] for m in CH.matches(product.inci, spec)):
                return GROUP_ACTIVE
    if job == "base" or product.role == "sunscreen":
        return GROUP_BASE
    return GROUP_GENTLE


def plan(jobs: list[dict], catalog: dict[str, Product], today: date) -> dict:
    """jobs: the basket's cards. Only status "pick" products are new; "owned" ones continue."""
    new, keep = [], []
    for i, j in enumerate(jobs):
        p = (j.get("pick") or {}).get("product")
        if not p:
            continue
        prod = catalog.get(p["id"])
        if prod is None:
            continue
        if j["status"] == "owned":
            keep.append({"product_id": prod.id, "name": prod.name, "job": j["title"],
                         "line": f"Keep using {prod.name} as you do now."})
        elif j["status"] == "pick" and prod.id not in {n["product_id"] for n in new}:
            new.append({"product_id": prod.id, "name": prod.name, "job": j["title"],
                        "group": group_of(j["job"], prod), "order_in": i})
    new.sort(key=lambda n: (n["group"], n["order_in"]))
    steps = []
    for k, n in enumerate(new):
        start = today + timedelta(days=PATCH_DAYS + SPACING_DAYS * k)
        patch_from, patch_to = start - timedelta(days=PATCH_DAYS), start - timedelta(days=1)
        steps.append({
            "order": k + 1, "product_id": n["product_id"], "name": n["name"], "job": n["job"],
            "group": GROUP_WORD[n["group"]],
            "patch_from": patch_from.isoformat(), "patch_to": patch_to.isoformat(),
            "start_on": start.isoformat(),
            "line": (f"{k + 1}. {n['job']}: {n['name']}. Patch-test {_fmt(patch_from)} to "
                     f"{_fmt(patch_to)}, then start it on your face {_fmt(start)}."),
        })
    facts = {f["id"]: f for f in N.data().get("facts", [])}
    return {
        "title": "Your start plan",
        "patch_line": PATCH_LINE, "spacing_line": SPACING_LINE,
        "steps": steps, "keep": keep, "if_reacts": IF_REACTS,
        "spacing_days": SPACING_DAYS, "patch_days": PATCH_DAYS,
        "sources": [{"id": k, "text": facts[k]["text"], "url": facts[k]["url"]}
                    for k in ("patch-test", "one-at-a-time") if k in facts],
        "today": today.isoformat(), "rule_version": RULE_VERSION,
    }
