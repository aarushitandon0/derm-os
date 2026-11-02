"""Basket engine (basket-1.0): one selfie -> a skincare basket made for your face.

docs/strategy.md sections 4-5. Deterministic, versioned, inputs stored with every result.

    zones + needs (app/needs.py) + finish goal + undertone (app/undertone.py)
        -> jobs: cleanser, a moisturiser per zone (one when both zones read the same), base
        -> per job, every product in the shop's stock tagged for that job is either
             already owned, skipped (with its exact reason), or a candidate
        -> candidates are ranked; the top one is the pick, the rest "also fit"
        -> one next step

How a product is skipped, first reason wins (the order the user would care about):

    history    the cart check (app/cartcheck.py) says BLOCKED or REPEATS A PATTERN. The reason
               is the cart check's own line, so the basket can't word it differently.
    unknown    the ingredient list is incomplete. It is never picked, so an unreadable label
               can never be shown as a pass.
    finish     its finish clashes with the one you asked for (matte when you want dewy).
    shade      tinted, and the range has no shade at your depth in your undertone family.
    zone       made for a different skin type than the zone this job is for.
    budget     over your budget while something under it fits.

Rules the claim linter and the tests hold this file to: products are "aimed at" a need, never
said to fix or work; nothing is ever called safe; no score or number about the skin appears in
any sentence; and the shopping flow always gives an answer. When a measurement is missing the
answer comes from the quiz and says "from your answers".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from . import cartcheck as CC
from . import chips as CH
from . import decision as D
from . import findings as F
from . import lookfor as LF
from . import needs as N
from . import patterns as P
from . import startplan as SP
from . import undertone as U
from .inci import canonical
from .outcomes import ProductOutcome

RULE_VERSION = "basket-1.0"

# Exactly one next step for every basket (docs/strategy.md section 4, step 7).
NEXT_STEP = ("Follow your start plan below: patch-test each new product first, then add one new product "
             "every 2 weeks.")
NEXT_STEP_NOTHING_NEW = ("Nothing new to buy: keep using what you have. Tap to set a day-14 reminder "
                         "to look again.")

HISTORY_IGNORED = "You chose not to check this basket against your history."
HISTORY_NOTHING = "Nothing recorded yet, so there was nothing to check it against."
HISTORY_CLEAR = "Nothing on this label matches anything that bothered you before."

BUDGETS = {"under_700": 700, "under_1000": 1000, "any": None}

# Skip kinds, in the order they are tried. The first that applies is the reason shown.
# "tried" (an ingredient chip, app/chips.py) sits right under "history": product-level history ranks
# above chips, so when both apply the product-level line is the one shown first.
SKIP_ORDER = ("history", "tried", "unknown", "finish", "shade", "zone", "budget")
SKIP_LABEL = {"history": "From your history", "tried": "From what you've tried",
              "unknown": "Ingredient list incomplete → unknown",
              "finish": "Wrong finish", "shade": "No shade for you", "zone": "Wrong zone type",
              "budget": "Over your budget"}

# Try-on: two renders of the base product in your shade (YouCam AI Makeup Virtual Try-On).
# Field names follow a public client of the API (glowIntensity, coverageIntensity, colorIntensity,
# 0-100); they are not yet checked against a live call, which the next live session does first.
TRYON_LOOKS = {
    "matte": {"label": "Matte", "colorIntensity": 55, "coverageIntensity": 50, "glowIntensity": 0},
    "dewy": {"label": "Dewy", "colorIntensity": 55, "coverageIntensity": 50, "glowIntensity": 70},
}
TRYON_PENDING = "Preview appears on a live scan"

HOW_TO_USE = {
    ("cleanser", "whole"): "Whole face, morning and night. Rinse with lukewarm water.",
    ("moisturiser", "t_zone"): "T-zone only (forehead, nose and chin), morning and night, a thin layer.",
    ("moisturiser", "u_zone"): "Cheeks and jawline, morning and night.",
    ("moisturiser", "whole"): "Whole face, morning and night.",
    ("base", "whole"): "Whole face, every morning as the last step. Reapply sunscreen every 2 hours outdoors.",
}

JOB_TITLE = {("cleanser", "whole"): "Cleanser", ("moisturiser", "t_zone"): "T-zone moisturiser",
             ("moisturiser", "u_zone"): "Cheek moisturiser", ("moisturiser", "whole"): "Moisturiser",
             ("base", "whole"): "Sunscreen / skin tint"}

# Owned products from the app's own catalogue carry no shop tags, so the only job they can be
# said to fill without guessing is the whole-face cleanser (any cleanser, used without a problem).
SHELF_BY_ROLE = {"cleanser": "cleanser"}

# Beginner ("nothing tried yet"): no history step, and the ranking leans to fragrance-free, gentle,
# low-active products. Every card then carries this label.
GENTLE_LABEL = "Gentle start for new routines"
GENTLE_ACTIVE_CHIPS = ("retinoids", "aha", "bha", "benzoyl_peroxide", "vitamin_c", "azelaic_acid",
                       "niacinamide")


def _and(words: list[str]) -> str:
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"


@dataclass
class Job:
    job: str                 # cleanser | moisturiser | base
    zone: str                # whole | t_zone | u_zone
    skin_type: str           # the type the product must suit
    zone_source: str         # face | answers

    @property
    def key(self) -> str:
        return f"{self.job}:{self.zone}"

    @property
    def title(self) -> str:
        return JOB_TITLE[(self.job, self.zone)]


def jobs_for(zones: dict[str, N.ZoneRead]) -> list[Job]:
    t, u = zones["t_zone"], zones["u_zone"]
    whole = t.type if N.same_type(zones) else "combination"
    src = "face" if "face" in (t.source, u.source) else "answers"
    out = [Job("cleanser", "whole", whole, src)]
    if N.same_type(zones):
        out.append(Job("moisturiser", "whole", t.type, t.source))
    else:
        out += [Job("moisturiser", "t_zone", t.type, t.source), Job("moisturiser", "u_zone", u.type, u.source)]
    out.append(Job("base", "whole", whole, src))
    return out


def _suits(tags: dict, skin_type: str) -> bool:
    suits = tags.get("suits") or []
    if skin_type == "combination":
        return "combination" in suits
    return skin_type in suits


def _hits(product: D.Product, targets: list[str]) -> list[str]:
    """The label lines that are on the need's target list, as printed on the label."""
    return [raw.strip() for raw in product.inci if canonical(raw) in set(targets)]


@dataclass
class Considered:
    product: D.Product
    tags: dict
    check: CC.CartCheck | None
    reasons: list[tuple[str, str]] = field(default_factory=list)   # (kind, sentence)
    shade: dict | None = None
    hits: list[str] = field(default_factory=list)
    over_budget: bool = False
    tried: dict = field(default_factory=dict)


def _history_line(chk: CC.CartCheck | None, use_history: bool) -> str:
    if not use_history or chk is None:
        return HISTORY_IGNORED
    if chk.nothing_to_check:
        return HISTORY_NOTHING
    if chk.rung == CC.Rung.NO_CONFLICTS.value:
        return HISTORY_CLEAR
    hist = next(s for s in chk.sources if s.key == "history")
    first = hist.lines[0] if hist.lines else ""
    return f"{CC.RUNG_LABEL[chk.rung]}: {first}"


def _skip_history(chk: CC.CartCheck) -> str | None:
    if chk.rung == CC.Rung.BLOCKED.value:
        hist = next(s for s in chk.sources if s.key == "history")
        return hist.lines[0] if hist.lines else CC.RUNG_LABEL[chk.rung]
    if chk.rung == CC.Rung.REPEATS_A_PATTERN.value:
        m = next(m for m in next(s for s in chk.sources if s.key == "history").detail["matches"]
                 if m["tier"] == P.Tier.SUSPECT.value and m["match_type"] == "exact")
        return f"Contains {m['label_line']}, {m['counts_line']}."
    return None


def _consider(p: D.Product, tags: dict, job: Job, *, chk: CC.CartCheck | None, finish: str,
              fspec: dict, ut: U.Undertone, zones_line: str, targets: list[str],
              cap: int | None, avoid: list[str], chips: list[CH.Chip] | None = None) -> Considered:
    c = Considered(p, tags, chk, hits=_hits(p, targets))
    if chk is not None:
        why = _skip_history(chk)
        if why:
            c.reasons.append(("history", why))
    if chips:
        c.tried = CH.evaluate(p.inci, chips)
        for s in c.tried["skip"]:
            c.reasons.append(("tried", s["line"]))
    if not p.inci_complete:
        # The card already prints SKIP_LABEL["unknown"] above this line, so the reason doesn't repeat it.
        c.reasons.append(("unknown", "Anything not printed on the label can't be checked against your "
                                     "history, so it isn't picked."))
    fin = tags.get("finish")
    if fin in fspec["clash"]:
        c.reasons.append(("finish", f"{fin.capitalize()} finish; you asked for {fspec['words']}."))
    if tags.get("tinted"):
        c.shade = U.match_shade(tags.get("shades") or [], ut)
        if c.shade is None:
            c.reasons.append(("shade", f"No shade for {ut.depth} {ut.tone} skin in this range."))
    if not _suits(tags, job.skin_type):
        c.reasons.append(("zone", f"Made for {_and(list(tags.get('suits') or ['other']))} skin; "
                                  f"{zones_line}."))
    for a in avoid:
        lines = [raw.strip() for raw in p.inci if canonical(raw) == a]
        if lines and not any(k == "history" for k, _ in c.reasons):
            c.reasons.append(("history", f"Lists {lines[0]}; with redness on your face map, the basket "
                                         f"keeps to {a}-free products."))
    if cap is not None and p.price_inr > cap:
        c.over_budget = True
    return c


def harsh_for_beginner(p: D.Product) -> bool:
    """Lists fragrance, essential oils or a drying alcohol (Alcohol Denat.)."""
    keys = set(p.canonical_inci)
    return bool(keys & (set(P.FAM.members_of("fragrance")) | {"essential oils"}
                        | set(P.FAM.members_of("drying alcohols"))))


def gentle_rank(p: D.Product) -> tuple[int, int]:
    """(lists fragrance, essential oils or Alcohol Denat., number of actives on the label): lower is gentler."""
    keys = set(p.canonical_inci)
    actives = sum(1 for cid in GENTLE_ACTIVE_CHIPS if keys & set(CH.spec_of(cid)["members"]))
    return (1 if harsh_for_beginner(p) else 0, actives)


def _rank_key(c: Considered, fspec: dict, textures: list[str], beginner: bool = False):
    rung = 1 if c.check is not None and c.check.rung == CC.Rung.PATCH_TEST_FIRST.value else 0
    gentle = gentle_rank(c.product) if beginner else (0, 0)
    fin = c.tags.get("finish")
    fin_rank = fspec["prefer"].index(fin) if fin in fspec["prefer"] else len(fspec["prefer"])
    tex = c.tags.get("texture")
    tex_rank = textures.index(tex) if tex in textures else len(textures)
    return (c.over_budget, rung, gentle, fin_rank, -len(c.hits), tex_rank, c.product.price_inr, c.product.id)


def _zone_phrase(job: Job, zones: dict[str, N.ZoneRead]) -> str:
    if job.zone == "whole":
        if N.same_type(zones):
            return f"your skin reads {zones['t_zone'].type}"
        return f"your skin reads combination (T-zone {zones['t_zone'].type}, cheeks {zones['u_zone'].type})"
    z = zones[job.zone]
    verb = "reads" if job.zone == "t_zone" else "read"
    return f"your {N.zone_in_sentence(job.zone)} {verb} {z.type}"


def _face_line(c: Considered, job: Job, zones: dict[str, N.ZoneRead], needs: list[N.Need],
               ut: U.Undertone) -> str:
    phrase = _zone_phrase(job, zones)
    tex = c.tags.get("texture")
    aimed = [n.words for n in needs if n.zone in (job.zone, "whole") or job.zone == "whole"]
    aimed = list(dict.fromkeys(aimed))[:2]
    bits = f"{phrase[0].upper()}{phrase[1:]}. A {tex}" + (f" aimed at {_and(aimed)}" if aimed else "")
    if c.hits:
        bits += f", listing {_and(c.hits[:3])}"
    bits += "."
    if job.job == "base" and c.shade:
        bits += f" Shade {c.shade['name']}, for {ut.depth} skin with a {ut.tone} undertone."
    return bits


def _finish_line(tags: dict, finish: str, fspec: dict) -> str:
    fin = tags.get("finish") or "natural"
    if fin == finish:
        return f"{fin.capitalize()} finish, as you asked."
    return f"{fin.capitalize()} finish, which sits well under the {fspec['words']} look you asked for."


@dataclass
class Basket:
    face_map: dict
    jobs: list[dict]
    skipped: list[dict]
    already_own: list[dict]
    total_inr: int
    next_step: str
    tryon: dict
    inputs: dict
    start_plan: dict = field(default_factory=dict)
    tried: dict = field(default_factory=dict)
    beginner: bool = False
    rule_version: str = RULE_VERSION

    def to_dict(self) -> dict:
        return {"face_map": self.face_map, "jobs": self.jobs, "skipped": self.skipped,
                "already_own": self.already_own, "total_inr": self.total_inr,
                "next_step": self.next_step, "tryon": self.tryon, "inputs": self.inputs,
                "start_plan": self.start_plan, "tried": self.tried, "beginner": self.beginner,
                "rule_version": self.rule_version}


def face_map(zones: dict[str, N.ZoneRead], needs: list[N.Need], ut: U.Undertone, *,
             demo: bool = False, measured: dict[str, float] | None = None) -> dict:
    """What the face map screen shows: one plain line per zone, the top needs, the undertone."""
    src = "face" if any(z.source == "face" for z in zones.values()) else "answers"
    return {
        "zones": [zones[z].to_dict() for z in N.ZONES],
        "same_type": N.same_type(zones),
        "needs": [n.to_dict() for n in needs[:3]],
        "needs_line": N.needs_line(needs),
        "see_doctor": next((n.see_doctor for n in needs if n.see_doctor), None),
        "undertone": ut.to_dict(),
        "source": src, "label": N.FROM_FACE if src == "face" else N.FROM_ANSWERS,
        "demo": demo,
        # What the scan found, in words (app/findings.py). None when nothing was measured.
        "findings": F.block(measured, needs),
    }


def build(*, zones: dict[str, N.ZoneRead], measured: dict[str, float] | None, ut: U.Undertone,
          answers: dict, stock: dict[str, dict], catalog: dict[str, D.Product],
          records: list[D.HistoryRecord], outcomes: list[ProductOutcome], shelf: list[str],
          demo: bool = False, src_file_id: str | None = None, chips: list | None = None,
          today: date | None = None, always: list[D.HistoryRecord] | None = None) -> Basket:
    """The whole basket. `stock` is the shop's tags by product id (app/products.shop_tags).
    `chips` is the quick history by ingredient (app/chips.py); `today` dates the start plan.
    `always`: clinician-confirmed records from an account, applied even when history is skipped."""
    answers = dict(answers or {})
    finish, fspec = N.finish_spec(answers.get("finish"))
    use_history = answers.get("history", "use") != "ignore"
    # "new": nothing tried yet. The history step is skipped and the ranking leans gentle.
    beginner = answers.get("history") == "new"
    cap = BUDGETS.get(answers.get("budget") or "any")
    chip_objs = CH.parse_all(chips) if use_history and not beginner else []
    # A clinician-confirmed chip becomes the existing hard-block record type, nothing new.
    recs = ((list(records) + CH.records_from(chip_objs)) if use_history else []) + list(always or [])
    outs = list(outcomes) if use_history else []
    reports = P.run_both(outs, catalog)
    suspects = {s.ingredient for r in reports.values() for s in r.suspects if s.tier == P.Tier.SUSPECT.value}
    needs = N.build_needs(zones, measured, suspects | CH.itched_members(chip_objs))
    avoid = N.avoid_for(needs)
    shelf = [i for i in shelf if i in catalog]
    checks: dict[str, CC.CartCheck] = {}

    def chk(pid: str) -> CC.CartCheck:
        if pid not in checks:
            checks[pid] = CC.check(catalog[pid], recs, outs, catalog, measured, shelf, reports=reports)
        return checks[pid]

    jobs_out: list[dict] = []
    owned_out: list[dict] = []
    skips: dict[str, dict] = {}
    picked: set[str] = set()
    fits: set[str] = set()
    total = 0
    base_pick: Considered | None = None
    base_fallback_shade: dict | None = None

    for job in jobs_for(zones):
        how = HOW_TO_USE[(job.job, job.zone)]
        card = {"job": job.job, "zone": job.zone, "title": job.title, "skin_type": job.skin_type,
                "zone_source": job.zone_source, "how_to_use": how, "status": "pick",
                "pick": None, "why": [], "also_fits": [], "note": None}
        # Already own: a store product for this job on the shelf, or a cleanser you use.
        owned = [pid for pid in shelf if stock.get(pid, {}).get("job") == job.job
                 and _suits(stock[pid], job.skin_type)]
        role = SHELF_BY_ROLE.get(job.job)
        if role and not owned:
            owned = [pid for pid in shelf if pid not in stock and catalog[pid].role == role]
        owned = [pid for pid in owned if chk(pid).rung not in (CC.Rung.BLOCKED.value,
                                                                CC.Rung.REPEATS_A_PATTERN.value)]
        if owned:
            p = catalog[owned[0]]
            card.update(status="owned", pick={"product": p.__dict__, "price_inr": 0, "shade": None})
            card["why"] = [{"key": "shelf", "label": "From your shelf",
                            "line": f"You already own {p.name}. It fills the {job.title.lower()} step, "
                                    f"so skip buying one."}]
            owned_out.append({"product_id": p.id, "name": p.name, "brand": p.brand, "job": job.title,
                              "line": f"You already own {p.name}: skip buying a {job.title.lower()}."})
            jobs_out.append(card)
            continue

        targets = N.targets_for(needs, job.zone)
        textures = N.textures_for(needs, job.zone)
        considered = []
        for pid, tags in sorted(stock.items()):
            if tags.get("job") != job.job or pid not in catalog:
                continue
            c = _consider(catalog[pid], tags, job, chk=chk(pid) if use_history or always else None, finish=finish,
                          fspec=fspec, ut=ut, zones_line=_zone_phrase(job, zones), targets=targets,
                          cap=cap, avoid=avoid, chips=chip_objs)
            if pid in shelf and not c.reasons:
                owned_out.append({"product_id": pid, "name": c.product.name, "brand": c.product.brand,
                                  "job": job.title,
                                  "line": f"You already own {c.product.name}: skip buying it again."})
                card.update(status="owned", pick={"product": c.product.__dict__, "price_inr": 0,
                                                  "shade": c.shade})
                continue
            considered.append(c)
            if job.job == "base" and c.shade and not any(k in ("history", "unknown") for k, _ in c.reasons):
                base_fallback_shade = base_fallback_shade or c.shade
        if card["status"] == "owned":
            card["why"] = [{"key": "shelf", "label": "From your shelf",
                            "line": f"You already own {card['pick']['product']['name']}, and it fits this step."}]
            jobs_out.append(card)
            continue

        eligible = [c for c in considered if not c.reasons]
        under = [c for c in eligible if not c.over_budget]
        if under:
            for c in eligible:
                if c.over_budget:
                    c.reasons.append(("budget", f"₹{c.product.price_inr:,} is over your budget of "
                                                f"₹{cap:,} a product."))
            eligible = under
        elif eligible and cap is not None:
            card["note"] = (f"Nothing under ₹{cap:,} fits this step, so this is the closest fit "
                            f"in the shop's stock.")
        eligible.sort(key=lambda c: _rank_key(c, fspec, textures, beginner))
        for c in considered:
            if c.reasons:
                kind, line = sorted(c.reasons, key=lambda r: SKIP_ORDER.index(r[0]))[0]
                prev = skips.get(c.product.id)
                if prev is None or SKIP_ORDER.index(kind) < SKIP_ORDER.index(prev["kind"]):
                    skips[c.product.id] = {"product_id": c.product.id, "name": c.product.name,
                                           "brand": c.product.brand, "job": job.title, "kind": kind,
                                           "label": SKIP_LABEL[kind], "reason": line,
                                           "all_reasons": [r for _, r in c.reasons]}
        if not eligible:
            card.update(status="none", note=(f"Nothing in this shop's stock fits the "
                                             f"{job.title.lower()} step for you. Keep what you use now."))
            jobs_out.append(card)
            continue
        top = eligible[0]
        picked.add(top.product.id)
        fits.update(c.product.id for c in eligible[1:])
        if job.job == "base":
            base_pick = top
        price = top.product.price_inr
        total += price
        face_label = N.FROM_FACE if job.zone_source == "face" else f"From your answers"
        card["pick"] = {"product": top.product.__dict__, "price_inr": price, "shade": top.shade,
                        "finish": top.tags.get("finish"), "texture": top.tags.get("texture"),
                        "rung": top.check.rung if top.check else None}
        card["why"] = [
            {"key": "face", "label": face_label, "line": _face_line(top, job, zones, needs, ut)},
            {"key": "history", "label": "From your history", "line": _history_line(top.check, use_history)},
            {"key": "finish", "label": "Matches your finish", "line": _finish_line(top.tags, finish, fspec)},
        ]
        card["tried"] = list(top.tried.get("worked", [])) + list(top.tried.get("notes", []))
        if beginner:
            card["label"] = GENTLE_LABEL
        card["also_fits"] = [{"product_id": c.product.id, "name": c.product.name, "brand": c.product.brand,
                              "price_inr": c.product.price_inr,
                              "patch_test_first": bool(c.check and c.check.rung == CC.Rung.PATCH_TEST_FIRST.value)}
                             for c in eligible[1:]
                             # A beginner's alternatives keep the same gentle bias as the pick.
                             if not (beginner and harsh_for_beginner(c.product))][:2]
        jobs_out.append(card)

    # A product picked or still fitting somewhere is not "skipped", whatever another job said.
    skipped = [s for pid, s in skips.items() if pid not in picked and pid not in fits]
    skipped.sort(key=lambda s: (SKIP_ORDER.index(s["kind"]), s["product_id"]))
    bought = [j for j in jobs_out if j["status"] == "pick"]
    next_step = NEXT_STEP if bought else NEXT_STEP_NOTHING_NEW
    tryon = tryon_plan(base_pick, base_fallback_shade, ut, demo=demo, src_file_id=src_file_id)

    # "What to look for" on every card: works in any store, names no brand (app/lookfor.py).
    hist_avoid = _history_avoid(reports, recs)
    for card in jobs_out:
        tinted = any(t.get("tinted") for t in stock.values() if t.get("job") == card["job"])
        card["look_for"] = LF.block(job=card["job"], zone=card["zone"], needs=needs, finish=finish, ut=ut,
                                    tinted=tinted, chips=chip_objs, history_avoid=hist_avoid,
                                    need_avoid=avoid)
    plan_ = SP.plan(jobs_out, catalog, today or date.today())
    tried = {"chips": [c.to_dict() for c in chip_objs],
             "purge_questions": [c.to_dict() for c in chip_objs if c.purge_question()],
             "beginner": beginner, "rule_version": CH.RULE_VERSION}

    fm = face_map(zones, needs, ut, demo=demo, measured=measured)
    inputs = {
        "answers": answers, "zones": {z: r.to_dict() for z, r in zones.items()},
        "measured": dict(measured or {}), "undertone": ut.to_dict(), "shelf": list(shelf),
        "records": [{"type": r.type.value, "product_id": r.product_id, "ingredient": r.ingredient} for r in recs],
        "outcomes": [{"product_id": o.product_id, "outcome": o.outcome} for o in outs],
        "stock": sorted(stock), "use_history": use_history, "budget_cap": cap, "finish": finish,
        "rule_versions": {"basket": RULE_VERSION, "needs": N.RULE_VERSION, "undertone": U.RULE_VERSION,
                          "cartcheck": CC.RULE_VERSION, "patterns": P.RULE_VERSION,
                          "families": P.FAM.FAMILIES_VERSION, "chips": CH.RULE_VERSION,
                          "lookfor": LF.RULE_VERSION, "startplan": SP.RULE_VERSION,
                          "findings": F.RULE_VERSION},
        "chips": [c.to_dict() for c in chip_objs], "beginner": beginner, "today": plan_["today"],
    }
    return Basket(fm, jobs_out, skipped, owned_out, total, next_step, tryon, inputs,
                  start_plan=plan_, tried=tried, beginner=beginner)


def _history_avoid(reports: dict[str, P.PatternReport], recs: list[D.HistoryRecord]) -> list[dict]:
    """Product-level history as "Avoid:" items: exact suspects from your outcomes, and ingredients
    you chose to avoid or hold a clinician-confirmed record for. No product or brand is named."""
    out: list[dict] = []
    for kind, r in reports.items():
        for s in r.suspects:
            if s.tier == P.Tier.SUSPECT.value and s.match_type == "exact":
                why = ("in products that made you itch" if kind == "irritation"
                       else "in products that broke you out")
                out.append({"what": s.display, "why": why})
    for rec in recs:
        if rec.type in (D.RecordType.AVOID, D.RecordType.CONFIRMED_ALLERGY) and rec.ingredient:
            if rec.note.startswith("From your ingredient history"):
                continue          # the chip itself is listed by app/lookfor.py
            why = "you chose to avoid it" if rec.type == D.RecordType.AVOID else "clinician-confirmed record"
            item = {"what": rec.ingredient, "why": why}
            if item not in out:
                out.append(item)
    return out


def vto_body(src_file_id: str | None, hex_: str, look: str) -> dict:
    """The Makeup VTO task body for one look (foundation only)."""
    spec = TRYON_LOOKS[look]
    return {"src_file_id": src_file_id or "<file id from the selfie upload>", "version": "1.0",
            "effects": [{"category": "foundation",
                         "palettes": [{"color": hex_, "colorIntensity": spec["colorIntensity"],
                                       "coverageIntensity": spec["coverageIntensity"],
                                       "glowIntensity": spec["glowIntensity"]}]}]}


def tryon_plan(base: Considered | None, fallback_shade: dict | None, ut: U.Undertone, *,
               demo: bool, src_file_id: str | None = None, renders: dict | None = None) -> dict:
    """Matte vs dewy, in your shade. In demo mode with no recorded render, it says when the
    preview appears instead of showing anything made up."""
    shade = (base.shade if base and base.shade else None) or fallback_shade
    if shade is None:
        return {"status": "no_shade", "line": "No tinted product in this basket to try on.",
                "looks": [], "requests": []}
    looks = [{"look": k, "label": v["label"], "glow": v["glowIntensity"], "image": (renders or {}).get(k)}
             for k, v in TRYON_LOOKS.items()]
    ready = all(lk["image"] for lk in looks)
    return {"status": "ready" if ready else "pending_live",
            "line": None if ready else TRYON_PENDING,
            "product": base.product.__dict__ if base and base.shade else None,
            "shade": shade, "undertone": ut.tone, "looks": looks,
            "requests": [{"look": k, "body": vto_body(src_file_id, shade["hex"], k)} for k in TRYON_LOOKS],
            "fields_note": "VTO field names follow a public client of the API and are checked on the first live call."}
