"""Thin client for the local Ollama server.

``generate_json`` asks a model for JSON constrained to a Pydantic model's schema and
validates the reply. An invalid reply is retried once; a second failure raises
``LLMInvalidOutputError``. Callers turn that into "unscored" — there is no fallback
value here, by design.
"""

import json
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import get_settings

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Base class for LLM failures."""


class LLMUnavailableError(LLMError):
    """Ollama is not reachable, timed out, or returned an HTTP error."""


class LLMInvalidOutputError(LLMError):
    """The model's reply was not valid JSON for the schema, even after a retry."""

    def __init__(self, message: str, attempts: list[str]):
        super().__init__(message)
        self.attempts = attempts


class OllamaClient:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        embed_model: str | None = None,
        timeout_s: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        settings = get_settings()
        self.model = model or settings.llm_model
        self.embed_model = embed_model or settings.embed_model
        self._client = httpx.AsyncClient(
            base_url=base_url or settings.ollama_url,
            timeout=timeout_s or settings.llm_timeout_s,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "OllamaClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        try:
            response = await self._client.request(method, path, **kwargs)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            detail = e.response.text[:300]
            raise LLMUnavailableError(
                f"Ollama {path} returned {e.response.status_code}: {detail}"
            ) from e
        except httpx.HTTPError as e:
            raise LLMUnavailableError(f"Ollama {path} failed: {e!r}") from e
        return response.json()

    async def version(self) -> str:
        return (await self._request("GET", "/api/version"))["version"]

    async def list_models(self) -> list[str]:
        data = await self._request("GET", "/api/tags")
        return [m["name"] for m in data.get("models", [])]

    async def generate_json(
        self,
        prompt: str,
        schema: type[T],
        *,
        system: str | None = None,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> T:
        """Return the model's reply parsed into ``schema``; one retry on invalid output."""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        attempts: list[str] = []
        for attempt in range(2):
            data = await self._request(
                "POST",
                "/api/chat",
                json={
                    "model": model or self.model,
                    "messages": messages,
                    "format": schema.model_json_schema(),
                    "stream": False,
                    "options": {"temperature": temperature},
                },
            )
            content = data.get("message", {}).get("content", "")
            attempts.append(content)
            try:
                return schema.model_validate_json(content)
            except ValidationError as e:
                if attempt == 1:
                    raise LLMInvalidOutputError(
                        f"{schema.__name__}: invalid output after retry: {e.errors()[:3]}",
                        attempts,
                    ) from e
                messages += [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": "That reply did not match the required JSON schema "
                        f"({json.dumps(e.errors()[:3], default=str)}). "
                        "Reply again with only valid JSON for the schema.",
                    },
                ]
        raise AssertionError("unreachable")

    async def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        data = await self._request(
            "POST", "/api/embed", json={"model": model or self.embed_model, "input": texts}
        )
        return data["embeddings"]
