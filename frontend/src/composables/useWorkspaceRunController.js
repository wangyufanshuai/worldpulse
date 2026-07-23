import { nextTick } from 'vue'
import { chatWithProject, getProject, getProjectRun, runProject } from '../api'

export function useWorkspaceRunController(ctx) {
  async function loadWorkspaceState(runId = ctx.selectedRunId.value) {
    if (!ctx.isWarRoom.value) {
      ctx.workspaceState.value = null
      return
    }
    try { ctx.workspaceState.value = await ctx.warRoomData.loadWorkspace(runId) }
    catch { ctx.workspaceState.value = null }
  }
  async function loadPresets() {
    if (!ctx.isWarRoom.value || ctx.presets.value) return
    try {
      ctx.presets.value = await ctx.warRoomData.loadPresets()
      if (!ctx.scenarioDraft.target_countries.length || !ctx.scenarioDraft.target_chains.length) {
        const scenario = ctx.presets.value.scenarios?.find(item => item.key === ctx.scenarioDraft.scenario_key)
        if (scenario) {
          ctx.scenarioDraft.target_countries = [...(scenario.target_countries || [])]
          ctx.scenarioDraft.target_chains = [...(scenario.target_chains || [])]
        }
      }
    } catch { ctx.presets.value = null }
  }
  async function load(runId = ctx.selectedRunId.value) {
    ctx.detail.value = runId ? await getProjectRun(ctx.projectId(), runId) : await getProject(ctx.projectId())
    ctx.selectedRunId.value = ctx.detail.value?.latest_run?.run_id || ''
    await loadWorkspaceState(ctx.selectedRunId.value)
    ctx.syncScenarioDraft()
    await loadPresets()
    ctx.prepareCompareDefaults()
    await ctx.loadRunDiff()
    await ctx.loadTrustSummary()
    await ctx.loadEvidenceSummary()
    await ctx.loadIngestionGovernance()
    await ctx.loadContinuousIntelligence()
    await ctx.loadScenarioCompiler()
    await ctx.loadOperationsCenter()
    if (ctx.activeSection.value === 'negotiation') await ctx.negotiation.load()
    await ctx.loadEvaluationCenter()
    await nextTick()
    ctx.renderGraph()
  }
  async function run() {
    if (!ctx.auth.permissions.value.canRun) return ctx.showToast('当前角色无运行权限')
    ctx.running.value = true
    try {
      if (ctx.isWarRoom.value) {
        await ctx.runLifecycle.create({ engine_mode: ctx.lifecycleEngineMode.value, scenario: ctx.scenarioPayload(), seed: ctx.scenarioDraft.seed || 42 })
        ctx.showToast('生命周期任务已排队；请启动或保持 worker 运行')
        return
      }
      ctx.detail.value = await runProject(ctx.projectId(), ctx.runMode.value)
      ctx.selectedRunId.value = ctx.detail.value?.latest_run?.run_id || ''
      await loadWorkspaceState(ctx.selectedRunId.value)
      ctx.resetReplayArtifacts()
      ctx.syncScenarioDraft()
      ctx.prepareCompareDefaults(true)
      await ctx.loadRunDiff()
      await nextTick()
      ctx.renderGraph()
    } finally { ctx.running.value = false }
  }
  async function send() {
    ctx.chatting.value = true
    try {
      await chatWithProject(ctx.projectId(), ctx.message.value)
      ctx.message.value = ''
      await load(ctx.selectedRunId.value)
    } finally { ctx.chatting.value = false }
  }
  return { load, loadWorkspaceState, loadPresets, run, send }
}
