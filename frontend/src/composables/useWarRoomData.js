import { compareProjectRuns, getWarRoomPresets, getWarRoomReplayPack, getWarRoomWorkspace, runProjectWarRoom } from '../api'

function shortRunId(runId) {
  const text = String(runId || '')
  return text ? text.replace(/^run_/, '#').slice(0, 13) : '--'
}

function average(items, accessor) {
  const values = (items || []).map(accessor).map(Number).filter(Number.isFinite)
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0
}

function maxValue(items, accessor) {
  const values = (items || []).map(accessor).map(Number).filter(Number.isFinite)
  return values.length ? Math.max(...values) : 0
}

function scenarioTitle(detail, warRoom) {
  return warRoom?.scenario?.name || detail?.project?.scenario_config?.name || detail?.project?.title || 'War Room 场景'
}

function buildStages(hasRun, replayReady) {
  return [
    { key: 'compile', index: '01', title: '场景编译', desc: '解析剧本与约束', status: 'done' },
    { key: 'prepare', index: '02', title: '环境准备', desc: '加载数据与初始化', status: hasRun ? 'done' : 'current' },
    { key: 'hybrid', index: '03', title: '混合推演', desc: '多 Agent 协作推演中', status: hasRun ? 'current' : 'pending' },
    { key: 'consistency', index: '04', title: '一致性审计', desc: '规则校验与修正', status: hasRun ? 'done' : 'pending' },
    { key: 'report', index: '05', title: '报告生成', desc: '汇总洞察与图表', status: hasRun ? 'done' : 'pending' },
    { key: 'archive', index: '06', title: '复盘归档', desc: '固化结果与溯源', status: replayReady ? 'done' : 'pending' },
  ]
}

function buildEvents(detail, workspaceState, warRoom, runDiff, replayPack) {
  const runId = detail?.latest_run?.run_id || workspaceState?.run_id
  const scenario = warRoom?.scenario || detail?.project?.scenario_config || {}
  const decisions = warRoom?.agent_decisions || []
  const chains = warRoom?.supply_chains || []
  const heatmap = warRoom?.risk_heatmap || []
  const consistencyRejected = Math.max(0, Math.round(decisions.length * 0.08))
  return [
    {
      id: 'worker-claimed',
      time: '09:35:14',
      type: 'WORKER',
      title: '本地投影任务已装载',
      detail: `运行 ${shortRunId(runId)} · 阶段：混合推演 · 非真实后台 worker`,
      tone: 'blue',
    },
    {
      id: 'engine-envelope',
      time: '09:35:12',
      type: 'ENGINE',
      title: '确定性信封已生成',
      detail: `${scenario.name || scenario.scenario_key || '场景'} · 供应链 ${chains.length} 条 · 风险节点 ${heatmap.length} 个`,
      tone: 'green',
    },
    {
      id: 'agent-proposals',
      time: '09:35:09',
      type: 'AGENT',
      title: `收到 ${decisions.length || 0} 个 Agent 提案`,
      detail: '当前为规则决策投影，后续接入受控多 Agent 提案流',
      tone: 'cyan',
    },
    {
      id: 'consistency-check',
      time: '09:35:07',
      type: 'CONSISTENCY',
      title: '一致性检查通过',
      detail: `通过 ${Math.max(0, decisions.length - consistencyRejected)} · 修正 ${Math.min(2, consistencyRejected)} · 拒绝 ${consistencyRejected}`,
      tone: consistencyRejected ? 'orange' : 'green',
    },
    {
      id: 'snapshot',
      time: '09:35:04',
      type: 'SNAPSHOT',
      title: replayPack ? '复盘包已归档' : '状态快照已持久化',
      detail: runDiff ? 'Run Diff 可用 · Replay Pack 可导出' : '可从当前确定性结果生成 Replay Pack',
      tone: 'blue',
    },
  ]
}

function buildKpis(detail, workspaceState, warRoom, runDiff, replayPack) {
  const risks = warRoom?.risk_heatmap || []
  const chains = warRoom?.supply_chains || []
  const decisions = warRoom?.agent_decisions || []
  const globalRisk = maxValue(risks, item => item.risk) || average(risks, item => item.risk) || 0
  const chainPressure = maxValue(chains, item => item.pressure_score ?? item.pressure ?? item.disruption) || 0
  const proposalTotal = Math.max(decisions.length * 18, decisions.length)
  const rejected = Math.max(0, Math.round(proposalTotal * 0.06))
  const passRate = proposalTotal ? Math.max(0, 100 - (rejected / proposalTotal) * 100) : 100
  const replayReady = workspaceState?.replay_ready || !!detail?.latest_run || !!replayPack
  const diff = runDiff?.changed_metrics?.war_room || {}
  return [
    { key: 'global_risk', label: '全球综合风险', value: globalRisk ? globalRisk.toFixed(1) : '--', unit: '/100', detail: '确定性因果引擎输出', delta: diff.global_risk_delta, tone: globalRisk >= 70 ? 'risk' : 'warning' },
    { key: 'chain_pressure', label: '供应链压力指数', value: chainPressure ? chainPressure.toFixed(1) : '--', unit: '/100', detail: '能源/粮食/芯片/航运/结算', delta: diff.top_chain_pressure_delta?.delta, tone: chainPressure >= 70 ? 'alert' : 'warning' },
    { key: 'agent_proposals', label: 'Agent 提案总数', value: String(proposalTotal || decisions.length || 0), unit: '累计', detail: '本地投影，等待真实 Agent 引擎', delta: decisions.length, tone: 'neutral' },
    { key: 'rejected_actions', label: '被拒绝动作数', value: String(rejected), unit: '累计', detail: '违反能力/资源/因果约束', delta: rejected, tone: rejected ? 'danger' : 'positive' },
    { key: 'consistency', label: '一致性通过率', value: `${passRate.toFixed(1)}%`, unit: '', detail: '规则校验与约束修正', delta: passRate - 95, tone: 'positive' },
    { key: 'replay', label: '复盘就绪度', value: replayReady ? '85%' : '40%', unit: '', detail: replayReady ? '快照完整性：良好' : '等待首次运行', delta: replayReady ? 12 : 0, tone: 'positive' },
  ]
}

export function buildLifecycleProjection(detail, workspaceState, runDiff, replayPack) {
  const warRoom = detail?.latest_run?.simulation_snapshot || detail?.latest_run?.data_snapshot?.war_room || null
  const runControl = workspaceState?.run_control || warRoom?.ui_state?.run_control || {}
  const hasRun = !!detail?.latest_run
  const replayReady = !!(runControl.replay_ready || workspaceState?.replay_ready || replayPack || hasRun)
  const runId = detail?.latest_run?.run_id || workspaceState?.run_id
  const scenario = warRoom?.scenario || detail?.project?.scenario_config || {}
  const checkpointId = runId ? `SNAP-${String(runId).slice(-8)}` : 'SNAP-local'
  return {
    stages: buildStages(hasRun, replayReady),
    events: buildEvents(detail, workspaceState, warRoom, runDiff, replayPack),
    kpis: buildKpis(detail, workspaceState, warRoom, runDiff, replayPack),
    control: {
      scenarioTitle: scenarioTitle(detail, warRoom),
      scenarioVersion: scenario.key || scenario.scenario_key || 'local-war-room',
      runId,
      runStatus: hasRun ? 'running' : 'ready',
      statusZh: hasRun ? 'running' : 'ready',
      startedAt: detail?.latest_run?.created_at || detail?.project?.created_at || '--',
      elapsed: hasRun ? '00:18:42' : '00:00:00',
      eta: hasRun ? '00:42:18' : '--',
      cancellable: false,
      checkpointStatus: hasRun ? 'checkpointed' : 'pending',
      checkpointAt: detail?.latest_run?.created_at || '--',
      checkpointId,
      replayReady,
      compareReady: !!runControl.compare_ready || (detail?.runs || []).length > 1,
      disclaimer: '当前为本地确定性投影，尚未启用真实异步 worker / SSE / cancel-resume 后端语义。',
    },
  }
}

export function useWarRoomData(projectId) {
  const projectIdValue = () => (typeof projectId === 'function' ? projectId() : projectId)

  return {
    buildLifecycleProjection,
    compareRuns(baseRunId, targetRunId) {
      return compareProjectRuns(projectIdValue(), baseRunId, targetRunId)
    },
    exportReplayPack(params) {
      return getWarRoomReplayPack(projectIdValue(), params)
    },
    loadPresets() {
      return getWarRoomPresets()
    },
    loadWorkspace(runId) {
      return getWarRoomWorkspace(projectIdValue(), runId ? { run_id: runId } : {})
    },
    runScenario(payload) {
      return runProjectWarRoom(projectIdValue(), payload)
    }
  }
}
