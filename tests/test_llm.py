import asyncio
import json

import httpx
import pytest
from pydantic import BaseModel

from app.llm import LLMInvalidOutputError, LLMUnavailableError, OllamaClient


class Answer(BaseModel):
    city: str
    population_millions: float


def chat_reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})


def client_with(replies: list[httpx.Response], seen: list[dict]) -> OllamaClient:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return replies[len(seen) - 1]

    return OllamaClient(base_url="http://ollama.test", transport=httpx.MockTransport(handler))


def run(coro):
    return asyncio.run(coro)


def test_valid_json_first_try():
    seen: list[dict] = []
    client = client_with([chat_reply('{"city": "Kathmandu", "population_millions": 1.5}')], seen)
    answer = run(client.generate_json("Capital of Nepal?", Answer))
    assert answer == Answer(city="Kathmandu", population_millions=1.5)
    assert len(seen) == 1
    assert seen[0]["format"] == Answer.model_json_schema()
    assert seen[0]["stream"] is False
    # Ollama's 4,096-token default would silently cut long prompts.
    assert seen[0]["options"]["num_ctx"] == 16384


def test_retries_once_then_succeeds():
    seen: list[dict] = []
    client = client_with(
        [chat_reply("not json"), chat_reply('{"city": "Pune", "population_millions": 7}')], seen
    )
    assert run(client.generate_json("q", Answer)).city == "Pune"
    assert len(seen) == 2
    # The retry tells the model what was wrong.
    assert "did not match" in seen[1]["messages"][-1]["content"]


def test_invalid_twice_raises_without_fallback():
    seen: list[dict] = []
    client = client_with([chat_reply("nope"), chat_reply('{"city": "Delhi"}')], seen)
    with pytest.raises(LLMInvalidOutputError) as exc:
        run(client.generate_json("q", Answer))
    assert exc.value.attempts == ["nope", '{"city": "Delhi"}']
    assert len(seen) == 2


def test_unreachable_raises_typed_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client = OllamaClient(base_url="http://ollama.test", transport=httpx.MockTransport(handler))
    with pytest.raises(LLMUnavailableError):
        run(client.version())


def test_http_error_raises_typed_error():
    client = OllamaClient(
        base_url="http://ollama.test",
        transport=httpx.MockTransport(lambda r: httpx.Response(404, text="model not found")),
    )
    with pytest.raises(LLMUnavailableError, match="404"):
        run(client.generate_json("q", Answer))
