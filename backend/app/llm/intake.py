"""Free text -> PROPOSED history records. Nothing here saves anything.

The LLM only extracts what the text says, as strict JSON. Plain rules then decide
the record type, so the LLM can't promote a reaction into an allergy:

- A product reaction is always a suspected product reaction. Any ingredient the LLM
  attaches to it is dropped: a reaction to a product never becomes an ingredient record.
- An ingredient allergy becomes "confirmed allergy" only when the user's own words say
  a clinician confirmed it. Otherwise it is proposed as "avoid" with the type marked
  "needs confirmation".
- Products are matched only against the catalog. Anything else stays as typed, unmatched.
- Every record must quote the user's text; a quote that isn't in the text is dropped.
- Any field the text doesn't state clearly goes in `needs_confirmation`.
"""
from __future__ import annotations

import json
import logging
import re

from ..decision import Product, RecordType
from .providers import Provider, call

log = logging.getLogger("dermos.llm")

MAX_TEXT = 1000
MAX_RECORDS = 8
KINDS = ("product_reaction", "ingredient_avoid", "ingredient_allergy")
ITEM_KEYS = {"kind", "product", "ingredient", "clinician_confirmed", "quote"}
CLINICIAN = re.compile(r"\b(dermat\w*|derm|doctor|dr\.?|clinician|allergist|gp|physician|patch[- ]?test\w*|diagnos\w*)\b",
                       re.I)

SYSTEM = """You extract skincare history from a user's own words. You never give advice.
Return ONLY a JSON object, no prose, of exactly this shape:
{"records": [{"kind": "product_reaction" | "ingredient_avoid" | "ingredient_allergy",
              "product": string or null, "ingredient": string or null,
              "clinician_confirmed": true or false, "quote": string}]}
Rules:
- product_reaction: the user's skin reacted to a product. "product" = the product as the user named it.
  Never turn a product reaction into an ingredient.
- ingredient_avoid: the user chooses to avoid an ingredient.
- ingredient_allergy: the user says they are allergic to an ingredient.
- clinician_confirmed is true only if the text says a doctor, dermatologist or other clinician confirmed it.
- "quote" is the exact words from the text this record comes from, copied character for character.
- Use null for anything the text doesn't say. Don't guess. Return {"records": []} if there is nothing."""


class IntakeRejected(Exception):
    """The LLM output wasn't the JSON we asked for. The reason is a short code, never the text."""


def _norm(s: str) -> str:
    s = s.lower().replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    return re.sub(r"\s+", " ", s).strip()


def _key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def parse(raw: str) -> list[dict]:
    """Strict schema check. Raises IntakeRejected on anything unexpected."""
    s = (raw or "").strip()
    fence = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", s, re.S)
    if fence:
        s = fence.group(1)
    try:
        data = json.loads(s)
    except ValueError:
        raise IntakeRejected("not_json") from None
    if not isinstance(data, dict) or set(data) != {"records"} or not isinstance(data["records"], list):
        raise IntakeRejected("wrong_shape")
    if len(data["records"]) > MAX_RECORDS:
        raise IntakeRejected("too_many_records")
    out = []
    for it in data["records"]:
        if not isinstance(it, dict) or set(it) != ITEM_KEYS:
            raise IntakeRejected("wrong_record_keys")
        if it["kind"] not in KINDS:
            raise IntakeRejected("unknown_kind")
        for k in ("product", "ingredient"):
            if it[k] is not None and (not isinstance(it[k], str) or len(it[k]) > 120):
                raise IntakeRejected(f"bad_{k}")
        if not isinstance(it["clinician_confirmed"], bool):
            raise IntakeRejected("bad_clinician_confirmed")
        if not isinstance(it["quote"], str) or not it["quote"].strip() or len(it["quote"]) > 400:
            raise IntakeRejected("bad_quote")
        out.append(it)
    return out


def match_product(text: str | None, catalog: dict[str, Product]) -> tuple[str | None, bool]:
    """(product_id, sure). Only catalog products; a partial name match is proposed but not sure."""
    if not text:
        return None, False
    t = _key(text)
    if not t:
        return None, False
    for p in catalog.values():
        name, full = _key(p.name), _key(f"{p.brand} {p.name}")
        if t in (name, full) or f" {name} " in f" {t} ":
            return p.id, True
    partial = [p.id for p in catalog.values() if len(t.split()) >= 2 and f" {t} " in f" {_key(p.name)} "]
    if len(partial) == 1:
        return partial[0], False
    return None, False


def _proposal(i: int, it: dict, text: str, catalog: dict[str, Product]) -> dict | None:
    quote = it["quote"].strip()
    if _norm(quote) not in _norm(text):
        return None   # not the user's words: drop it
    needs, hints = [], []
    in_text = lambda v: bool(v) and _norm(v) in _norm(text)  # noqa: E731
    product_text = it["product"].strip() if in_text(it["product"]) else None
    ingredient = it["ingredient"].strip() if in_text(it["ingredient"]) else None
    note = f'In your words: "{quote[:160]}"'

    if it["kind"] == "product_reaction":
        pid, sure = match_product(product_text, catalog)
        if not pid:
            needs.append("product_id")
            hints.append("Not matched to a product in the catalog. Pick it, or skip this record."
                         if product_text else "The text doesn't name the product.")
        elif not sure:
            needs.append("product_id")
            hints.append("Partly matches a catalog product. Check it's the right one.")
        # A product reaction stays product-level: any ingredient is dropped on purpose.
        return {"id": f"p{i}", "type": RecordType.SUSPECTED_REACTION.value, "product_id": pid,
                "product_text": product_text, "product_matched": bool(pid), "ingredient": None,
                "note": note, "needs_confirmation": needs, "hints": hints, "quote": quote}

    if not ingredient:
        needs.append("ingredient")
        hints.append("The text doesn't clearly name the ingredient.")
    rtype = RecordType.AVOID
    if it["kind"] == "ingredient_allergy":
        if it["clinician_confirmed"] and CLINICIAN.search(quote):
            rtype = RecordType.CONFIRMED_ALLERGY
        else:
            needs.append("type")
            hints.append("The text doesn't say a clinician confirmed this allergy, so it's proposed as "
                         "\"avoid by choice\". Change it only if a clinician confirmed it.")
    return {"id": f"p{i}", "type": rtype.value, "product_id": None, "product_text": None,
            "product_matched": False, "ingredient": ingredient, "note": note,
            "needs_confirmation": needs, "hints": hints, "quote": quote}


def propose(text: str, catalog: dict[str, Product], provider: Provider | None) -> dict:
    text = (text or "").strip()[:MAX_TEXT]
    if provider is None:
        return {"available": False, "proposals": [], "rejected": None, "dropped": 0}
    if not text:
        return {"available": True, "proposals": [], "rejected": None, "dropped": 0}
    raw = call(provider, SYSTEM, text)
    if raw is None:
        return {"available": True, "proposals": [], "rejected": "provider_failed", "dropped": 0}
    try:
        items = parse(raw)
    except IntakeRejected as e:
        log.info("Intake output rejected: %s", e)
        return {"available": True, "proposals": [], "rejected": str(e), "dropped": 0}
    props = [_proposal(i, it, text, catalog) for i, it in enumerate(items, 1)]
    kept = [p for p in props if p is not None]
    return {"available": True, "proposals": kept, "rejected": None, "dropped": len(props) - len(kept)}
