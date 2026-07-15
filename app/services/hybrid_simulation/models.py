from __future__ import annotations

from pydantic import BaseModel, Field

from app.core.models import WarRoomRun


class DeterministicActionModifier(BaseModel):
    schema_version: str = "deterministic-action-modifier.v1"
    adapter_version: str = "worldpulse-action-adapter.v0.11"
    modifier_id: str
    proposal_id: str
    turn: int
    action_type: str
    policy_actions: list[str] = Field(default_factory=list)
    chain_adjustments: dict[str, dict[str, float]] = Field(default_factory=dict)
    rationale_refs: list[str] = Field(default_factory=list)
    no_numeric_effect_reason: str | None = None
    modifier_hash: str


class HybridModifierBundle(BaseModel):
    schema_version: str = "hybrid-modifier-bundle.v1"
    adapter_version: str = "worldpulse-action-adapter.v0.11"
    accepted_proposal_ids: list[str]
    modifiers: list[DeterministicActionModifier]
    scenario_patch: dict
    bundle_hash: str


class HybridReplayRecord(BaseModel):
    schema_version: str = "hybrid-replay-record.v1"
    baseline_result_hash: str
    final_result_hash: str
    consistency_audit_hash: str
    modifier_bundle_hash: str
    accepted_proposal_ids: list[str]
    baseline_diff: dict = Field(default_factory=dict)
    hash_scope: str = "WarRoomRun before hybrid_trace metadata"
    replay_hash: str


class HybridSimulationOutcome(BaseModel):
    final_result: WarRoomRun
    modifier_bundle: HybridModifierBundle
    replay_record: HybridReplayRecord
