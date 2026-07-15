from __future__ import annotations

from fastapi import HTTPException

from app.core.models import RunJobStatus, WarRoomScenarioRequest
from app.services.agent_contract import build_mock_agent_batch
from app.services.consistency import evaluate_war_room_result
from app.services.consistency.projector import project_consistency_audit
from app.services.projects import persist_war_room_result
from app.services.war_room_engine import run_war_room

from . import repository


PHASES = [
    ("scenario_compile", 12, "ENGINE", "Scenario compiled", "场景参数已通过 schema 编译，确定性规则输入已冻结。"),
    ("environment_prepare", 28, "WORKER", "Environment prepared", "国家、供应链、政策动作和审计上下文已装载。"),
    ("deterministic_run", 56, "ENGINE", "Deterministic engine completed", "风险数值、供应链压力、热力图、时间线和因果图已由规则引擎生成。"),
    ("consistency_audit", 74, "CONSISTENCY", "Consistency audit started", "只读评估器正在检查数值、引用、时序、因果和证据合同。"),
    ("report_generate", 88, "SNAPSHOT", "Report projection prepared", "报告、图谱和旧版 workspace 投影已准备写入。"),
    ("replay_archive", 100, "SNAPSHOT", "Replay archive ready", "Replay Pack 可从已完成 research_run 生成，无需重新调用 LLM。"),
]


def process_one_queued_job() -> RunJobStatus | None:
    job = repository.claim_next_job()
    if job is None:
        return None
    try:
        return process_job(job.run_id)
    except Exception as exc:  # pragma: no cover - defensive audit path
        repository.append_event(job.run_id, "WORKER", job.current_phase, "Run failed", str(exc), payload={"error": type(exc).__name__})
        return repository.update_job_status(
            job.run_id,
            status="failed",
            phase=job.current_phase,
            progress=job.progress,
            error_code=type(exc).__name__,
            error_message=str(exc),
            completed=True,
        )


def process_job(run_id: str) -> RunJobStatus:
    job = repository.get_job(run_id)
    scenario = WarRoomScenarioRequest(**job.scenario)
    repository.add_artifact(run_id, "scenario", "scenario.v1", scenario.model_dump())

    result = None
    proposals = []
    constraint_context = None
    for index, (phase, progress, event_type, title, detail) in enumerate(PHASES):
        interrupted = _apply_boundary_control(run_id)
        if interrupted:
            return interrupted
        repository.mark_phase(run_id, phase, progress, event_type, title, detail, payload={"phase_index": index, "progress": progress})
        if phase == "deterministic_run":
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
        elif phase == "consistency_audit":
            if result is None:
                raise HTTPException(status_code=500, detail="Consistency audit requires a deterministic War Room result")
            report = evaluate_war_room_result(
                result,
                run_id=run_id,
                created_at=repository.now_iso(),
                proposals=proposals,
                constraint_context=constraint_context,
            )
            project_consistency_audit(run_id, report, repository)

    if result is None:
        raise HTTPException(status_code=500, detail="Lifecycle executor did not produce a War Room result")

    interrupted = _apply_boundary_control(run_id)
    if interrupted:
        return interrupted

    started = repository.get_job(run_id).started_at
    detail = persist_war_room_result(job.project_id, result, started=started, lifecycle_job_id=run_id)
    result_run_id = detail.latest_run.run_id if detail.latest_run else None
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
    return repository.update_job_status(run_id, status="completed", phase="replay_archive", progress=100, result_run_id=result_run_id, completed=True)


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
