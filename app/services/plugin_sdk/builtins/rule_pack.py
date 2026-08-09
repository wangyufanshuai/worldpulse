"""Read-only Plugin SDK adapter for the active governed Rule Pack."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.core.trust_models import RulePackManifest
from app.services.rule_packs import active_rule_pack

from ..contracts import (
    PluginInputEnvelope,
    PluginManifest,
    PluginOutputEnvelope,
    build_plugin_manifest,
    build_plugin_output,
    canonical_hash,
)
from ..registry import PluginRegistry
from ..verification import verify_plugin_input


class ActiveRulePackRequestV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["active-rule-pack-request.v1"] = (
        "active-rule-pack-request.v1"
    )
    organization_id: str = Field(min_length=3, max_length=80)
    expected_rule_pack_id: str | None = Field(default=None, min_length=3, max_length=80)
    expected_manifest_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )


class ActiveRulePackOutputV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["active-rule-pack-output.v1"] = (
        "active-rule-pack-output.v1"
    )
    organization_id: str
    rule_pack: RulePackManifest
    rule_pack_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    activation_write: Literal[False] = False
    human_review_required: Literal[True] = True
    calibration_required: Literal[True] = True


class ActiveRulePackAdapter:
    """Resolve and authenticate the active pack without promotion capability."""

    plugin_id = "rule_pack.active"
    implementation_id = "builtin.rule_pack.active.v1"

    def __init__(
        self,
        resolver: Callable[[], RulePackManifest] = active_rule_pack,
    ) -> None:
        self._resolver = resolver
        self._manifest = build_plugin_manifest(
            plugin_id=self.plugin_id,
            kind="rule_pack",
            version="1.0.0",
            implementation_id=self.implementation_id,
            capabilities=("active.resolve", "lineage.verify"),
            permissions=("rule_pack.read",),
            input_schema="active-rule-pack-request.v1",
            output_schema="active-rule-pack-output.v1",
            configuration=self.configuration(),
        )

    @classmethod
    def configuration(cls) -> dict[str, Any]:
        return {
            "resolver": "active-rule-pack.v1",
            "write_operations": [],
            "human_review_required": True,
            "calibration_required": True,
            "manifest_integrity": "strict",
        }

    @property
    def manifest(self) -> PluginManifest:
        return self._manifest

    def execute(self, envelope: PluginInputEnvelope) -> PluginOutputEnvelope:
        self.manifest.verify_configuration(self.configuration())
        verified = verify_plugin_input(self.manifest, envelope)
        request = ActiveRulePackRequestV1.model_validate(verified.payload)
        if request.schema_version != self.manifest.input_schema:
            raise ValueError("active Rule Pack input schema does not match manifest")
        if verified.invocation.organization_id != request.organization_id:
            raise ValueError("active Rule Pack organization binding mismatch")
        pack = self._resolver()
        self._verify_pack(pack)
        if (
            request.expected_rule_pack_id is not None
            and request.expected_rule_pack_id != pack.rule_pack_id
        ):
            raise ValueError("active Rule Pack ID does not match pinned expectation")
        if (
            request.expected_manifest_hash is not None
            and request.expected_manifest_hash != pack.manifest_hash
        ):
            raise ValueError("active Rule Pack hash does not match pinned expectation")
        output = ActiveRulePackOutputV1(
            organization_id=request.organization_id,
            rule_pack=pack,
            rule_pack_hash=pack.manifest_hash,
        )
        return build_plugin_output(
            self.manifest,
            verified.invocation,
            output.model_dump(mode="json"),
            provider_calls=0,
        )

    @staticmethod
    def _verify_pack(pack: RulePackManifest) -> None:
        if pack.status != "active":
            raise ValueError("Rule Pack plugin resolved a non-active pack")
        expected_manifest = {
            "name": pack.name,
            "version": pack.version,
            "war_room_rule_version": pack.war_room_rule_version,
            "consistency_rule_version": pack.consistency_rule_version,
            "action_adapter_version": pack.action_adapter_version,
            "scoring_weights_version": pack.scoring_weights_version,
            "evidence_policy_version": pack.evidence_policy_version,
        }
        if pack.manifest != expected_manifest:
            raise ValueError("Rule Pack manifest columns do not match manifest payload")
        if canonical_hash(pack.manifest) != pack.manifest_hash:
            raise ValueError("Rule Pack manifest hash mismatch")


def built_in_rule_pack() -> ActiveRulePackAdapter:
    return ActiveRulePackAdapter()


def built_in_rule_pack_registry() -> PluginRegistry:
    adapter = built_in_rule_pack()
    return PluginRegistry((adapter.manifest,))
