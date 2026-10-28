"""Language layer, no network: the LLM extracts and words; rules decide; any failure -> templates."""
import importlib
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import decision as D
from app import evidence as E
from app.fingerprint import Fingerprint
from app.llm import explain as X
from app.llm import intake as I
from app.llm import providers as P
from benchmark.fakes import ScriptedProvider

CAT = D.load_catalog()
USER_TEXT = ("I broke out from a fragranced moisturiser last year and my dermat said I'm allergic to lanolin")


def caps(*scores):
    return [E.Capture({"redness": s}, Fingerprint(1080, 1440, 0.55, 1.2, "PhoneX", 10, 0.7, 0, 0, 0), "sd")
            for s in scores]


def record(base, follow, confirmed=False):
    rep = E.evaluate(base, follow, E.TrialContext(), concerns=["redness"]).to_dict()
    return X.record_for(rep, CAT["sr-04"], "redness", confirmed), rep["message"]


NO_CHANGE, _ = record(caps(60, 64), caps(62, 63))
MOVED, _ = record(caps(60, 62), caps(70, 71))
NOT_COMP = X.record_for({**E.evaluate(caps(60, 62), caps(70, 71), E.TrialContext(2)).to_dict()},
                        CAT["sr-04"], "redness")


# ---------------------------------------------------------------- claim validator
@pytest.mark.parametrize("draft,reason", [
    ("Calm Centella Serum caused your redness to settle.", "causal_wording"),
    ("Your redness is lower because of the serum.", "causal_wording"),
    ("The serum worked on your redness.", "causal_wording"),
    ("This looks like rosacea.", "diagnosis_word"),
    ("You may have an allergy.", "diagnosis_word"),
    ("Your scores sit inside your range, unlike with Velvet Rose Moisturiser.", "name_not_in_record"),
    ("Your scores sit inside your range; niacinamide might help.", "name_not_in_record"),
    ("Your redness improved during this trial.", "stronger_verdict"),
    ("This proves the serum is effective.", "stronger_verdict"),
    ("Your redness score moved by 17 points.", "number_not_in_record"),
])
def test_validator_rejects_each_banned_category(draft, reason):
    assert X.validate(draft, NO_CHANGE, CAT) == reason


def test_validator_accepts_a_clean_draft():
    draft = ("Your redness scores at this check-in sit inside your own baseline range of 60 to 64. "
             "That means no detectable change yet while using Calm Centella Serum.")
    assert X.validate(draft, NO_CHANGE, CAT) is None


def test_allergy_word_allowed_only_when_clinician_confirmed():
    d = "Your clinician-confirmed allergy is on record; your redness sits inside your range."
    assert X.validate(d, NO_CHANGE, CAT) == "diagnosis_word"
    confirmed = {**NO_CHANGE, "clinician_confirmed_allergy": True}
    assert X.validate(d, confirmed, CAT) is None


def test_cant_tell_cannot_be_worded_as_no_change():
    assert X.validate("There was no change in your redness.", NOT_COMP, CAT) == "stronger_verdict"


def test_moved_direction_must_match_the_record():
    assert MOVED["findings"][0]["direction"] == "better"
    assert X.validate("Your redness looks better during this trial.", MOVED, CAT) is None
    assert X.validate("Your redness looks worse during this trial.", MOVED, CAT) == "stronger_verdict"


def test_more_than_three_sentences_rejected():
    assert X.validate("One. Two. Three. Four.", NO_CHANGE, CAT) == "sentence_count"


# ---------------------------------------------------------------- explain fallbacks
def test_llm_off_returns_template():
    out = X.explain(NO_CHANGE, "TEMPLATE", CAT, None)
    assert out == {"text": "TEMPLATE", "source": "template", "rejected": None}


def test_provider_failure_retries_once_then_template():
    p = ScriptedProvider(TimeoutError(), httpx.ConnectError("x"))
    out = X.explain(NO_CHANGE, "TEMPLATE", CAT, p)
    assert out["source"] == "template" and out["text"] == "TEMPLATE" and len(p.calls) == 2


def test_one_retry_recovers():
    p = ScriptedProvider(TimeoutError(), "Your redness sits inside your own range.")
    assert X.explain(NO_CHANGE, "T", CAT, p)["source"] == "llm"


def test_rejected_draft_shows_template_and_logs_reason_not_text(caplog):
    p = ScriptedProvider("The serum caused a SECRET-DRAFT change.")
    with caplog.at_level("INFO", logger="dermos.llm"):
        out = X.explain(NO_CHANGE, "T", CAT, p)
    assert out == {"text": "T", "source": "template", "rejected": "causal_wording"}
    assert "causal_wording" in caplog.text and "SECRET-DRAFT" not in caplog.text


def test_llm_sees_only_the_structured_record():
    p = ScriptedProvider("Your redness sits inside your own range.")
    X.explain(NO_CHANGE, "T", CAT, p)
    assert json.loads(p.calls[0][1]) == NO_CHANGE


# ---------------------------------------------------------------- intake
def items(*recs):
    return json.dumps({"records": [{"product": None, "ingredient": None, "clinician_confirmed": False, **r} for r in recs]})


def test_user_example_is_split_into_the_right_record_types():
    p = ScriptedProvider(items(
        {"kind": "product_reaction", "product": "fragranced moisturiser", "quote": "I broke out from a fragranced moisturiser"},
        {"kind": "ingredient_allergy", "ingredient": "lanolin", "clinician_confirmed": True,
         "quote": "my dermat said I'm allergic to lanolin"},
    ))
    out = I.propose(USER_TEXT, CAT, p)
    a, b = out["proposals"]
    assert a["type"] == "suspected_reaction" and a["product_id"] is None and not a["product_matched"]
    assert a["product_text"] == "fragranced moisturiser" and "product_id" in a["needs_confirmation"]
    assert a["ingredient"] is None
    assert b["type"] == "confirmed_allergy" and b["ingredient"] == "lanolin" and b["needs_confirmation"] == []


def test_product_reaction_stays_product_level():
    text = "Velvet Rose Moisturiser made me itchy, probably the fragrance."
    p = ScriptedProvider(items({"kind": "product_reaction", "product": "Velvet Rose Moisturiser",
                                "ingredient": "fragrance", "clinician_confirmed": True, "quote": text}))
    (r,) = I.propose(text, CAT, p)["proposals"]
    assert r["type"] == "suspected_reaction" and r["product_id"] == "mo-02" and r["ingredient"] is None


def test_allergy_without_clinician_is_not_confirmed():
    text = "I think I'm allergic to lanolin."
    p = ScriptedProvider(items({"kind": "ingredient_allergy", "ingredient": "lanolin", "clinician_confirmed": True,
                                "quote": text}))
    (r,) = I.propose(text, CAT, p)["proposals"]
    assert r["type"] == "avoid" and "type" in r["needs_confirmation"]


def test_unclear_fields_need_confirmation_and_invented_values_are_dropped():
    text = "Something in my old cream stung."
    p = ScriptedProvider(items({"kind": "ingredient_avoid", "ingredient": "alcohol denat", "quote": text}))
    (r,) = I.propose(text, CAT, p)["proposals"]
    assert r["ingredient"] is None and "ingredient" in r["needs_confirmation"]


@pytest.mark.parametrize("raw,reason", [
    ("Sure! Here are the records.", "not_json"),
    ('{"records": [], "extra": 1}', "wrong_shape"),
    ('{"records": [{"kind": "diagnosis", "product": null, "ingredient": null, "clinician_confirmed": false, "quote": "x"}]}',
     "unknown_kind"),
    ('{"records": [{"kind": "ingredient_avoid", "ingredient": "x", "quote": "x"}]}', "wrong_record_keys"),
])
def test_bad_json_is_rejected(raw, reason):
    out = I.propose("I avoid x", CAT, ScriptedProvider(raw))
    assert out["proposals"] == [] and out["rejected"] == reason


def test_quote_not_in_text_is_dropped():
    p = ScriptedProvider(items({"kind": "ingredient_avoid", "ingredient": "retinol", "quote": "I avoid retinol"}))
    out = I.propose("I avoid fragrance", CAT, p)
    assert out["proposals"] == [] and out["dropped"] == 1


def test_intake_provider_failure_is_reported_not_raised():
    out = I.propose("I avoid fragrance", CAT, ScriptedProvider(TimeoutError(), TimeoutError()))
    assert out["proposals"] == [] and out["rejected"] == "provider_failed"


def test_catalog_matching_only():
    assert I.match_product("Lumen & Leaf Velvet Rose Moisturiser", CAT) == ("mo-02", True)
    assert I.match_product("velvet rose", CAT) == ("mo-02", False)
    assert I.match_product("GlowMax 3000 cream", CAT) == (None, False)


# ---------------------------------------------------------------- providers
def test_provider_selection_from_env(monkeypatch):
    assert P.get_provider() is None
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    assert P.get_provider() is None                      # no key -> off, not a crash
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-secret")
    p = P.get_provider()
    assert p.name == "anthropic" and "sk-test-secret" not in repr(p)
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    assert P.get_provider() is None                      # needs base URL + model
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen3:4b")
    assert P.get_provider().name == "openai_compatible"


def test_http_providers_parse_and_fail_closed(caplog):
    def handler(req: httpx.Request):
        if "anthropic" in str(req.url):
            assert req.headers["x-api-key"] == "sk-secret"
            return httpx.Response(200, json={"content": [{"type": "text", "text": "hello"}]})
        return httpx.Response(500, json={})
    http = httpx.Client(transport=httpx.MockTransport(handler))
    assert P.AnthropicProvider("sk-secret", "m", http).complete("s", "u") == "hello"
    oa = P.OpenAICompatibleProvider("http://127.0.0.1:1/v1", "m", "sk-secret", http)
    with caplog.at_level("WARNING", logger="dermos.llm"):
        assert P.call(oa, "s", "u") is None
    assert "HTTP 500" in caplog.text and "sk-secret" not in caplog.text


# ---------------------------------------------------------------- API
@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DERMOS_DB", str(tmp_path / "t.db"))
    monkeypatch.setenv("DERMOS_MEDIA", str(tmp_path / "media"))
    import app.main as m
    m = importlib.reload(m)
    return m, TestClient(m.app)


def test_intake_never_saves(client, monkeypatch):
    m, c = client
    monkeypatch.setattr(m.L, "get_provider", lambda: ScriptedProvider(items(
        {"kind": "ingredient_allergy", "ingredient": "lanolin", "clinician_confirmed": True,
         "quote": "my dermat said I'm allergic to lanolin"})))
    r = c.post("/api/history/intake", json={"text": USER_TEXT}).json()
    assert r["available"] and r["proposals"][0]["type"] == "confirmed_allergy"
    assert c.get("/api/history").json() == []


def test_intake_with_llm_off(client):
    _, c = client
    assert c.post("/api/history/intake", json={"text": USER_TEXT}).json() == {
        "available": False, "proposals": [], "rejected": None, "dropped": 0}
    assert c.get("/api/health").json()["llm"] is False


def test_ollama_needs_no_key_and_defaults_to_local(monkeypatch):
    from app.llm import providers as PR
    for k in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    p = PR.get_provider()
    assert p is not None and p.name == "ollama" and p._key is None
    assert p.base_url == "http://127.0.0.1:11434/v1" and p.model == PR.DEFAULT_OLLAMA_MODEL
    assert p.timeout == PR.DEFAULT_OLLAMA_TIMEOUT          # a local model is slow; LLM_TIMEOUT overrides
    monkeypatch.setenv("LLM_TIMEOUT", "30")
    assert PR.get_provider().timeout is None
    monkeypatch.delenv("LLM_TIMEOUT")
    monkeypatch.setenv("LLM_MODEL", "gemma4:e2b")
    assert PR.get_provider().model == "gemma4:e2b"


def test_ollama_not_running_falls_back_to_templates(monkeypatch):
    """Nothing listening: the call fails, call() returns None, the app shows its fixed wording."""
    import httpx
    from app.llm import providers as PR

    def refuse(req):
        raise httpx.ConnectError("refused")
    p = PR.OpenAICompatibleProvider("http://127.0.0.1:11434/v1", "m", None,
                                    http=httpx.Client(transport=httpx.MockTransport(refuse)), name="ollama")
    assert PR.call(p, "s", "u") is None
