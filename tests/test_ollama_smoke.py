"""Round-trips a prompt through the real local Ollama. Run with `make smoke`."""

import asyncio

import pytest
from pydantic import BaseModel, Field

from app.llm import OllamaClient

pytestmark = pytest.mark.ollama


class SkillExtraction(BaseModel):
    skills: list[str] = Field(min_length=1)
    seniority: str
    years_experience: int = Field(ge=0, le=60)


def test_llm_returns_valid_json():
    async def go() -> SkillExtraction:
        async with OllamaClient() as client:
            return await client.generate_json(
                "Extract the skills, seniority and years of experience from this line: "
                "'Senior backend engineer, 6 years of Python, FastAPI and PostgreSQL.'",
                SkillExtraction,
            )

    result = asyncio.run(go())
    lowered = [s.lower() for s in result.skills]
    assert any("python" in s for s in lowered)
    assert result.years_experience == 6


def test_embedding_dimension():
    from app.db import EMBEDDING_DIM

    async def go() -> list[list[float]]:
        async with OllamaClient() as client:
            return await client.embed(["Backend engineer, Kathmandu"])

    vectors = asyncio.run(go())
    assert len(vectors) == 1 and len(vectors[0]) == EMBEDDING_DIM
