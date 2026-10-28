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
    ("% improvement", re.compile(
        r"\b\d+(\.\d+)?\s*%\s*(better|improve\w*|less|fewer|more|smoother|clearer|brighter|firmer|lighter|"
        r"reduc\w*|decreas\w*|increas\w*|drop\w*)\b"
        r"|\b(improv\w*|reduc\w*|decreas\w*|increas\w*|drop\w*|cut\w*|lower\w*|boost\w*)\b[\w ]{0,30}?\bby\s+\d+(\.\d+)?\s*%",
        re.I)),
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
        for line, text in texts:
            for rule, rx in RULES:
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
