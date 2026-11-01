"""Claim linter: no user-facing sentence may overclaim.

    python scripts/claim_lint.py          # prints every finding; exit 1 if any

Scans
  * every .ts/.tsx file in frontend/src, with comments removed (so strings and JSX text,
    which is everything a user can read, are checked; identifiers rarely match these words);
  * every string constant in backend/app/**/*.py (docstrings excluded): the verdict template
    sentences, rebuy lines, refusal fixes, exclusion reasons and error messages users see.

Fails on: cause / caused by, cure, treat, diagnose, prove / proven, guarantee, clinically,
"it works", and a percentage improvement claim ("30% fewer breakouts", "reduces redness by 20%").
Words in the same family count (causes, cured, treating, diagnosed, proves...). "Treatment" (the
routine step) and "diagnosis" (as in "not diagnosis") are different words and are not flagged.

An exception needs an entry in ALLOW with a written reason. tests/test_claim_linter.py runs this
in CI, and BRANDS below keeps real brand and retailer names out of the catalog, fixtures and UI.
"""
from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
FRONTEND_SRC = ROOT / "frontend" / "src"
APP = BACKEND / "app"

RULES: list[tuple[str, re.Pattern]] = [
    ("cause", re.compile(r"\bcaus(e|es|ed|ing)\b", re.I)),
    ("cure", re.compile(r"\bcur(e|es|ed|ing)\b", re.I)),
    ("treat", re.compile(r"\btreat(s|ed|ing)?\b", re.I)),
    ("diagnose", re.compile(r"\bdiagnos(e|es|ed|ing)\b", re.I)),
    ("prove", re.compile(r"\bprov(e|es|ed|en|ing)\b", re.I)),
    ("guarantee", re.compile(r"\bguarantee(s|d|ing)?\b", re.I)),
    ("clinically", re.compile(r"\bclinically\b", re.I)),
    ("it works", re.compile(r"\bit works\b", re.I)),
    # ---- added for the three moments (docs/STRATEGY.md section 4, rule 9: the wording ceiling).
    #
    # Two of these four are written as claim SHAPES rather than as bare words, and that is on
    # purpose. "Fix" and "work" are both ordinary vocabulary in this codebase with a meaning that
    # is the opposite of a claim: a comparability `fix` is what to do on the retake, and "the spot
    # where you took them works best" is advice about a photo. Banning the bare words would mean
    # an allowlist entry on nearly every screen, which stops the linter meaning anything. What is
    # actually forbidden is the claim: a product fixing, or working on, a person or their skin.
    #
    # "allergy" is broad on purpose, because the only legitimate use is about a clinician-confirmed
    # record. Every one of those names the record type and is listed in ALLOW with its reason,
    # which is exactly the "outside a clinician-confirmed record" carve-out.
    ("allergy", re.compile(r"\ballerg(y|ies|ic)\b", re.I)),
    # Never "safe". "Unsafe", "safety" and "safely" are different words and are not flagged.
    ("safe", re.compile(r"\bsafe\b", re.I)),
    # A product working: "it works", "this worked", "works for you", "working on my skin".
    # Not flagged: "works best" (about a spot or a photo), "worked out" (computed by the engine),
    # and "Is my product working?", which is a question the user asks, not an answer we give.
    ("works", re.compile(
        r"\b(it|this|that|they|these|the (?:product|serum|cream|routine|moisturiser|sunscreen))\s+"
        r"(?:really\s+|definitely\s+|actually\s+)?work(?:s|ed)\b"
        r"|\bwork(?:s|ed|ing)\s+(?:for|on)\s+(?:you|your|me|my|her|his|their)\b"
        r"|\bdoes\s+work\b|\bwill\s+work\b", re.I)),
    # A product fixing something: "fixes your skin", "fixed my acne", "will fix it".
    # Not flagged: "holding fixed" (the name of the trial design), "fixed rules" (how the engine
    # works), or a comparability "fix" (the retake instruction).
    ("fixes", re.compile(
        r"\bfix(?:es|ed|ing)?\s+(?:your|my|her|his|their|the)?\s*"
        r"(?:skin|face|redness|acne|pores?|breakouts?|texture|oiliness|dryness|moisture|it|this)\b",
        re.I)),
    ("% improvement", re.compile(
        r"\b\d+(\.\d+)?\s*%\s*(better|improve\w*|less|fewer|more|smoother|clearer|brighter|firmer|lighter|"
        r"reduc\w*|decreas\w*|increas\w*|drop\w*)\b"
        r"|\b(improv\w*|reduc\w*|decreas\w*|increas\w*|drop\w*|cut\w*|lower\w*|boost\w*)\b[\w ]{0,30}?\bby\s+\d+(\.\d+)?\s*%",
        re.I)),
]


# ---- Strategy v2: the shopping flow (docs/strategy.md sections 4 and 9).
# Two more rules, applied only to the files of the basket flow: no score or points shown to a
# shopper, and never "can't tell" (a missing measurement is filled from the answers and labelled).
# They are scoped to these files because the optional check-in still talks about its own
# measurements and its "can't tell yet" verdict, which is correct there.
SHOPPING_FILES = {
    "frontend/src/screens/Basket.tsx",
    "frontend/src/components/FaceMap.tsx",
    "frontend/src/basketCopy.ts",
    "backend/app/basket.py",
    "backend/app/needs.py",
    "backend/app/undertone.py",
    "backend/app/demo_faces.py",
}
SHOPPING_RULES: list[tuple[str, re.Pattern]] = [
    ("score shown", re.compile(r"\b(scores?|points?|/\s?100)\b", re.I)),
    ("can't tell", re.compile(r"\bcan['’]?t tell\b|\bcannot tell\b|\bunable to tell\b", re.I)),
]


@dataclass(frozen=True)
class Allow:
    file: str      # path relative to the repo root, forward slashes
    text: str      # exact substring of the flagged line or string
    reason: str


# Every exception, with why it is not a user-facing claim.
ALLOW: list[Allow] = [
    Allow("backend/app/llm/explain.py", "Never say a product caused, fixed, worked or led to anything",
          "Instruction to the language model listing what it must never say; never shown to users."),
    Allow("backend/app/llm/explain.py", r"\b(prove[sn]?|proof|definitely",
          "Claim-validator pattern that rejects overclaiming in model drafts; never shown to users."),

    # ---- "allergy", only ever about the clinician-confirmed record type.
    # derm//os has three history record types, and one of them IS a clinician-confirmed allergy
    # (app/decision.py RecordType.CONFIRMED_ALLERGY). Naming that record is the carve-out: the
    # banned use is calling a reaction of the user's own an allergy, which none of these do.
    Allow("frontend/src/copy.ts", "It doesn't turn any ingredient into an allergy",
          "The rule text for the reaction record type, saying the opposite of the banned claim: a "
          "product that bothered you is not an allergy."),
    Allow("frontend/src/copy.ts", "Clinician-confirmed allergy",
          "The on-screen name of the clinician-confirmed record type, which is the one context "
          "docs/STRATEGY.md allows the word in."),
    Allow("frontend/src/screens/History.tsx", "an ingredient you avoid by choice and a clinician-confirmed allergy",
          "Explains how the three record types differ, naming the clinician-confirmed one. It is "
          "about a record, not about the user's skin."),
    Allow("frontend/src/screens/History.tsx", "my dermat said I'm allergic to lanolin",
          "An example of the user's OWN words in the free-text box, shown so they know what to "
          "type. The app's reply to that text proposes 'avoid by choice' unless a clinician is named."),
    Allow("backend/app/decision.py", "Avoid / confirmed allergy records must name an ingredient",
          "A validation error about the clinician-confirmed record type, naming that type."),
    Allow("backend/app/decision.py", "you have a confirmed allergy to",
          "The exclusion reason shown only for a clinician-confirmed record, which is what makes "
          "the word accurate here."),
    Allow("backend/app/llm/intake.py", "ingredient_allergy: the user says they are allergic to an ingredient",
          "Instruction to the extraction model describing one record kind; never shown to users, "
          "and the proposal it produces is downgraded to 'avoid' unless a clinician is named."),
    Allow("backend/app/llm/intake.py", "The text doesn't say a clinician confirmed this allergy",
          "The hint shown when the app REFUSES to file something as an allergy, which is the rule "
          "being enforced rather than broken."),

    # ---- "worked for you": the user's own "suited me" chip, echoed back. Not a product claim.
    # One entry covers both places in chips.py (the chip read-back and the basket card line).
    Allow("backend/app/chips.py", "worked for you.",
          "the user's own 'suited me' report read back to them"),
    Allow("backend/app/lookfor.py", "Worked for you before:",
          "the user's own 'suited me' report read back to them"),
]

# Real cosmetic brands and retailers that must never appear (all products are fictional).
BRANDS = [
    "CeraVe", "Cetaphil", "Neutrogena", "The Ordinary", "Minimalist", "Mamaearth", "Plum Goodness", "Dot & Key",
    "Foxtale", "Re'equil", "Deconstruct", "The Derma Co", "Paula's Choice", "COSRX", "Innisfree", "Laneige",
    "La Roche-Posay", "Bioderma", "Avène", "Avene", "Vichy", "Eucerin", "Aveeno", "Olay", "L'Oréal", "L'Oreal",
    "Garnier", "Nivea", "Clinique", "Estée Lauder", "Estee Lauder", "Kiehl's", "Lakmé", "Lakme", "Himalaya",
    "Biotique", "Lotus Herbals", "Pond's", "Ponds", "Sebamed", "Glossier", "Drunk Elephant", "Tatcha", "Fenty",
    "Clean & Clear", "Simple Skincare", "Dove", "Vaseline", "Bioré", "Biore", "Shiseido", "SK-II", "Sunday Riley",
    "Kama Ayurveda", "Forest Essentials", "Wishcare", "Pilgrim", "Conscious Chemist", "Aqualogica", "Cosrx",
    "Nykaa", "Sephora", "Ulta", "Purplle", "Tira", "Myntra", "Amazon", "Flipkart", "Boots", "Watsons",
    "Superdrug", "Target", "Walmart", "Perfect Corp", "YouCam Makeup",
]
# "YouCam" and "Perfect Corp" appear as the API provider credit. Only product-like uses are checked:
BRAND_ALLOWED_CONTEXT = {"Perfect Corp", "YouCam Makeup"}


@dataclass(frozen=True)
class Finding:
    file: str
    line: int
    rule: str
    text: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: [{self.rule}] {self.text}"


# -- TypeScript / TSX ----------------------------------------------------------------------

_BLOCK = re.compile(r"/\*.*?\*/", re.S)
# A line comment starts with // at the start of a line or after whitespace, followed by a space or the
# end of the line. That keeps "derm//os" in JSX text and "https://" in strings, which a tokenizer would
# get wrong (JSX text is not a string, so its apostrophes don't open quotes).
_LINE = re.compile(r"(^|\s)//(\s.*|)$", re.M)


def strip_ts_comments(src: str) -> str:
    """Remove /* */ and // comments. Newlines are kept so line numbers stay right."""
    src = _BLOCK.sub(lambda m: "\n" * m.group(0).count("\n"), src)
    return _LINE.sub(lambda m: m.group(1), src)


def ts_texts(path: Path) -> list[tuple[int, str]]:
    code = strip_ts_comments(path.read_text(encoding="utf-8"))
    # JSX comments {/* ... */} leave an empty {} behind, which is harmless.
    return [(i, line) for i, line in enumerate(code.splitlines(), 1) if line.strip()]


# -- Python --------------------------------------------------------------------------------

def py_texts(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            out.append((node.lineno, node.value))
    return out


# -- run -----------------------------------------------------------------------------------

def rel(p: Path) -> str:
    return p.resolve().relative_to(ROOT).as_posix()


def sources() -> list[tuple[str, list[tuple[int, str]]]]:
    out = []
    for p in sorted(FRONTEND_SRC.rglob("*.ts")) + sorted(FRONTEND_SRC.rglob("*.tsx")):
        out.append((rel(p), ts_texts(p)))
    for p in sorted(APP.rglob("*.py")):
        out.append((rel(p), py_texts(p)))
    return out


def allowed(file: str, text: str) -> Allow | None:
    return next((a for a in ALLOW if a.file == file and a.text in text), None)


def lint(srcs=None) -> tuple[list[Finding], list[tuple[Finding, Allow]]]:
    findings, excused = [], []
    for file, texts in (srcs if srcs is not None else sources()):
        rules = RULES + (SHOPPING_RULES if file in SHOPPING_FILES else [])
        for line, text in texts:
            for rule, rx in rules:
                if rx.search(text):
                    f = Finding(file, line, rule, text.strip()[:200])
                    a = allowed(file, text)
                    (excused.append((f, a)) if a else findings.append(f))
    return findings, excused


def brand_hits() -> list[Finding]:
    """Real brand or retailer names in the catalog, fixtures or frontend source (should be none)."""
    files = [APP / "catalog.json", *sorted((BACKEND / "fixtures").rglob("*.json")),
             *sorted(FRONTEND_SRC.rglob("*.ts")), *sorted(FRONTEND_SRC.rglob("*.tsx")),
             *sorted((ROOT / "frontend" / "public").rglob("*.*"))]
    hits = []
    for p in files:
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".ico"):
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            for b in BRANDS:
                if b in BRAND_ALLOWED_CONTEXT:
                    continue
                if re.search(rf"(?<![A-Za-z]){re.escape(b)}(?![A-Za-z])", line):
                    hits.append(Finding(rel(p), i, f"brand: {b}", line.strip()[:160]))
    return hits


def main() -> int:
    # User-facing copy contains characters a Windows console's default code page can't print
    # (curly quotes, the arrow in "incomplete -> unknown"). The linter must report, not crash.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - not a reconfigurable stream
        pass
    findings, excused = lint()
    for f, a in excused:
        print(f"allowed  {f}\n         reason: {a.reason}")
    for f in findings:
        print(f"FAIL     {f}")
    brands = brand_hits()
    for b in brands:
        print(f"FAIL     {b}")
    print(f"\n{len(findings)} claim finding(s), {len(excused)} allowed with a reason, {len(brands)} brand name(s).")
    return 1 if findings or brands else 0


if __name__ == "__main__":
    sys.exit(main())
