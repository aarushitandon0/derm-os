"""INCI ingredient-name normalisation.

Labels write the same ingredient many ways: "Parfum (Fragrance)", "Aqua/Water/Eau",
"Niacinamide 5%". Exclusion matching must not miss a synonym, so every name is
reduced to one canonical key before comparison.
"""
from __future__ import annotations

import re

# canonical key -> spellings seen on labels. Small and curated on purpose:
# every entry is a claim we can defend. Extend with care.
SYNONYMS: dict[str, set[str]] = {
    "fragrance": {"fragrance", "parfum", "perfume", "aroma", "parfum fragrance", "fragrance parfum"},
    "water": {"water", "aqua", "eau", "aqua water", "water aqua", "aqua water eau"},
    "vitamin e": {"tocopherol", "tocopheryl acetate", "vitamin e"},
    "vitamin c": {"ascorbic acid", "l-ascorbic acid"},
    "niacinamide": {"niacinamide", "nicotinamide"},
    "salicylic acid": {"salicylic acid", "bha", "beta hydroxy acid"},
    "glycolic acid": {"glycolic acid"},
    "lactic acid": {"lactic acid"},
    "retinol": {"retinol"},
    "retinal": {"retinal", "retinaldehyde"},
    "alcohol denat": {"alcohol denat", "alcohol denat.", "sd alcohol", "denatured alcohol", "ethanol", "alcohol"},
    "linalool": {"linalool"},
    "limonene": {"limonene", "d-limonene"},
    "citronellol": {"citronellol"},
    "geraniol": {"geraniol"},
    "methylisothiazolinone": {"methylisothiazolinone", "mit"},
    "essential oils": {"lavandula angustifolia oil", "lavender oil", "citrus aurantium dulcis peel oil",
                       "orange peel oil", "mentha piperita oil", "peppermint oil", "tea tree oil",
                       "melaleuca alternifolia leaf oil"},
}

# Groups a user can choose to avoid as a whole ("avoid fragrance" also catches
# label-declared fragrance components and essential oils).
GROUPS: dict[str, set[str]] = {
    "fragrance": {"fragrance", "linalool", "limonene", "citronellol", "geraniol", "essential oils"},
}

_LOOKUP = {spelling: key for key, spellings in SYNONYMS.items() for spelling in spellings}


def clean(name: str) -> str:
    s = name.lower().strip()
    s = re.sub(r"\d+(\.\d+)?\s*%", "", s)          # strip percentages
    s = s.replace("/", " ").replace("(", " ").replace(")", " ")
    s = re.sub(r"[^a-z0-9\-\. ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip().rstrip(".")
    return s


def canonical(name: str) -> str:
    c = clean(name)
    if c in _LOOKUP:
        return _LOOKUP[c]
    return c


def canonical_list(names: list[str]) -> list[str]:
    return [canonical(n) for n in names if clean(n)]


def expand_avoid(term: str) -> set[str]:
    """What a user means by 'avoid X': the canonical key plus its group members."""
    key = canonical(term)
    return GROUPS.get(key, set()) | {key}
