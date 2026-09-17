"""Model backends. Everything above this layer talks to `LLMClient`."""

from notetaker.llm.base import LLMClient, LLMError
from notetaker.llm.fake import FakeLLM

__all__ = ["FakeLLM", "LLMClient", "LLMError"]
