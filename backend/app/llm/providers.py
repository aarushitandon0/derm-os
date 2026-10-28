"""One adapter interface, chosen by LLM_PROVIDER = none | anthropic | openai_compatible.

The LLM never decides anything. It only turns free text into proposed records the user
confirms, and words results a validator checks. Every failure (no key, timeout, HTTP
error, odd response) ends in a template, so the app works the same with it off.

Keys come from the environment only and are never logged.
"""
from __future__ import annotations

import logging
import os
from typing import Protocol

import httpx

log = logging.getLogger("dermos.llm")

DEFAULT_ANTHROPIC_MODEL = "claude-haiku-5-5"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


class LLMError(Exception):
    """Any provider failure. The message never contains a key or the prompt."""


class Provider(Protocol):
    name: str

    def complete(self, system: str, user: str) -> str: ...


def _timeout() -> float:
    try:
        return max(1.0, float(os.environ.get("LLM_TIMEOUT", "12")))
    except ValueError:
        return 12.0


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, http: httpx.Client | None = None):
        self._key = api_key
        self.model = model
        self._http = http

    def __repr__(self) -> str:   # never show the key
        return f"AnthropicProvider(model={self.model!r})"

    def complete(self, system: str, user: str) -> str:
        body = {"model": self.model, "max_tokens": 700, "temperature": 0, "system": system,
                "messages": [{"role": "user", "content": user}]}
        headers = {"x-api-key": self._key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
        data = _post(self._http, ANTHROPIC_URL, body, headers)
        try:
            return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
        except (KeyError, TypeError, AttributeError) as e:
            raise LLMError("unexpected response shape") from e


class OpenAICompatibleProvider:
    """Groq, Gemini's OpenAI endpoint, local Ollama (http://127.0.0.1:11434/v1) and similar."""
    name = "openai_compatible"

    def __init__(self, base_url: str, model: str, api_key: str | None = None, http: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._key = api_key
        self._http = http

    def __repr__(self) -> str:
        return f"OpenAICompatibleProvider(base_url={self.base_url!r}, model={self.model!r})"

    def complete(self, system: str, user: str) -> str:
        body = {"model": self.model, "temperature": 0,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        headers = {"content-type": "application/json"}
        if self._key:
            headers["authorization"] = f"Bearer {self._key}"
        data = _post(self._http, f"{self.base_url}/chat/completions", body, headers)
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise LLMError("unexpected response shape") from e


def _post(http: httpx.Client | None, url: str, body: dict, headers: dict) -> dict:
    try:
        if http is not None:
            r = http.post(url, json=body, headers=headers, timeout=_timeout())
        else:
            with httpx.Client(timeout=_timeout()) as c:
                r = c.post(url, json=body, headers=headers)
    except httpx.HTTPError as e:
        raise LLMError(type(e).__name__) from None
    if r.status_code >= 400:
        raise LLMError(f"HTTP {r.status_code}")
    try:
        return r.json()
    except ValueError:
        raise LLMError("response was not JSON") from None


def get_provider() -> Provider | None:
    """The configured provider, or None when the LLM is off or misconfigured. Read on every call
    so a changed environment takes effect without a restart (and tests can set it)."""
    kind = os.environ.get("LLM_PROVIDER", "none").strip().lower()
    if kind in ("", "none", "off", "0"):
        return None
    model = os.environ.get("LLM_MODEL", "").strip()
    if kind == "anthropic":
        key = (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("LLM_API_KEY") or "").strip()
        if not key:
            log.warning("LLM_PROVIDER=anthropic but no ANTHROPIC_API_KEY is set; using templates.")
            return None
        return AnthropicProvider(key, model or DEFAULT_ANTHROPIC_MODEL)
    if kind == "openai_compatible":
        base = os.environ.get("LLM_BASE_URL", "").strip()
        if not base or not model:
            log.warning("LLM_PROVIDER=openai_compatible needs LLM_BASE_URL and LLM_MODEL; using templates.")
            return None
        return OpenAICompatibleProvider(base, model, (os.environ.get("LLM_API_KEY") or "").strip() or None)
    log.warning("Unknown LLM_PROVIDER %r; using templates.", kind)
    return None


def call(provider: Provider, system: str, user: str) -> str | None:
    """One try plus one retry. Returns None on any failure (logged without prompt, output or key)."""
    for attempt in (1, 2):
        try:
            return provider.complete(system, user)
        except Exception as e:  # noqa: BLE001 - any failure falls back to templates
            reason = str(e) if isinstance(e, LLMError) else type(e).__name__
            log.warning("LLM call failed (%s, attempt %d of 2): %s", provider.name, attempt, reason)
    return None
