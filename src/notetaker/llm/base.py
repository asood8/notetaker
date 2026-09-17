"""The interface the rest of the package codes against."""

from __future__ import annotations

from typing import Any, Protocol


class LLMError(RuntimeError):
    """A backend could not produce usable output."""


class LLMClient(Protocol):
    """Anything that can turn a prompt into JSON matching a schema.

    Keeping this narrow is what lets the whole pipeline be tested without
    Ollama running: `FakeLLM` satisfies it in a few dozen lines.
    """

    name: str

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Return parsed JSON that conforms to `schema`, or raise `LLMError`."""
        ...
