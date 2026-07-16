from __future__ import annotations

import base64

import pytest
from fastapi import HTTPException

from app.services.evaluation.benchmark_tools import pack_labels, validate_label_payload, validate_source_plan
from app.services.evaluation.service import _historical_case_metrics
from app.services.war_room.data import SUPPLY_CHAINS


def test_historical_metrics_do_not_default_missing_direction_to_up():
    baseline = next(item for item in SUPPLY_CHAINS if item.key == "energy").pressure_score
    result = {
        "country_agents": [{"code": "USA", "risk_score": 40}],
        "supply_chains": [{"key": "energy", "pressure_score": baseline}],
        "timeline": [],
    }
    metrics = _historical_case_metrics(
        result,
        {
            "risk_ranking": ["USA", "CHN", "JPN", "KOR", "TWN"],
            "top3_countries": ["USA", "CHN", "JPN"],
            "supply_chain_directions": {"energy": "up"},
            "turning_points": [],
        },
        0.7,
        2,
    )
    assert metrics["supply_chain_direction_accuracy"] == 0
    assert metrics["agent_outcome_agreement"] is None
    assert metrics["data_coverage"] > 0


def test_label_contract_rejects_invalid_top3():
    with pytest.raises(HTTPException):
        validate_label_payload(
            {
                "suite_id": "historical-benchmark.v1",
                "labels": {"hist_blind_01": {"risk_ranking": ["USA", "CHN", "JPN", "KOR", "TWN"], "top3_countries": ["USA", "EU", "JPN"], "supply_chain_directions": {"energy": "up"}, "turning_points": [], "label_confidence": 0.7}},
            },
            {"hist_blind_01"},
        )


def test_source_plan_requires_exact_matrix():
    with pytest.raises(HTTPException):
        validate_source_plan({"suite_id": "historical-benchmark.v1", "version": "1", "cases": []})


def test_offline_label_pack_is_encrypted_and_signed():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    aes_key = base64.b64encode(b"x" * 32).decode("ascii")
    signer_key = base64.b64encode(private.private_bytes_raw()).decode("ascii")
    blind_ids = {f"hist_blind_{index:02d}" for index in range(30)}
    labels = {
        case_id: {
            "risk_ranking": ["USA", "CHN", "JPN", "KOR", "TWN"],
            "top3_countries": ["USA", "CHN", "JPN"],
            "supply_chain_directions": {"energy": "up"},
            "turning_points": [3],
            "label_confidence": 0.7,
        }
        for case_id in blind_ids
    }
    packed = pack_labels(
        {"suite_id": "historical-benchmark.v1", "labels": labels},
        blind_ids,
        aes_key_b64=aes_key,
        signer_private_key_b64=signer_key,
        signer_key_id="test",
        encryption_key_id="test-aes",
        evidence_hash="e" * 64,
    )
    assert packed["case_count"] == 30
    assert packed["ciphertext_sha256"]
    assert packed["signature"]
