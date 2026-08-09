from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.evaluation_models import EvaluationBatchCreateRequest
from app.services import project_store
from app.services.auth import ensure_system_user
from app.services.evaluation import EvaluationService
from app.services.plugin_sdk import build_plugin_input, verify_stored_plugin_output
from app.services.plugin_sdk.builtins import (
    ActiveRulePackAdapter,
    ActiveRulePackOutputV1,
    EvaluationReportAdapter,
    EvaluationReportOutputV1,
    built_in_evaluator_registry,
    built_in_rule_pack_registry,
)
from app.services.rule_packs import active_rule_pack


def _counts(*tables: str) -> dict[str, int]:
    with project_store.connect() as connection:
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in tables
        }


def _rule_payload(pack, organization_id: str = "org_default") -> dict:
    return {
        "schema_version": "active-rule-pack-request.v1",
        "organization_id": organization_id,
        "expected_rule_pack_id": pack.rule_pack_id,
        "expected_manifest_hash": pack.manifest_hash,
    }


def _evaluation_payload(
    batch_id: str,
    organization_id: str = "org_default",
    report_kind: str = "standard",
) -> dict:
    return {
        "schema_version": "evaluation-report-request.v1",
        "organization_id": organization_id,
        "batch_id": batch_id,
        "report_kind": report_kind,
    }


def test_active_rule_pack_adapter_is_integrity_checked_and_read_only(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "rule-plugin.db")
    pack = active_rule_pack()
    calls = {"count": 0}

    def resolver():
        calls["count"] += 1
        return active_rule_pack()

    adapter = ActiveRulePackAdapter(resolver=resolver)
    tables = ("rule_packs", "rule_pack_reviews", "calibration_runs")
    before = _counts(*tables)
    stored = adapter.execute(
        build_plugin_input(
            adapter.manifest,
            _rule_payload(pack),
            organization_id="org_default",
        )
    )
    after = _counts(*tables)
    output = ActiveRulePackOutputV1.model_validate(stored.payload)

    assert before == after
    assert calls["count"] == 1
    assert output.rule_pack.rule_pack_id == pack.rule_pack_id
    assert output.rule_pack_hash == pack.manifest_hash
    assert output.activation_write is False
    assert output.human_review_required is True
    assert output.calibration_required is True
    assert stored.provider_calls == 0
    assert not hasattr(adapter, "activate")
    assert verify_stored_plugin_output(
        adapter.manifest,
        stored,
        require_provider_free=True,
        require_zero_provider_calls=True,
    ) == stored
    assert calls["count"] == 1


def test_rule_pack_adapter_rejects_manifest_and_scope_drift(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "rule-tamper.db")
    pack = active_rule_pack()
    tampered = pack.model_copy(
        update={"manifest": {**pack.manifest, "version": "tampered"}}
    )
    adapter = ActiveRulePackAdapter(resolver=lambda: tampered)
    envelope = build_plugin_input(
        adapter.manifest,
        _rule_payload(pack),
        organization_id="org_default",
    )
    with pytest.raises(ValueError, match="columns do not match"):
        adapter.execute(envelope)

    valid = ActiveRulePackAdapter(resolver=lambda: pack)
    mismatched_scope = build_plugin_input(
        valid.manifest,
        _rule_payload(pack, organization_id="org_default"),
        organization_id="org_other",
    )
    with pytest.raises(ValueError, match="organization binding mismatch"):
        valid.execute(mismatched_scope)


def test_real_evaluator_adapter_reports_without_governance_writes(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "evaluator-plugin.db")
    service = EvaluationService()
    batch = service.create_standard_batch(
        "org_default",
        ensure_system_user(),
        EvaluationBatchCreateRequest(provider="mock"),
    )
    adapter = EvaluationReportAdapter(service)
    tables = (
        "evaluation_batches",
        "evaluation_members",
        "evaluation_metrics",
        "historical_label_packs",
        "historical_label_pack_reviews",
        "rule_pack_reviews",
    )
    before = _counts(*tables)
    stored = adapter.execute(
        build_plugin_input(
            adapter.manifest,
            _evaluation_payload(batch.batch_id),
            organization_id="org_default",
        )
    )
    after = _counts(*tables)
    output = EvaluationReportOutputV1.model_validate(stored.payload)

    assert before == after
    assert output.batch_id == batch.batch_id
    assert output.report["batch"]["organization_id"] == "org_default"
    assert output.report["safety_gate"]["status"] == "pending"
    assert output.label_writes == 0
    assert output.rights_decision_writes == 0
    assert output.blind_labels_redacted is True
    assert '"labels":' not in stored.model_dump_json()
    assert stored.provider_calls == 0
    assert not hasattr(adapter, "create_batch")
    assert not hasattr(adapter, "import_label_pack")
    assert verify_stored_plugin_output(
        adapter.manifest,
        stored,
        require_provider_free=True,
        require_zero_provider_calls=True,
    ) == stored

    wrong_org = build_plugin_input(
        adapter.manifest,
        _evaluation_payload(batch.batch_id, organization_id="org_other"),
        organization_id="org_other",
    )
    with pytest.raises(HTTPException) as exc:
        adapter.execute(wrong_org)
    assert exc.value.status_code == 404


def test_evaluator_rejects_historical_label_material() -> None:
    class Batch:
        evaluation_track = "historical_blind"

    class UnsafeReport:
        blind_labels_redacted = True
        report_hash = "a" * 64

        @staticmethod
        def model_dump(*_args, **_kwargs):
            return {
                "batch": {"organization_id": "org_default"},
                "blind_labels_redacted": True,
                "labels": {"blind_case": "must-not-leak"},
                "report_hash": "a" * 64,
            }

    class UnsafeApplication:
        @staticmethod
        def get_batch(_batch_id, _organization_id=None):
            return Batch()

        @staticmethod
        def historical_report(_batch_id, _organization_id):
            return UnsafeReport()

    adapter = EvaluationReportAdapter(UnsafeApplication())
    envelope = build_plugin_input(
        adapter.manifest,
        _evaluation_payload("eval_historical", report_kind="historical"),
        organization_id="org_default",
    )
    with pytest.raises(ValueError, match="forbidden label material"):
        adapter.execute(envelope)


def test_governance_plugin_manifests_are_read_only_and_registered(
    monkeypatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "registry.db")
    rule_manifest = built_in_rule_pack_registry().resolve(
        "rule_pack.active",
        kind="rule_pack",
        required_permissions=("rule_pack.read",),
    )
    evaluator_manifest = built_in_evaluator_registry().resolve(
        "evaluator.governed_report",
        kind="evaluator",
        required_permissions=("evaluation.read",),
    )
    assert rule_manifest.permissions == ("rule_pack.read",)
    assert evaluator_manifest.permissions == ("evaluation.read",)
    assert "write" not in rule_manifest.model_dump_json()
    assert EvaluationReportAdapter.configuration()["label_write"] is False
    assert EvaluationReportAdapter.configuration()["rights_decision_write"] is False
