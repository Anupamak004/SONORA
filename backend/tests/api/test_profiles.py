"""API integration tests for /api/v1/profiles."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_profiles_endpoint(client: TestClient) -> None:
    response = client.get("/api/v1/profiles")
    assert response.status_code == 200

    payload = response.json()
    assert "profiles" in payload
    assert len(payload["profiles"]) == 7
    assert any(p["id"] == "acoustic_guitar" for p in payload["profiles"])


def test_get_single_profile_and_not_found_envelope(client: TestClient) -> None:
    ok_resp = client.get("/api/v1/profiles/piano")
    assert ok_resp.status_code == 200
    assert ok_resp.json()["id"] == "piano"

    missing_resp = client.get("/api/v1/profiles/ukulele_unknown")
    assert missing_resp.status_code == 404
    err = missing_resp.json()
    assert err["error"]["code"] == "RESOURCE_NOT_FOUND"
    assert "ukulele_unknown" in err["error"]["message"]
