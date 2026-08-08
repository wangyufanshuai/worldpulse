from __future__ import annotations

from dataclasses import dataclass, field

from app.core.models import RunArtifactSummary, RunJobStatus, RunStepRecord, WarRoomRun
from app.services.agent_contract.models import AgentActionProposal, AgentConstraintContext
from app.services.consistency.hashing import stable_hash
from app.services.consistency.models import ConsistencyAuditReport
from app.services.consistency.models import AgentActionProjectionAudit
from app.services.consistency.projection import verify_action_projection_audit
from app.services.negotiation import ConsistencyAuditSource, ProjectionAuditSource

from . import repository, steps
from .execution_contract import select_job_execution_contract
from .kernel_shadow import (
    KERNEL_SHADOW_ARTIFACT_TYPE,
    kernel_shadow_policy_for_job,
    verify_persisted_kernel_shadow_artifact,
)


@dataclass
class CheckpointState:
    completed_steps: list[RunStepRecord] = field(default_factory=list)
    artifacts: dict[str, dict] = field(default_factory=dict)
    artifact_summaries: dict[str, RunArtifactSummary] = field(default_factory=dict)
    result: WarRoomRun | None = None
    proposals: list[AgentActionProposal] = field(default_factory=list)
    constraint_context: AgentConstraintContext | None = None
    report: ConsistencyAuditReport | None = None
    projection_audit: AgentActionProjectionAudit | None = None
    result_run_id: str | None = None

    @property
    def previous_step(self) -> RunStepRecord | None:
        return self.completed_steps[-1] if self.completed_steps else None

    @property
    def next_step_key(self) -> str | None:
        completed = {item.step_key for item in self.completed_steps}
        return next((item.key for item in steps.STEP_DEFINITIONS if item.key not in completed), None)


def load_verified_checkpoint(job: RunJobStatus) -> CheckpointState:
    scenario_hash = stable_hash(job.scenario)
    all_steps = steps.get_steps(job.run_id)
    execution_contract = select_job_execution_contract(job)
    state = CheckpointState()
    previous: RunStepRecord | None = None

    for definition in steps.step_definitions_for_runtime_profile(job.runtime_profile):
        candidates = [
            item for item in all_steps
            if item.step_key == definition.key
            and item.step_version == definition.version
            and item.status == "completed"
            and (
                not execution_contract.is_v2
                or item.attempt_id == job.current_attempt_id
            )
        ]
        selected = next(
            (
                item for item in reversed(candidates)
                if _step_is_valid(job, item, previous, scenario_hash)
            ),
            None,
        )
        if selected is None:
            break
        for artifact_id in selected.artifact_refs:
            artifact_type, payload = repository.get_artifact_record_by_id(job.run_id, artifact_id)
            summary = repository.get_artifact_summary_by_id(job.run_id, artifact_id)
            if summary.artifact_type != artifact_type:
                raise ValueError("Checkpoint Artifact summary type mismatch")
            state.artifacts[artifact_type] = payload
            state.artifact_summaries[artifact_type] = summary
        state.completed_steps.append(selected)
        previous = selected

    _restore_execution_state(job, state)
    return state


def _step_is_valid(
    job: RunJobStatus,
    step: RunStepRecord,
    previous: RunStepRecord | None,
    scenario_hash: str,
) -> bool:
    if stable_hash(step.input) != step.input_hash:
        return False
    if step.output_hash is None or stable_hash(step.output) != step.output_hash:
        return False
    if step.input.get("run_id") != job.run_id:
        return False
    if step.input.get("engine_mode") != job.engine_mode:
        return False
    if step.input.get("scenario_hash") != scenario_hash:
        return False
    if step.input.get("previous_step_id") != (previous.step_id if previous else None):
        return False
    if step.input.get("previous_output_hash") != (previous.output_hash if previous else None):
        return False
    if step.input.get("previous_artifact_refs", []) != (previous.artifact_refs if previous else []):
        return False
    if sorted(step.output.get("artifact_refs", [])) != sorted(step.artifact_refs):
        return False
    try:
        for artifact_id in step.artifact_refs:
            repository.get_artifact_content_by_id(job.run_id, artifact_id)
    except Exception:
        return False
    return True


def _restore_execution_state(job: RunJobStatus, state: CheckpointState) -> None:
    baseline = state.artifacts.get("war_room_result")
    if baseline:
        state.result = WarRoomRun.model_validate(baseline)

    shadow_payload = state.artifacts.get(KERNEL_SHADOW_ARTIFACT_TYPE)
    shadow_policy = kernel_shadow_policy_for_job(job)
    if baseline and shadow_policy is not None and shadow_payload is None:
        raise ValueError("Pinned Kernel shadow checkpoint is missing its Artifact")
    if shadow_payload is not None:
        if baseline is None or state.result is None:
            raise ValueError("Kernel shadow checkpoint is missing source result")
        if shadow_policy is None:
            raise ValueError("Kernel shadow checkpoint has no pinned job policy")
        source_summary = state.artifact_summaries.get("war_room_result")
        if source_summary is None:
            raise ValueError("Kernel shadow checkpoint is missing source Artifact summary")
        verify_persisted_kernel_shadow_artifact(
            shadow_payload,
            job=job,
            source_result=state.result,
            source_artifact=source_summary,
        )

    proposal_batch = state.artifacts.get("agent_action_proposals")
    if proposal_batch:
        state.proposals = [AgentActionProposal.model_validate(item) for item in proposal_batch.get("proposals", [])]
        raw_context = proposal_batch.get("constraint_context")
        if raw_context:
            state.constraint_context = AgentConstraintContext.model_validate(raw_context)

    audit = state.artifacts.get("consistency_audit")
    if audit:
        if audit.get("schema_version") == "consistency-audit.v3":
            state.report = ConsistencyAuditSource.model_validate(
                audit
            ).inner_report()
        else:
            state.report = ConsistencyAuditReport.model_validate(audit)

    projection_audit = state.artifacts.get("agent_action_projection_audit")
    if projection_audit:
        if projection_audit.get("schema_version") == "agent-action-projection-audit.v2":
            ProjectionAuditSource.model_validate(projection_audit)
        else:
            state.projection_audit = AgentActionProjectionAudit.model_validate(projection_audit)
            verify_action_projection_audit(state.projection_audit)

    if job.engine_mode == "hybrid" and state.artifacts.get("hybrid_war_room_result"):
        state.result = WarRoomRun.model_validate(state.artifacts["hybrid_war_room_result"])
    if job.engine_mode == "negotiation" and state.artifacts.get("negotiation_final_result"):
        state.result = WarRoomRun.model_validate(state.artifacts["negotiation_final_result"])

    projection = state.artifacts.get("projection")
    if projection:
        state.result_run_id = projection.get("result_run_id")
