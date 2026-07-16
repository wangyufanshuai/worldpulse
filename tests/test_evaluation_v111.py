from app.core.evaluation_models import EvaluationBatchCreateRequest
from app.services.auth import ensure_system_user
from app.services.evaluation import EvaluationService
from app.services.evaluation.corpus import standard_cases, suite_manifest


def test_cross_mode_suite_is_immutable_and_contains_twelve_cases():
    manifest = suite_manifest()
    assert len(manifest["cases"]) == 12
    assert len({item["case_hash"] for item in manifest["cases"]}) == 12
    assert manifest["manifest_hash"]


def test_standard_batch_expands_to_eighty_four_members():
    service = EvaluationService()
    batch = service.create_standard_batch("org_default", ensure_system_user(), EvaluationBatchCreateRequest(provider="mock"))
    assert batch.total_members == 84
    assert len(service.list_members(batch.batch_id)) == 84
    assert {item.engine_mode for item in service.list_members(batch.batch_id)} == {"deterministic", "hybrid", "negotiation"}


def test_live_provider_cannot_be_standard_gate():
    service = EvaluationService()
    try:
        service.create_standard_batch("org_default", ensure_system_user(), EvaluationBatchCreateRequest(provider="deepseek"))
    except Exception as exc:
        assert "mock" in str(exc).lower()
    else:
        raise AssertionError("live provider must not create a standard safety batch")
