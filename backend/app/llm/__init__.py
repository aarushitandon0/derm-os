"""Language layer: intake extraction and explanations. Rules decide; the LLM only extracts and words."""
from .explain import explain as explain_result
from .explain import record_for, validate
from .intake import propose
from .providers import get_provider

__all__ = ["explain_result", "get_provider", "propose", "record_for", "validate"]
