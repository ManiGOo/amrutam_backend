from fastapi.testclient import TestClient

from amrutam.main import create_app


def test_health() -> None:
    client = TestClient(create_app())
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready() -> None:
    client = TestClient(create_app())
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready"}
