"""Plain-language explanation of a stored evidence result, behind a claim validator.

The LLM sees only the structured record (verdict, ranges, comparability, symptoms,
product name). It writes 1-3 sentences. `validate` rejects any draft that:
  - uses causal wording ("caused", "because of", "worked", ...),
  - uses diagnosis words ("eczema", "rosacea", ...; "allergy" only if the record is clinician-confirmed),
  - names a product or ingredient that isn't in the record,
  - states a verdict stronger than the stored one,
  - gives a number that isn't in the record.
On rejection (or any failure) the template sentence is shown. Only the reason code is
logged, never the draft.
"""
from __future__ import annotations

import json
import logging
import re

from ..decision import Product
from ..inci import SYNONYMS, canonical_list
from .providers import Provider, call

log = logging.getLogger("dermos.llm")

SYSTEM = """You explain one skincare trial result to the person who ran it, in 1 to 3 short plain sentences.
Use ONLY facts in the JSON record you are given. Rules:
- Never say a product caused, fixed, worked or led to anything. Say things "changed during this trial" at most.
- Never name a skin condition or diagnosis.
- Never name a product or ingredient that isn't in the record.
- Never make the result sound stronger than the "verdict" field.
- Only use numbers that appear in the record.
Return only the sentences, no lists, no headings."""

CAUSAL = re.compile(r"\b(caus\w*|because of|due to|thanks to|led to|leads? to|lead to|made your skin|makes? your skin|"
                    r"fix(ed|es)?|cur(ed|es?)|worked|works|working|responsible for|result(ed)? of|as a result)\b", re.I)
DIAGNOSIS = re.compile(r"\b(eczema|rosacea|dermatitis|psoriasis|seborrh\w*|melasma|folliculitis|urticaria|"
                       r"infection|infected|fungal|diagnos\w*|disease|disorder|syndrome)\b", re.I)
ALLERGY = re.compile(r"\ballerg\w*\b", re.I)
OVERCLAIM = re.compile(r"\b(prove[sn]?|proof|definitely|certainly|clearly|guarantee\w*|clinically|significant\w*|"
                       r"effective\w*|safe to)\b", re.I)
DIRECTION = re.compile(r"\b(better|worse|improv\w*|worsen\w*|reduc\w*|increas\w*|decreas\w*|clear(ed|er)? up|"
                       r"real change|changed beyond)\b", re.I)
BETTER = re.compile(r"\b(better|improv\w*|reduc\w*|clear(ed|er)? up)\b", re.I)
WORSE = re.compile(r"\b(worse|worsen\w*)\b", re.I)
NO_CHANGE_CLAIM = re.compile(r"\b(no (detectable |real )?change|unchanged|(has|have)n'?t changed|did ?n[o']?t change|"
                             r"stayed the same|no difference)\b", re.I)
KEEP_GOING = re.compile(r"\b(keep using|continue using|carry on|keep going)\b", re.I)
NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")

CANT_TELL = {"cant_tell_no_baseline", "cant_tell_not_comparable", "cant_tell_several_changes"}
EXTRA_INGREDIENTS = {"retinol", "lanolin", "hyaluronic acid", "benzoyl peroxide", "paraben", "parabens", "sulfate",
                     "sulfates", "aha", "bha", "vitamin a", "ceramide", "ceramides", "peptide", "peptides", "fragrance",
                     "essential oil", "essential oils"}


def vocabulary(catalog: dict[str, Product]) -> list[str]:
    """Product names, brands and ingredient names the validator watches for."""
    words = set(EXTRA_INGREDIENTS)
    for p in catalog.values():
        words.update({p.name.lower(), p.brand.lower()})
        words.update(canonical_list(p.inci))
    for key, spellings in SYNONYMS.items():
        words.add(key)
        words.update(spellings)
    # Very short tokens ("mit", "eau") would match ordinary words; skip them.
    return sorted((w for w in words if len(w) >= 4), key=len, reverse=True)


def _numbers(record: dict) -> set[str]:
    out: set[str] = set()

    def walk(v):
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            for s in (str(v), f"{v:g}", str(round(v)), f"{v:.1f}", f"{v:.2f}"):
                out.add(s)
                out.add(s.rstrip("0").rstrip(".") if "." in s else s)
        elif isinstance(v, str):
            out.update(NUMBER.findall(v))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
    walk(record)
    return out


def validate(draft: str, record: dict, catalog: dict[str, Product]) -> str | None:
    """None if the draft is acceptable, else a short reason code (logged; never the text)."""
    text = (draft or "").strip()
    if not text:
        return "empty"
    if len(text) > 600 or "\n\n" in text or re.search(r"^\s*[-*#]", text, re.M):
        return "format"
    sentences = [s for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if not 1 <= len(sentences) <= 3:
        return "sentence_count"
    if CAUSAL.search(text):
        return "causal_wording"
    if DIAGNOSIS.search(text):
        return "diagnosis_word"
    if ALLERGY.search(text) and not record.get("clinician_confirmed_allergy"):
        return "diagnosis_word"
    if OVERCLAIM.search(text):
        return "stronger_verdict"

    rec_text = json.dumps(record, ensure_ascii=False).lower()
    low = f" {re.sub(r'[^a-z0-9%.& -]+', ' ', text.lower())} "
    for w in vocabulary(catalog):
        if re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", low) and w not in rec_text:
            return "name_not_in_record"

    verdict = record.get("verdict")
    if verdict != "moved_beyond_noise" and DIRECTION.search(text):
        return "stronger_verdict"
    if verdict in CANT_TELL and NO_CHANGE_CLAIM.search(text):
        return "stronger_verdict"
    if verdict == "stop_reaction" and KEEP_GOING.search(text):
        return "stronger_verdict"
    if verdict == "moved_beyond_noise":
        dirs = {f.get("direction") for f in record.get("findings", []) if f.get("beyond_noise")}
        if (BETTER.search(text) and "better" not in dirs) or (WORSE.search(text) and "worse" not in dirs):
            return "stronger_verdict"

    allowed = _numbers(record)
    for n in NUMBER.findall(text):
        if n not in allowed:
            return "number_not_in_record"
    return None


def record_for(report: dict, product: Product, goal_concern: str, clinician_confirmed_allergy: bool = False) -> dict:
    """The only thing the LLM sees: the stored structured result, no photos, no history notes."""
    comp = report.get("comparability") or {}
    return {
        "verdict": report["verdict"],
        "verdict_sentence": report["message"],
        "goal_concern": goal_concern,
        "product": {"name": product.name, "brand": product.brand},
        "findings": report.get("findings", []),
        "comparable": comp.get("comparable"),
        "comparability_reasons": comp.get("reasons", []),
        "symptoms": report.get("symptoms", []),
        "clinician_confirmed_allergy": clinician_confirmed_allergy,
    }


def explain(record: dict, template: str, catalog: dict[str, Product], provider: Provider | None) -> dict:
    """{"text", "source": "llm" | "template", "rejected": reason | None}."""
    if provider is None:
        return {"text": template, "source": "template", "rejected": None}
    draft = call(provider, SYSTEM, json.dumps(record, ensure_ascii=False))
    if draft is None:
        return {"text": template, "source": "template", "rejected": "provider_failed"}
    reason = validate(draft, record, catalog)
    if reason:
        log.info("Explanation draft rejected: %s", reason)
        return {"text": template, "source": "template", "rejected": reason}
    return {"text": draft.strip(), "source": "llm", "rejected": None}
