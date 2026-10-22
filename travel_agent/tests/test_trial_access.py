from fastapi.testclient import TestClient

from travel_agent.main import app, settings


def test_trial_key_protects_api_but_not_health(monkeypatch):
    monkeypatch.setattr(settings, "trial_access_key", "expected-key")
    client = TestClient(app)

    assert client.get("/health").status_code == 200
    assert client.get("/api/session/missing").status_code == 401
    assert client.get(
        "/api/session/missing",
        headers={"X-Xingji-Trial-Key": "wrong-key"},
    ).status_code == 401
    assert client.get(
        "/api/session/missing",
        headers={"X-Xingji-Trial-Key": "expected-key"},
    ).status_code != 401


def test_production_trial_preview_requires_explicit_opt_in(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "trial_access_key", "expected-key")
    monkeypatch.setattr(settings, "legacy_trial_auth_enabled", True)
    client = TestClient(app)

    assert client.get("/api/session/missing").status_code == 401
    assert client.get(
        "/api/session/missing",
        headers={"X-Xingji-Trial-Key": "expected-key"},
    ).status_code != 401

    monkeypatch.setattr(settings, "legacy_trial_auth_enabled", False)
    assert client.get(
        "/api/session/missing",
        headers={"X-Xingji-Trial-Key": "expected-key"},
    ).status_code == 503
