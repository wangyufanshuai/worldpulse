"""Read-only Evaluator plugin backed by the Evaluation application port."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.evaluation import EvaluationApplicationPort, EvaluationService

from ..contracts import (
    PluginInputEnvelope,
    PluginManifest,
    PluginOutputEnvelope,
    build_plugin_manifest,
    build_plugin_output,
)
from ..registry import PluginRegistry
from ..verification import verify_plugin_input


_FORBIDDEN_LABEL_KEYS = {
    "blind_labels",
    "ciphertext_b64",
    "development_labels",
    "labels",
    "nonce_b64",
    "rights_decision",
}


class EvaluationReportRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["evaluation-report-request.v1"] = (
        "evaluation-report-request.v1"
    )
    organization_id: str = Field(min_length=3, max_length=80)
    batch_id: str = Field(min_length=3, max_length=80)
    report_kind: Literal["standard", "historical"] = "standard"


class EvaluationReportOutputV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["evaluation-report-output.v1"] = (
        "evaluation-report-output.v1"
    )
    organization_id: str
    batch_id: str
    report_kind: Literal["standard", "historical"]
    report: dict[str, Any]
    report_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    label_writes: Literal[0] = 0
    rights_decision_writes: Literal[0] = 0
    blind_labels_redacted: Literal[True] = True


class EvaluationReportAdapter:
    """Project existing governed reports without exposing mutation methods."""

    plugin_id = "evaluator.governed_report"
    implementation_id = "builtin.evaluator.report.v1"

    def __init__(self, application: EvaluationApplicationPort) -> None:
        self._application = application
        self._manifest = build_plugin_manifest(
            plugin_id=self.plugin_id,
            kind="evaluator",
            version="1.0.0",
            implementation_id=self.implementation_id,
            capabilities=("report.project", "safety.observe"),
            permissions=("evaluation.read",),
            input_schema="evaluation-report-request.v1",
            output_schema="evaluation-report-output.v1",
            configuration=self.configuration(),
        )

    @classmethod
    def configuration(cls) -> dict[str, Any]:
        return {
            "operations": ["historical_report", "report"],
            "label_write": False,
            "rights_decision_write": False,
            "blind_labels_redacted": True,
            "organization_scope_required": True,
        }

    @property
    def manifest(self) -> PluginManifest:
        return self._manifest

    def execute(self, envelope: PluginInputEnvelope) -> PluginOutputEnvelope:
        self.manifest.verify_configuration(self.configuration())
        verified = verify_plugin_input(self.manifest, envelope)
        request = EvaluationReportRequestV1.model_validate(verified.payload)
        if request.schema_version != self.manifest.input_schema:
            raise ValueError("Evaluator input schema does not match manifest")
        if verified.invocation.organization_id != request.organization_id:
            raise ValueError("Evaluator organization binding mismatch")
        batch = self._application.get_batch(
            request.batch_id,
            request.organization_id,
        )
        if request.report_kind == "historical":
            if batch.evaluation_track != "historical_blind":
                raise ValueError("historical Evaluator report requires a historical batch")
            report = self._application.historical_report(
                request.batch_id,
                request.organization_id,
            )
            if report.blind_labels_redacted is not True:
                raise ValueError("historical Evaluator report exposed blind labels")
        else:
            if batch.evaluation_track == "historical_blind":
                raise ValueError("historical batches require the redacted report path")
            report = self._application.report(
                request.batch_id,
                request.organization_id,
            )
        report_payload = report.model_dump(mode="json")
        if report_payload["batch"]["organization_id"] != request.organization_id:
            raise ValueError("Evaluator report organization scope mismatch")
        if _contains_forbidden_label_material(report_payload):
            raise ValueError("Evaluator report contains forbidden label material")
        output = EvaluationReportOutputV1(
            organization_id=request.organization_id,
            batch_id=request.batch_id,
            report_kind=request.report_kind,
            report=report_payload,
            report_hash=report.report_hash,
        )
        return build_plugin_output(
            self.manifest,
            verified.invocation,
            output.model_dump(mode="json"),
            provider_calls=0,
        )


def _contains_forbidden_label_material(value: object) -> bool:
    if isinstance(value, dict):
        if set(value) & _FORBIDDEN_LABEL_KEYS:
            return True
        return any(_contains_forbidden_label_material(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_forbidden_label_material(item) for item in value)
    return False


def built_in_evaluator() -> EvaluationReportAdapter:
    return EvaluationReportAdapter(EvaluationService())


def built_in_evaluator_registry() -> PluginRegistry:
    adapter = built_in_evaluator()
    return PluginRegistry((adapter.manifest,))
