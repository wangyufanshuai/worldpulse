import { computed, watch } from 'vue'

const PHASES = ['scenario_compile', 'environment_prepare', 'deterministic_run', 'consistency_audit', 'report_generate', 'replay_archive']
const PHASE_META = {
  scenario_compile: ['01', '场景编译', '解析剧本与约束'],
  environment_prepare: ['02', '环境准备', '加载数据与初始化'],
  deterministic_run: ['03', '混合推演', '确定性规则推演中'],
  consistency_audit: ['04', '一致性审计', '规则校验与修正'],
  report_generate: ['05', '报告生成', '汇总洞察与图表'],
  replay_archive: ['06', '复盘归档', '固化结果与溯源'],
}

export function useRunLifecycleConsole({ runLifecycle, lifecycleProjection, runVersions, running, showToast, onCompleted }) {
  const activeLifecycleRun = computed(() => runLifecycle.activeRun.value)
  const lifecycleStages = computed(() => {
    const job = activeLifecycleRun.value
    if (!job) return lifecycleProjection.value.stages
    const index = Math.max(0, PHASES.indexOf(job.current_phase))
    return PHASES.map((phase, phaseIndex) => {
      const [stageIndex, title, desc] = PHASE_META[phase]
      const terminalDone = job.status === 'completed'
      const stopped = ['failed', 'cancelled', 'paused'].includes(job.status)
      return {
        key: phase,
        index: stageIndex,
        title,
        desc,
        status: terminalDone || phaseIndex < index ? 'done' : phaseIndex === index && !stopped ? 'current' : 'pending',
      }
    })
  })
  const lifecycleControl = computed(() => {
    const base = lifecycleProjection.value.control
    const job = activeLifecycleRun.value
    if (!job) {
      const historicalStatus = base.replayReady ? 'completed' : 'ready'
      return {
        ...base,
        statusZh: historicalStatus,
        runStatus: historicalStatus,
        currentPhaseZh: base.replayReady ? '历史完成' : '等待运行',
        progress: base.replayReady ? 100 : 0,
        resultRunId: base.runId,
        canPause: false,
        canCancel: false,
        canResume: false,
        canRetry: false,
        busy: running.value,
        disclaimer: base.replayReady
          ? '历史 v1 run：可复盘/对比；新运行将进入 v2 生命周期队列。'
          : base.disclaimer,
      }
    }
    const status = job.status
    const resultRunId = job.result_run_id
    return {
      ...base,
      runId: job.run_id,
      resultRunId,
      runStatus: status,
      statusZh: status,
      currentPhase: job.current_phase,
      currentPhaseZh: PHASE_META[job.current_phase]?.[1] || job.current_phase,
      progress: job.progress,
      engineMode: job.engine_mode,
      startedAt: job.started_at || job.created_at,
      checkpointAt: job.updated_at,
      checkpointId: resultRunId ? `SNAP-${String(resultRunId).slice(-8)}` : `JOB-${String(job.run_id).slice(-8)}`,
      checkpointStatus: status,
      replayReady: status === 'completed' && !!resultRunId,
      compareReady: base.compareReady || (status === 'completed' && !!resultRunId && runVersions.value.length > 1),
      canPause: ['queued', 'preparing', 'running'].includes(status),
      canCancel: ['queued', 'preparing', 'running', 'pausing', 'paused'].includes(status),
      canResume: ['paused', 'pausing'].includes(status),
      canRetry: ['failed', 'cancelled'].includes(status),
      busy: ['queued', 'preparing', 'running', 'pausing', 'cancelling'].includes(status),
      disclaimer: status === 'completed'
        ? '真实生命周期任务已完成；结果已投影回 v1 workspace / Run Diff / Replay Pack。'
        : '当前为真实本地 Run Lifecycle：状态、事件、检查点来自 SQLite + 独立 worker。',
    }
  })
  const lifecycleEventsForDisplay = computed(() => runLifecycle.events.value.length ? runLifecycle.events.value : lifecycleProjection.value.events)
  const lifecycleEventMode = computed(() => runLifecycle.events.value.length ? 'live' : 'projection')

  async function control(action, message) {
    await runLifecycle[action]()
    showToast?.(message)
  }

  watch(() => activeLifecycleRun.value?.status, async (status, previous) => {
    const job = activeLifecycleRun.value
    if (status === 'completed' && previous !== 'completed' && job?.result_run_id) {
      await onCompleted?.(job.result_run_id)
      showToast?.('生命周期任务已完成，workspace 已刷新')
    }
  })

  return {
    activeLifecycleRun,
    lifecycleControl,
    lifecycleEventMode,
    lifecycleEventsForDisplay,
    lifecycleStages,
    pauseLifecycleRun: () => control('pause', '暂停请求已写入生命周期状态'),
    resumeLifecycleRun: () => control('resume', '生命周期任务已恢复排队'),
    cancelLifecycleRun: () => control('cancel', '取消请求已写入生命周期状态'),
    retryLifecycleRun: () => control('retry', '已创建 retry 生命周期任务'),
  }
}
