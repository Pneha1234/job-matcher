import pytest

from app.security import _host_name, _origin_is_local


def test_host_names():
    assert _host_name("localhost:3000") == "localhost"
    assert _host_name("127.0.0.1") == "127.0.0.1"
    assert _host_name("[::1]:8000") == "[::1]"
    assert _host_name("Evil.Example:3000") == "evil.example"


@pytest.mark.parametrize(
    "origin, local",
    [
        ("http://localhost:3000", True),
        ("http://127.0.0.1:3000", True),
        ("http://[::1]:3000", True),
        ("https://evil.example", False),
        ("http://localhost.evil.example", False),
        ("null", False),
    ],
)
def test_origins(origin, local):
    assert _origin_is_local(origin) is local


def test_rebinding_host_is_rejected(client):
    assert client.get("/summary", headers={"Host": "evil.example:8000"}).status_code == 403
    proxied = {"X-Forwarded-Host": "evil.example:3000"}
    assert client.get("/summary", headers=proxied).status_code == 403
    assert client.get("/summary", headers={"Host": "localhost:8000"}).status_code == 200


def test_cross_site_writes_are_rejected(client):
    body = {"text": "Python developer · Pune"}
    evil = client.post("/searches", json=body, headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403
    fetch = client.post("/searches", json=body, headers={"Sec-Fetch-Site": "cross-site"})
    assert fetch.status_code == 403
    assert client.get("/searches").json() == []  # nothing was written
    ui = client.post("/searches", json=body, headers={"Origin": "http://localhost:3000"})
    assert ui.status_code == 200
    # Local tools send no Origin at all.
    assert client.post("/searches", json={"text": "Data engineer"}).status_code == 200


def test_reads_from_other_sites_are_not_blocked_by_this_layer(client):
    # Browsers already stop other sites from reading replies (no CORS grant); GETs stay
    # usable for local tools and the UI.
    assert client.get("/summary", headers={"Origin": "https://evil.example"}).status_code == 200
