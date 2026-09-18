import json
from typing import Any

import httpx
import pytest

from notetaker.llm.base import LLMError
from notetaker.llm.ollama import OllamaLLM

SCHEMA: dict[str, Any] = {"type": "object", "properties": {"cards": {"type": "array"}}}
PAYLOAD = {"cards": [{"question": "What is ATP?", "answer": "Adenosine triphosphate"}]}


def client_returning(*responses: httpx.Response, record: list[dict] | None = None) -> OllamaLLM:
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if record is not None:
            record.append(json.loads(request.content))
        return queue.pop(0) if len(queue) > 1 else queue[0]

    transport = httpx.MockTransport(handler)
    return OllamaLLM("llama3.2", client=httpx.Client(transport=transport))


def chat(content: str) -> httpx.Response:
    return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})


def test_a_well_formed_response_is_parsed() -> None:
    llm = client_returning(chat(json.dumps(PAYLOAD)))
    assert llm.complete("sys", "user", SCHEMA) == PAYLOAD


def test_the_request_carries_the_schema_and_a_deterministic_seed() -> None:
    sent: list[dict] = []
    llm = client_returning(chat(json.dumps(PAYLOAD)), record=sent)
    llm.complete("sys", "user", SCHEMA)

    body = sent[0]
    assert body["format"] == SCHEMA
    assert body["stream"] is False
    assert body["options"]["temperature"] == 0
    assert body["options"]["seed"] == 7


def test_num_ctx_is_always_set_explicitly() -> None:
    sent: list[dict] = []
    llm = client_returning(chat(json.dumps(PAYLOAD)), record=sent)
    llm.complete("sys", "user", SCHEMA)
    assert sent[0]["options"]["num_ctx"] == 8192


def test_the_think_parameter_is_never_sent() -> None:
    # Sending think=false makes some models ignore the format schema entirely.
    sent: list[dict] = []
    llm = client_returning(chat(json.dumps(PAYLOAD)), record=sent)
    llm.complete("sys", "user", SCHEMA)
    assert "think" not in sent[0]


def test_inline_think_blocks_are_stripped_before_parsing() -> None:
    content = f"<think>weighing options</think>{json.dumps(PAYLOAD)}"
    llm = client_returning(chat(content))
    assert llm.complete("sys", "user", SCHEMA) == PAYLOAD


def test_prose_is_retried_once_and_the_repair_succeeds() -> None:
    sent: list[dict] = []
    llm = client_returning(chat("Here are your cards!"), chat(json.dumps(PAYLOAD)), record=sent)
    assert llm.complete("sys", "user", SCHEMA) == PAYLOAD
    assert len(sent) == 2
    assert sent[1]["messages"][-1]["content"].startswith("That was not valid JSON")


def test_two_bad_responses_raise() -> None:
    llm = client_returning(chat("still not json"))
    with pytest.raises(LLMError, match="did not return JSON"):
        llm.complete("sys", "user", SCHEMA)


def test_a_missing_model_names_the_pull_command() -> None:
    llm = client_returning(httpx.Response(404, json={"error": "model not found"}))
    with pytest.raises(LLMError, match="ollama pull llama3.2"):
        llm.complete("sys", "user", SCHEMA)


def test_a_refused_connection_says_how_to_start_ollama() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    llm = OllamaLLM("llama3.2", client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(LLMError, match="ollama serve"):
        llm.complete("sys", "user", SCHEMA)


def test_a_timeout_points_at_reasoning_models() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    llm = OllamaLLM("deepseek-r1:8b", client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(LLMError, match="too slow"):
        llm.complete("sys", "user", SCHEMA)


def test_an_error_field_in_the_body_is_surfaced() -> None:
    llm = client_returning(httpx.Response(200, json={"error": "out of memory"}))
    with pytest.raises(LLMError, match="out of memory"):
        llm.complete("sys", "user", SCHEMA)


def test_an_empty_response_is_an_error() -> None:
    llm = client_returning(chat(""))
    with pytest.raises(LLMError, match="empty response"):
        llm.complete("sys", "user", SCHEMA)


def test_the_name_identifies_the_model() -> None:
    assert OllamaLLM("llama3.2").name == "ollama/llama3.2"


def test_the_host_can_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "http://box:9999/")
    assert OllamaLLM("llama3.2").host == "http://box:9999"


@pytest.mark.parametrize(
    "name", ["deepseek-r1:8b", "qwen3.5:9b", "qwen3.5:0.8B", "qwq:32b", "QWEN3.5:4b"]
)
def test_reasoning_models_are_recognized(name: str) -> None:
    from notetaker.llm.ollama import is_reasoning_model

    assert is_reasoning_model(name)


@pytest.mark.parametrize(
    "name", ["llama3.2", "llama3.1:8b", "phi4-mini:3.8b", "qwen2.5-coder:7b", "qwen2.5vl:3b"]
)
def test_plain_instruct_models_are_not_flagged(name: str) -> None:
    from notetaker.llm.ollama import is_reasoning_model

    assert not is_reasoning_model(name)
