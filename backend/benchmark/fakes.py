"""A scripted stand-in for an LLM provider: no network, no key. Used by the benchmark and tests."""
from __future__ import annotations


class ScriptedProvider:
    """Returns the scripted outputs in order. An Exception instance in the script is raised instead."""
    name = "scripted"

    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        out = self.outputs.pop(0) if self.outputs else RuntimeError("script exhausted")
        if isinstance(out, Exception):
            raise out
        return out
