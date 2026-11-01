"""Demo faces for the basket flow.

Riya's face now comes from fixtures/riya/basket_face.json: the values of one live scan
(2026-11-01: skin_type + 7 concerns, and Skin Tone), cleaned to values only. Her history and shelf
stay fictional, so every screen still carries the "Demo data" tag, and with no recorded render the
try-on says "Preview appears on a live scan". The hand-made entry below (SYNTHETIC, nothing from a
YouCam call) is the fallback when that file is absent.

Shapes:
  * skin analysis (format=json): data.results.output[], one item per action. skin_type carries the
    documented subcategories whole / t_zone / u_zone; the concern items carry raw_score/ui_score.
  * skin tone (AI Facial Color Tones Analyzer): data.results.color.skin_color, a #rrggbb colour,
    plus face_quality. The undertone is not in the response; app/undertone.py derives it.
"""
from __future__ import annotations

DEMO_FACES: dict[str, dict] = {
    # Riya: combination (oily T-zone, dry cheeks), warm-neutral, wants dewy.
    "riya": {
        "synthetic": True,
        "label": "Demo data",
        "skin": {"data": {"task_status": "success", "results": {"output": [
            {"type": "skin_type", "whole": {"skin_type": "Combination"},
             "t_zone": {"skin_type": "Oily"}, "u_zone": {"skin_type": "Dry"}},
            {"type": "oiliness", "raw_score": 48.0, "ui_score": 70},
            {"type": "moisture", "raw_score": 44.0, "ui_score": 66},
            {"type": "pore", "raw_score": 55.2, "ui_score": 74},
            {"type": "acne", "raw_score": 72.2, "ui_score": 84},
            {"type": "redness", "raw_score": 62.1, "ui_score": 80},
            {"type": "radiance", "raw_score": 52.0, "ui_score": 72},
            {"type": "texture", "raw_score": 58.6, "ui_score": 77},
        ]}}},
        "tone": {"data": {"task_status": "success", "results": {
            "face_quality": {"has_face": True, "area": "good", "frontal": "good", "lighting": "good",
                             "faceangle": "good"},
            "color": {"skin_color": "#b9947c", "eye_color": "#4a3324", "lip_color": "#b06a5e",
                      "eyebrow_color": "#2e2119", "hair_color": "#241a14"}}}},
        "answers": {"finish": "dewy", "history": "use", "budget": "any"},
    },
    # A beginner: nothing tried yet, so the history step is skipped ("history": "new") and the
    # basket leans to gentle, fragrance-free, low-active products. Hand-made values, labelled.
    "beginner": {
        "synthetic": True,
        "label": "Demo data",
        "skin": {"data": {"task_status": "success", "results": {"output": [
            {"type": "skin_type", "whole": {"skin_type": "Normal"},
             "t_zone": {"skin_type": "Normal"}, "u_zone": {"skin_type": "Normal"}},
            {"type": "oiliness", "raw_score": 66.0, "ui_score": 78},
            {"type": "moisture", "raw_score": 64.0, "ui_score": 77},
            {"type": "pore", "raw_score": 70.0, "ui_score": 80},
            {"type": "acne", "raw_score": 81.0, "ui_score": 88},
            {"type": "redness", "raw_score": 74.0, "ui_score": 83},
            {"type": "radiance", "raw_score": 68.0, "ui_score": 79},
            {"type": "texture", "raw_score": 72.0, "ui_score": 82},
        ]}}},
        "tone": {"data": {"task_status": "success", "results": {
            "face_quality": {"has_face": True, "area": "good", "frontal": "good", "lighting": "good",
                             "faceangle": "good"},
            "color": {"skin_color": "#c8a07c"}}}},
        "answers": {"finish": "natural", "history": "new", "budget": "any"},
    },
}

# The SD actions one live basket scan asks for: skin_type plus the seven concerns (5-8 tier).
BASKET_ACTIONS = ["skin_type", "oiliness", "moisture", "pore", "acne", "redness", "radiance", "texture"]


def load_face(persona: str) -> dict | None:
    """A recorded basket face (fixtures/<persona>/basket_face.json, written by the live session
    from a real response, sanitised) wins over the synthetic one. It sits beside the persona's
    scan sets, not inside one, so the scan replay never mistakes it for a skin-analysis fixture."""
    import json
    from . import demo

    if not demo._SAFE.match(persona or ""):
        return None
    path = demo.fixtures_dir() / persona / "basket_face.json"
    if path.is_file():
        blob = json.loads(path.read_text(encoding="utf-8"))
        # Still the demo persona, so it keeps the "Demo data" tag; `source` says where the values came from.
        return {"synthetic": bool(blob.get("synthetic", False)),
                "label": blob.get("label") or "Demo data", "source": blob.get("source"),
                "skin": blob.get("skin"), "tone": blob.get("tone"), "renders": blob.get("renders") or {},
                "answers": blob.get("answers") or {}}
    face = DEMO_FACES.get(persona)
    return {**face, "renders": {}} if face else None
