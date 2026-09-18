"""The Ollama backend.

Two things here are less obvious than they look, and both were found by
measuring rather than by reading docs:

`num_ctx` is set explicitly. Ollama's default context window is small, and it
truncates silently -- notes just vanish from the end of a chunk, which looks
like the model ignoring half the input rather than like a configuration
problem.

The `think` parameter is never sent. Setting `think: false` makes some models
(the qwen3.5 family, at least) stop honoring the `format` schema and return
markdown instead. Leaving it unset keeps schema-constrained decoding working.
The cost is that reasoning models are unusably slow for this job, so the
timeout error says so.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

from notetaker.llm.base import LLMError

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "llama3.2"
DEFAULT_NUM_CTX = 8192
DEFAULT_TIMEOUT = 180.0
DEFAULT_SEED = 7

THINK_TAG_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

REASONING_MODELS = (
    "deepseek-r1",
    "qwen3",
    "qwq",
    "magistral",
    "exaone-deep",
    "phi4-reasoning",
)
"""Families that reason before answering, which makes them unusable here.

`deepseek-r1` and the `qwen3.5` line were measured: over 280 seconds for a
single short section, on an already-loaded model. The rest are listed because
they work the same way, not because they were timed. This only ever drives a
warning -- nothing is blocked on it.
"""


def is_reasoning_model(name: str) -> bool:
    """Whether `name` looks like a model that thinks at length before answering."""
    return name.lower().startswith(REASONING_MODELS)


REPAIR = (
    "That was not valid JSON. Reply with the JSON object only, "
    "with no commentary, markdown, or code fences."
)


class OllamaLLM:
    """Calls a local Ollama server with schema-constrained decoding."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        *,
        host: str | None = None,
        num_ctx: int = DEFAULT_NUM_CTX,
        timeout: float = DEFAULT_TIMEOUT,
        seed: int = DEFAULT_SEED,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self.host = (host or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST).rstrip("/")
        self.num_ctx = num_ctx
        self.timeout = timeout
        self.seed = seed
        self._client = client or httpx.Client(timeout=timeout)

    @property
    def name(self) -> str:
        return f"ollama/{self.model}"

    def complete(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        content = self._chat(messages, schema)
        parsed = _try_parse(content)
        if parsed is not None:
            return parsed

        # One repair attempt. Small models occasionally wrap the object in
        # prose despite the schema; showing them the mistake usually fixes it.
        messages.extend(
            [
                {"role": "assistant", "content": content},
                {"role": "user", "content": REPAIR},
            ]
        )
        retry = self._chat(messages, schema)
        parsed = _try_parse(retry)
        if parsed is not None:
            return parsed

        raise LLMError(f"{self.model} did not return JSON after a retry: {retry[:200]!r}")

    def _chat(self, messages: list[dict[str, str]], schema: dict[str, Any]) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "format": schema,
            "options": {
                "temperature": 0,
                "seed": self.seed,
                "num_ctx": self.num_ctx,
            },
        }

        try:
            response = self._client.post(f"{self.host}/api/chat", json=payload)
        except httpx.TimeoutException as exc:
            raise LLMError(
                f"{self.model} did not respond within {self.timeout:.0f}s. "
                "Reasoning models such as deepseek-r1 and qwen3.5 are far too slow "
                "for this; try a plain instruct model like llama3.2."
            ) from exc
        except httpx.ConnectError as exc:
            raise LLMError(
                f"Could not reach Ollama at {self.host}. "
                "Is it running? Start it with `ollama serve`."
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Request to Ollama failed: {exc}") from exc

        if response.status_code == 404:
            raise LLMError(
                f"Ollama does not have {self.model!r}. Pull it with `ollama pull {self.model}`."
            )
        if response.status_code >= 400:
            raise LLMError(f"Ollama returned {response.status_code}: {response.text[:200]}")

        try:
            body = response.json()
        except ValueError as exc:
            raise LLMError("Ollama returned a response that was not JSON.") from exc

        if "error" in body:
            raise LLMError(f"Ollama reported an error: {body['error']}")

        content = body.get("message", {}).get("content")
        if not content:
            raise LLMError(f"{self.model} returned an empty response.")

        return _strip_thinking(content)


def _strip_thinking(content: str) -> str:
    """Remove inline `<think>` blocks.

    Ollama usually puts reasoning in a separate `thinking` field, but not every
    model template does, and a stray block would break JSON parsing.
    """
    return THINK_TAG_RE.sub("", content).strip()


def _try_parse(content: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
