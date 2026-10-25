import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_ollama
from app.config import get_settings
from app.normalize.geo import load_geo
from tests.fakes import FakeOllama

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Point every test at a throwaway database, no scheduler, no scrape delays, and a
    tiny GeoNames extract instead of the real download."""
    monkeypatch.setenv("JM_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("JM_SCHEDULER", "0")
    monkeypatch.setenv("JM_SCRAPE_DELAY_MIN", "0")
    monkeypatch.setenv("JM_SCRAPE_DELAY_MAX", "0")
    monkeypatch.setenv("JM_HTTP_CACHE_TTL_S", "0")
    shutil.copytree(FIXTURES / "geonames", tmp_path / "geonames")
    get_settings.cache_clear()
    load_geo.cache_clear()
    yield
    get_settings.cache_clear()
    load_geo.cache_clear()


@pytest.fixture
def fake_ollama():
    return FakeOllama()


@pytest.fixture
def client(fake_ollama):
    from app.main import app

    app.dependency_overrides[get_ollama] = lambda: fake_ollama.client
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def db(client):
    return client.app.state.db


def wait_task(client, task_id: int, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = client.get(f"/tasks/{task_id}").json()
        if task["status"] in ("done", "error"):
            return task
        time.sleep(0.02)
    raise AssertionError(f"task {task_id} still running: {task}")
