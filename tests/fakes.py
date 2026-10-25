"""A stand-in for Ollama: canned JSON per schema, deterministic embeddings."""

import hashlib
import json
import math

import httpx

from app.db import EMBEDDING_DIM
from app.llm import OllamaClient

PROFILE = {
    "current_title": "Senior Backend Engineer",
    "seniority": "senior",
    "years_experience": 8,
    "summary": "Backend engineer focused on Python services.",
    "skills": [
        {"name": "Python", "years": 8},
        {"name": "Django", "years": 6},
        {"name": "PostgreSQL", "years": 6},
        {"name": "Celery", "years": 4},
    ],
    "roles": ["Backend Engineer", "Software Engineer"],
    "domains": ["Fintech"],
    "languages": [{"language": "English", "level": "fluent"}],
}

ASSESSMENT = {
    "required_skills": [
        {"skill": "Python", "status": "matched"},
        {"skill": "Django", "status": "matched"},
        {"skill": "Kubernetes", "status": "missing"},
        {"skill": "PostgreSQL", "status": "partial"},
    ],
    "nice_to_have_skills": [{"skill": "Celery", "status": "matched"}],
    "seniority_fit": "match",
    "domain_fit": "related",
    "location_language_fit": "fits",
    "explanation": "Strong Python and Django match. Kubernetes is the one missing must-have.",
}


def vector(text: str) -> list[float]:
    """Stable pseudo-embedding: texts sharing words point in similar directions."""
    vec = [0.0] * EMBEDDING_DIM
    for word in text.lower().split():
        h = int(hashlib.md5(word.encode()).hexdigest(), 16)
        vec[h % EMBEDDING_DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class FakeOllama:
    def __init__(self):
        self.replies: dict[str, list[str]] = {}  # schema title -> queued raw replies
        self.defaults = {
            "ExtractedProfile": PROFILE,
            "JobAssessment": ASSESSMENT,
            "CoverLetter": {"letter": "Dear hiring team, " + "I build Python services. " * 12},
            "ImportedJob": {
                "title": "Python Developer",
                "company": "Acme",
                "locations": ["Amsterdam"],
                "remote": False,
                "job_type": "Full-time",
                "salary_text": "€60k–70k",
            },
        }
        self.calls: list[dict] = []
        self.down = False
        self.client = OllamaClient(
            base_url="http://ollama.test",
            model="qwen2.5:14b",
            embed_model="bge-m3",
            transport=httpx.MockTransport(self.handle),
        )

    def queue(self, schema: str, *raw: str) -> None:
        self.replies.setdefault(schema, []).extend(raw)

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("refused", request=request)
        path = request.url.path
        if path == "/api/version":
            return httpx.Response(200, json={"version": "0.0.1"})
        if path == "/api/tags":
            return httpx.Response(
                200, json={"models": [{"name": "qwen2.5:14b"}, {"name": "bge-m3:latest"}]}
            )
        body = json.loads(request.content)
        self.calls.append(body)
        if path == "/api/embed":
            return httpx.Response(200, json={"embeddings": [vector(t) for t in body["input"]]})
        title = body["format"].get("title")
        queued = self.replies.get(title)
        content = queued.pop(0) if queued else json.dumps(self.defaults[title])
        return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})
