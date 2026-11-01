"""What to look for (lookfor-1.0): one block per basket card that works in any store.

The basket picks from this shop's stock. This block says what to look for on ANY label for the same
job, so the advice still holds in another shop: the key ingredients your zone's needs are aimed at,
the texture and finish, the shade family for a tinted product, and "Avoid:" with your own skip
reasons. It never names a brand or a product. Deterministic: same inputs, same block.
"""
from __future__ import annotations

from . import chips as CH
from . import needs as N
from . import undertone as U

RULE_VERSION = "lookfor-1.0"

# Plain names for the canonical keys the needs engine aims at.
WORDS = {
    "niacinamide": "niacinamide", "salicylic acid": "salicylic acid (BHA)", "zinc pca": "zinc PCA",
    "glycerin": "glycerin", "sodium hyaluronate": "hyaluronic acid", "ceramide np": "ceramides",
    "squalane": "squalane", "panthenol": "panthenol", "centella asiatica extract": "centella",
    "allantoin": "allantoin", "sodium ascorbyl phosphate": "a vitamin C derivative",
    "ascorbyl glucoside": "a vitamin C derivative", "3-o-ethyl ascorbic acid": "a vitamin C derivative",
    "lactic acid": "lactic acid (AHA)", "benzoyl peroxide": "benzoyl peroxide",
}
MAX_INGREDIENTS = 4

TEXTURE_WORDS = {"gel": "a gel", "fluid": "a fluid", "foam": "a foam", "lotion": "a lotion",
                 "cream": "a cream", "balm": "a balm"}
FINISH_WORDS = {"dewy": "a dewy (glow) finish", "natural": "a natural (satin) finish",
                "matte": "a matte finish"}
# A cleanser is washed off, so its finish doesn't matter; sunscreen and tints are always fluids here.
JOB_TEXTURE = {"cleanser": None, "base": ["fluid", "lotion"]}


def _and(words: list[str]) -> str:
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} or {words[-1]}"


def ingredient_words(targets: list[str]) -> list[str]:
    return list(dict.fromkeys(WORDS.get(t, t) for t in targets))[:MAX_INGREDIENTS]


def block(*, job: str, zone: str, needs: list[N.Need], finish: str, ut: U.Undertone, tinted: bool,
          chips: list[CH.Chip], history_avoid: list[dict], need_avoid: list[str]) -> dict:
    """job/zone of the card; history_avoid: [{"what", "why"}] from product-level history (suspects,
    avoid records); need_avoid: ingredients the face's needs keep out (fragrance with redness)."""
    targets = N.targets_for(needs, zone)
    if job == "cleanser":
        # A wash-off step: only the gentle, zone-type targets are worth looking for.
        targets = [t for t in targets if t in ("glycerin", "salicylic acid", "zinc pca", "panthenol",
                                               "ceramide np", "niacinamide")]
    elif job == "base":
        # A sunscreen or tint: only the comfort ingredients belong in it, not exfoliants.
        targets = [t for t in targets if t in ("niacinamide", "glycerin", "sodium hyaluronate", "squalane",
                                               "panthenol", "allantoin")]
    ings = ingredient_words(targets)
    textures = JOB_TEXTURE[job] if job in JOB_TEXTURE else N.textures_for(needs, zone)[:2]
    tex = _and([TEXTURE_WORDS.get(t, t) for t in textures]) if textures else None
    fin = None if job == "cleanser" else FINISH_WORDS.get(finish)
    shade = None
    if job == "base" and tinted:
        fam = _and(list(ut.family))
        shade = f"a {ut.depth} shade in the {fam} family"
    avoid: list[dict] = []
    for a in history_avoid:
        if a not in avoid:
            avoid.append(a)
    for a in CH.avoid_items(chips):
        item = {"what": a["what"], "why": a["why"]}
        if item not in avoid:
            avoid.append(item)
    for a in need_avoid:
        item = {"what": a, "why": "redness on your face map"}
        if not any(x["what"] == a for x in avoid):
            avoid.append(item)

    lines = []
    if ings:
        lines.append(f"Key ingredients: {_and(ings)}.")
    feel = " with ".join(x for x in (tex, fin) if x)
    if feel:
        lines.append(f"Texture: {feel}.")
    if shade:
        lines.append(f"Shade: {shade}.")
    if avoid:
        lines.append("Avoid: " + "; ".join(f"{a['what']} ({a['why']})" for a in avoid) + ".")
    worked = CH.worked_words(chips)
    if worked:
        lines.append(f"Worked for you before: {', '.join(worked)}.")
    return {"ingredients": ings, "texture": tex, "finish": fin, "shade": shade, "avoid": avoid,
            "worked": worked, "lines": lines, "rule_version": RULE_VERSION}
