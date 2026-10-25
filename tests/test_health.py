import httpx
from fastapi.testclient import TestClient

from app.api.health import get_ollama
from app.llm import OllamaClient
from app.main import app


def fake_ollama(handler) -> OllamaClient:
    return OllamaClient(
        base_url="http://ollama.test",
        model="qwen2.5:14b",
        embed_model="bge-m3",
        transport=httpx.MockTransport(handler),
    )


def ollama_up(models: list[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.0.1"})
        return httpx.Response(200, json={"models": [{"name": m} for m in models]})

    return handler


def get_health(handler) -> dict:
    app.dependency_overrides[get_ollama] = lambda: fake_ollama(handler)
    try:
        with TestClient(app) as client:
            response = client.get("/health")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    return response.json()


def test_health_ok():
    body = get_health(ollama_up(["qwen2.5:14b", "bge-m3:latest"]))
    assert body["status"] == "ok"
    assert body["db"]["ok"] is True
    assert body["ollama"]["llm_model_ready"] and body["ollama"]["embed_model_ready"]


def test_health_model_missing():
    body = get_health(ollama_up(["bge-m3:latest"]))
    assert body["status"] == "degraded"
    assert body["ollama"]["ok"] is True
    assert "qwen2.5:14b" in body["ollama"]["error"]


def test_health_ollama_down():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    body = get_health(handler)
    assert body["status"] == "degraded"
    assert body["db"]["ok"] is True
    assert body["ollama"]["ok"] is False and body["ollama"]["error"]
