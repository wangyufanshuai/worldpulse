from __future__ import annotations

from dataclasses import dataclass, field

from app.core.models import RunJobStatus, RunStepRecord, WarRoomRun
from app.services.agent_contract.models import AgentActionProposal, AgentConstraintContext
from app.services.consistency.hashing import stable_hash
from app.services.consistency.models import ConsistencyAuditReport
from app.services.consistency.models import AgentActionProjectionAudit
from app.services.consistency.projection import verify_action_projection_audit

from . import repository, steps


@dataclass
class CheckpointState:
    completed_steps: list[RunStepRecord] = field(default_factory=list)
    artifacts: dict[str, dict] = field(default_factory=dict)
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
    state = CheckpointState()
    previous: RunStepRecord | None = None

    for definition in steps.STEP_DEFINITIONS:
        candidates = [
            item for item in all_steps
            if item.step_key == definition.key
            and item.step_version == definition.version
            and item.status == "completed"
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
            state.artifacts[artifact_type] = payload
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

    proposal_batch = state.artifacts.get("agent_action_proposals")
    if proposal_batch:
        state.proposals = [AgentActionProposal.model_validate(item) for item in proposal_batch.get("proposals", [])]
        raw_context = proposal_batch.get("constraint_context")
        if raw_context:
            state.constraint_context = AgentConstraintContext.model_validate(raw_context)

    audit = state.artifacts.get("consistency_audit")
    if audit:
        state.report = ConsistencyAuditReport.model_validate(audit)

    projection_audit = state.artifacts.get("agent_action_projection_audit")
    if projection_audit:
        state.projection_audit = AgentActionProjectionAudit.model_validate(projection_audit)
        verify_action_projection_audit(state.projection_audit)

    if job.engine_mode == "hybrid" and state.artifacts.get("hybrid_war_room_result"):
        state.result = WarRoomRun.model_validate(state.artifacts["hybrid_war_room_result"])
    if job.engine_mode == "negotiation" and state.artifacts.get("negotiation_final_result"):
        state.result = WarRoomRun.model_validate(state.artifacts["negotiation_final_result"])

    projection = state.artifacts.get("projection")
    if projection:
        state.result_run_id = projection.get("result_run_id")
