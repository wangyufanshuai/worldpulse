import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.version import WORLDPULSE_VERSION


def test_version_endpoint_and_openapi_release_are_aligned():
    client = TestClient(app)
    response = client.get("/api/version")
    assert response.status_code == 200
    assert response.json() == {
        "service": "worldpulse",
        "version": "1.2.0-dev",
        "api_contract_version": "v1",
        "release_channel": "development",
    }
    assert app.version == WORLDPULSE_VERSION
    assert app.openapi()["info"]["version"] == WORLDPULSE_VERSION


def test_openapi_snapshot_matches_runtime_contract():
    snapshot = json.loads(Path("docs/api/openapi.v1.json").read_text(encoding="utf-8"))
    assert snapshot == app.openapi()
