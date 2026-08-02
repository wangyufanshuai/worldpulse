from __future__ import annotations

from time import perf_counter

from fastapi import HTTPException

from app.core.models import RunJobStatus, WarRoomRun, WarRoomScenarioRequest
from app.services.agent_contract import build_mock_agent_batch
from app.services.agent_runtime import run_agent_runtime, runtime_config_from_env
from app.services.consistency import evaluate_war_room_result
from app.services.consistency.hashing import stable_hash
from app.services.consistency.projector import project_consistency_audit
from app.services.consistency.projection import build_action_projection_audit
from app.services.hybrid_simulation import run_hybrid_simulation
from app.services.projects import persist_war_room_result
from app.services.security import redact_secrets
from app.services.simulation_runtime import SimulationRuntimeApplicationPort, simulation_runtime_service
from app.services.reviews import create_review_case
from app.services.negotiation import run_negotiation

from . import checkpoints, repository, steps


simulation_runtime: SimulationRuntimeApplicationPort = simulation_runtime_service


def run_war_room(request: WarRoomScenarioRequest) -> WarRoomRun:
    """Compatibility patch seam delegating to the Simulation Runtime port."""
    return simulation_runtime.run_war_room(request)


PHASES = [
    ("scenario_compile", 12, "ENGINE", "Scenario compiled", "场景参数已通过 schema 编译，确定性规则输入已冻结。"),
    ("environment_prepare", 28, "WORKER", "Environment prepared", "国家、供应链、政策动作和审计上下文已装载。"),
    ("deterministic_run", 56, "ENGINE", "Deterministic engine completed", "风险数值、供应链压力、热力图、时间线和因果图已由规则引擎生成。"),
    ("consistency_audit", 74, "CONSISTENCY", "Consistency audit started", "只读评估器正在检查数值、引用、时序、因果和证据合同。"),
    ("report_generate", 88, "SNAPSHOT", "Report projection prepared", "报告、图谱和旧版 workspace 投影已准备写入。"),
    ("replay_archive", 100, "SNAPSHOT", "Replay archive ready", "Replay Pack 可从已完成 research_run 生成，无需重新调用 LLM。"),
]


def lifecycle_fault_hook(phase: str, moment: str) -> None:
    """Test-only fault injection seam; production is a no-op."""

    return None


def process_one_queued_job(worker_id: str | None = None, *, prefer_evaluation: bool | None = None) -> RunJobStatus | None:
    job = repository.claim_next_job(worker_id=worker_id, prefer_evaluation=prefer_evaluation)
    if job is None:
        return None
    if worker_id:
        from app.services.operations import heartbeat_registered_worker

        heartbeat_registered_worker(worker_id, status="busy", current_job_id=job.run_id)
    try:
        return process_job(job.run_id)
    except Exception as exc:  # pragma: no cover - defensive audit path
        steps.fail_active_step(job.run_id, exc)
        safe_error = redact_secrets(str(exc)) or "Lifecycle execution failed"
        current = repository.get_job(job.run_id)
        repository.append_event(
            job.run_id,
            "WORKER",
            current.current_phase,
            "Run attempt failed",
            safe_error,
            payload={"error": type(exc).__name__, "attempt_id": current.current_attempt_id},
        )
        return repository.handle_attempt_failure(job.run_id, exc)


def process_job(run_id: str) -> RunJobStatus:
    job = repository.get_job(run_id)
    if job.job_kind == "calibration":
        from app.services.calibration import process_calibration_job
        return process_calibration_job(run_id)
    worker_id = job.worker_id
    projected_run_id = repository.get_projected_result_run_id(run_id)
    if projected_run_id:
        if repository.get_latest_artifact_content(run_id, "projection") is None:
            repository.add_artifact(
                run_id,
                "projection",
                "research-run-projection.v1",
                {"project_id": job.project_id, "result_run_id": projected_run_id, "workspace_compatible": True, "recovered": True},
            )
        repository.append_event(
            run_id,
            "SNAPSHOT",
            "replay_archive",
            "Completed projection recovered",
            "检测到该 lifecycle job 已存在完整 v1 投影，已幂等恢复完成状态，未重复写入 research_runs。",
            payload={"result_run_id": projected_run_id},
        )
        return repository.update_job_status(
            run_id,
            status="completed",
            phase="replay_archive",
            progress=100,
            result_run_id=projected_run_id,
            completed=True,
        )
    lifecycle_started = perf_counter()
    phase_durations_ms: dict[str, int] = {}
    scenario = WarRoomScenarioRequest(**job.scenario)
    attempt_id = job.current_attempt_id
    if not attempt_id:
        raise HTTPException(status_code=409, detail="Lifecycle job has no active execution attempt")

    checkpoint = checkpoints.load_verified_checkpoint(job)
    repository.set_attempt_resume_step(attempt_id, checkpoint.next_step_key)
    result = checkpoint.result
    proposals = checkpoint.proposals
    constraint_context = checkpoint.constraint_context
    report = checkpoint.report
    result_run_id = checkpoint.result_run_id
    previous_step = checkpoint.previous_step
    start_index = len(checkpoint.completed_steps)
    if checkpoint.completed_steps:
        repository.append_event(
            run_id,
            "SNAPSHOT",
            checkpoint.completed_steps[-1].step_key,
            "Verified checkpoint restored",
            "已验证阶段版本、输入链、输出 Hash 与 Artifact 完整性；后续执行从下一个阶段继续。",
            payload={
                "attempt_id": attempt_id,
                "completed_step_count": start_index,
                "last_step_id": checkpoint.completed_steps[-1].step_id,
                "resume_from_step": checkpoint.next_step_key,
            },
        )

    for index, (phase, progress, event_type, title, detail) in enumerate(PHASES[start_index:], start=start_index):
        phase_started = perf_counter()
        repository.heartbeat_job(run_id, worker_id)
        if worker_id:
            from app.services.operations import heartbeat_registered_worker

            heartbeat_registered_worker(worker_id, status="busy", current_job_id=run_id)
        interrupted = _apply_boundary_control(run_id)
        if interrupted:
            return interrupted
        step_input = {
            "run_id": run_id,
            "engine_mode": job.engine_mode,
            "scenario_hash": stable_hash(scenario.model_dump(mode="json")),
            "previous_step_id": previous_step.step_id if previous_step else None,
            "previous_output_hash": previous_step.output_hash if previous_step else None,
            "previous_artifact_refs": previous_step.artifact_refs if previous_step else [],
            "job_kind": job.job_kind,
            "rule_pack_id": job.rule_pack_id,
            "rule_pack_hash": job.rule_pack_hash,
        }
        step = steps.begin_step(run_id, phase, attempt_id, step_input)
        artifacts_before = {item.artifact_id for item in repository.get_artifacts(run_id)}
        lifecycle_fault_hook(phase, "before")
        repository.mark_phase(run_id, phase, progress, event_type, title, detail, payload={"phase_index": index, "progress": progress})
        if phase == "scenario_compile":
            repository.add_artifact(run_id, "scenario", "scenario.v1", scenario.model_dump(mode="json"))
        elif phase == "environment_prepare":
            repository.add_artifact(
                run_id,
                "environment_manifest",
                "environment-manifest.v1",
                {
                    "scenario_hash": stable_hash(scenario.model_dump(mode="json")),
                    "target_countries": scenario.target_countries,
                    "target_chains": scenario.target_chains,
                    "policy_actions": scenario.policy_actions,
                    "seed": scenario.seed,
                    "rule_pack_id": job.rule_pack_id,
                    "rule_pack_hash": job.rule_pack_hash,
                },
            )
        elif phase == "deterministic_run":
            result = run_war_room(scenario)
            repository.add_artifact(run_id, "war_room_result", "war-room-result.v1", result.model_dump())
            if job.engine_mode == "mock_agent":
                batch = build_mock_agent_batch(result, run_id=run_id, seed=job.seed)
                proposals = batch.proposals
                constraint_context = batch.constraint_context
                artifact = repository.add_artifact(run_id, "agent_action_proposals", batch.schema_version, batch.model_dump(mode="json"))
                repository.append_event(
                    run_id,
                    "AGENT",
                    "deterministic_run",
                    "Deterministic Mock Agent proposals recorded",
                    f"已生成 {len(proposals)} 个可重复的结构化提案；尚未进入确定性数值转换。",
                    payload={
                        "provider": batch.provider,
                        "proposal_count": len(proposals),
                        "batch_hash": batch.batch_hash,
                        "artifact_id": artifact.artifact_id,
                    },
                )
            elif job.engine_mode in {"controlled_agent", "hybrid"}:
                runtime = run_agent_runtime(
                    result,
                    run_id=run_id,
                    config=runtime_config_from_env(job.seed, job.runtime_profile),
                    should_stop=lambda: repository.get_job(run_id).status in {"pausing", "paused", "cancelling", "cancelled"},
                )
                proposals = runtime.proposals
                constraint_context = runtime.constraint_context
                runtime_artifact = repository.add_artifact(run_id, "agent_runtime_audit", runtime.schema_version, runtime.model_dump(mode="json"))
                proposal_artifact = repository.add_artifact(
                    run_id,
                    "agent_action_proposals",
                    "agent-action-batch.v1",
                    {
                        "schema_version": "agent-action-batch.v1",
                        "provider": runtime.provider,
                        "model": runtime.model,
                        "mode": runtime.mode,
                        "runtime_hash": runtime.runtime_hash,
                        "proposals": [proposal.model_dump(mode="json") for proposal in proposals],
                        "constraint_context": constraint_context.model_dump(mode="json"),
                    },
                )
                repository.append_event(
                    run_id,
                    "AGENT",
                    "deterministic_run",
                    "Controlled Agent Runtime completed",
                    f"受控 Runtime 记录 {len(proposals)} 个结构化提案；模式 {runtime.mode}，失败调用 {runtime.failed_calls}。",
                    payload={
                        "provider": runtime.provider,
                        "model": runtime.model,
                        "mode": runtime.mode,
                        "proposal_count": len(proposals),
                        "call_count": runtime.total_calls,
                        "estimated_tokens": runtime.total_estimated_tokens,
                        "failed_calls": runtime.failed_calls,
                        "runtime_hash": runtime.runtime_hash,
                        "runtime_artifact_id": runtime_artifact.artifact_id,
                        "proposal_artifact_id": proposal_artifact.artifact_id,
                        "fallback_reason": runtime.fallback_reason,
                    },
                )
        elif phase == "consistency_audit":
            if result is None:
                raise HTTPException(status_code=500, detail="Consistency audit requires a deterministic War Room result")
            if job.engine_mode == "negotiation":
                result, negotiation_summary = run_negotiation(
                    result,
                    run_id=run_id,
                    seed=job.seed or 42,
                    runtime_profile=job.runtime_profile,
                    should_stop=lambda: repository.get_job(run_id).status in {"pausing", "paused", "cancelling", "cancelled"},
                )
                interrupted = _apply_boundary_control(run_id)
                if interrupted:
                    return interrupted
                repository.add_artifact(run_id, "negotiation_summary", "negotiation-summary.v1", negotiation_summary)
                repository.add_artifact(run_id, "negotiation_final_result", "war-room-result.negotiation.v1", result.model_dump(mode="json"))
            report = evaluate_war_room_result(
                result,
                run_id=run_id,
                created_at=repository.now_iso(),
                proposals=proposals,
                constraint_context=constraint_context,
            )
            project_consistency_audit(run_id, report, repository)
            for decision in report.proposal_decisions:
                if decision.outcome in {"constrained", "rejected", "expired"}:
                    create_review_case(
                        "agent_action_admission",
                        "agent_action",
                        f"{run_id}:{decision.proposal_id}",
                        f"Agent action outcome requires human acknowledgement: {decision.outcome}",
                        severity="high" if decision.outcome == "rejected" else "warning",
                        payload={
                            "run_id": run_id,
                            "proposal_id": decision.proposal_id,
                            "outcome": decision.outcome,
                            "rule_version": decision.rule_version,
                            "audit_hash": decision.audit_hash,
                            "projection_status": decision.projection_status,
                        },
                    )
            if job.engine_mode == "hybrid":
                outcome = run_hybrid_simulation(result, proposals, report, seed=job.seed or 42)
                if outcome.projection_audit is not None:
                    repository.add_artifact(
                        run_id,
                        "agent_action_projection_audit",
                        outcome.projection_audit.schema_version,
                        outcome.projection_audit.model_dump(mode="json"),
                    )
                modifier_artifact = repository.add_artifact(
                    run_id,
                    "deterministic_action_modifiers",
                    outcome.modifier_bundle.schema_version,
                    outcome.modifier_bundle.model_dump(mode="json"),
                )
                final_artifact = repository.add_artifact(
                    run_id,
                    "hybrid_war_room_result",
                    "war-room-result.hybrid.v1",
                    outcome.final_result.model_dump(mode="json"),
                )
                replay_artifact = repository.add_artifact(
                    run_id,
                    "hybrid_replay_record",
                    outcome.replay_record.schema_version,
                    outcome.replay_record.model_dump(mode="json"),
                )
                repository.append_event(
                    run_id,
                    "ENGINE",
                    "consistency_audit",
                    "Audited actions applied by deterministic adapter",
                    f"{len(outcome.modifier_bundle.accepted_proposal_ids)} 个已接受提案完成固定映射与确定性重算。",
                    payload={
                        "accepted_proposal_count": len(outcome.modifier_bundle.accepted_proposal_ids),
                        "modifier_bundle_hash": outcome.modifier_bundle.bundle_hash,
                        "baseline_result_hash": outcome.replay_record.baseline_result_hash,
                        "final_result_hash": outcome.replay_record.final_result_hash,
                        "replay_hash": outcome.replay_record.replay_hash,
                        "modifier_artifact_id": modifier_artifact.artifact_id,
                        "final_artifact_id": final_artifact.artifact_id,
                        "replay_artifact_id": replay_artifact.artifact_id,
                    },
                )
                result = outcome.final_result
            elif proposals and report is not None:
                projection_audit = build_action_projection_audit(
                    run_id=run_id,
                    consistency_audit_hash=report.audit_hash,
                    final_result_hash=stable_hash(result.model_dump(mode="json")),
                    proposals=proposals,
                    decisions=report.proposal_decisions,
                    projection_mode="audit_only",
                )
                repository.add_artifact(
                    run_id,
                    "agent_action_projection_audit",
                    projection_audit.schema_version,
                    projection_audit.model_dump(mode="json"),
                )
        elif phase == "report_generate":
            if result is None:
                raise HTTPException(status_code=500, detail="Report projection requires a deterministic War Room result")
            repository.add_artifact(
                run_id,
                "report_projection_manifest",
                "report-projection-manifest.v1",
                {
                    "result_hash": stable_hash(result.model_dump(mode="json")),
                    "workspace_compatible": True,
                    "run_diff_compatible": True,
                    "replay_pack_compatible": True,
                },
            )
        elif phase == "replay_archive":
            if result is None:
                raise HTTPException(status_code=500, detail="Replay archive requires a deterministic War Room result")
            started = repository.get_job(run_id).started_at
            persisted = persist_war_room_result(job.project_id, result, started=started, lifecycle_job_id=run_id)
            result_run_id = persisted.latest_run.run_id if persisted.latest_run else None
            repository.add_artifact(
                run_id,
                "projection",
                "research-run-projection.v1",
                {"project_id": job.project_id, "result_run_id": result_run_id, "workspace_compatible": True},
            )
            repository.append_event(
                run_id,
                "SNAPSHOT",
                "replay_archive",
                "Lifecycle run completed",
                "确定性结果已投影回 research_runs，Run Diff / Replay Pack / workspace 可继续使用。",
                payload={"result_run_id": result_run_id},
            )
        lifecycle_fault_hook(phase, "after")
        phase_durations_ms[phase] = max(0, int((perf_counter() - phase_started) * 1000))
        new_artifacts = [
            item.artifact_id for item in repository.get_artifacts(run_id)
            if item.artifact_id not in artifacts_before
        ]
        step_output = {
            "phase": phase,
            "progress": progress,
            "result_hash": stable_hash(result.model_dump(mode="json")) if result is not None else None,
            "proposal_count": len(proposals),
            "consistency_audit_hash": report.audit_hash if report is not None else None,
            "result_run_id": result_run_id,
            "artifact_refs": new_artifacts,
        }
        previous_step = steps.complete_step(step.step_id, step_output, new_artifacts)

    if result is None:
        raise HTTPException(status_code=500, detail="Lifecycle executor did not produce a War Room result")
    repository.add_artifact(
        run_id,
        "lifecycle_metrics",
        "lifecycle-metrics.v1",
        {
            "worker_id": worker_id,
            "attempt_count": repository.get_job(run_id).attempt_count,
            "phase_durations_ms": phase_durations_ms,
            "total_duration_ms": max(0, int((perf_counter() - lifecycle_started) * 1000)),
            "event_count": len(repository.get_events(run_id)),
            "engine_mode": job.engine_mode,
        },
        step_id=previous_step.step_id if previous_step is not None else None,
    )
    return repository.update_job_status(
        run_id,
        status="completed",
        phase="replay_archive",
        progress=100,
        result_run_id=result_run_id,
        terminal_reason="completed",
        completed=True,
    )


def _apply_boundary_control(run_id: str) -> RunJobStatus | None:
    job = repository.get_job(run_id)
    if job.status == "cancelling":
        repository.append_event(run_id, "WORKER", job.current_phase, "Run cancelled", "任务在阶段边界取消，未投影到 research_runs。", payload={"status": "cancelled"})
        return repository.update_job_status(run_id, status="cancelled", progress=job.progress, completed=True)
    if job.status == "pausing":
        repository.append_event(run_id, "WORKER", job.current_phase, "Run paused", "任务已在阶段边界暂停，可恢复后继续排队执行。", payload={"status": "paused"})
        return repository.update_job_status(run_id, status="paused", progress=job.progress)
    if job.status in {"cancelled", "paused", "failed", "completed"}:
        return job
    return None
