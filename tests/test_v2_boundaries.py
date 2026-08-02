from __future__ import annotations

from pathlib import Path

from scripts.verify_v2_boundaries import verify


def test_v2_boundary_manifest_has_no_forbidden_service_imports():
    report = verify(Path(__file__).resolve().parents[1])
    assert report["status"] == "ok"
    assert report["schema_version"] == "worldpulse-v2-boundaries.v1"
