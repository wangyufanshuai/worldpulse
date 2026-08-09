import { computed, getCurrentScope, onScopeDispose, ref, watch } from 'vue'

function useBlobUrl(source, type) {
  let activeUrl = ''

  function release() {
    if (!activeUrl) return
    URL.revokeObjectURL(activeUrl)
    activeUrl = ''
  }

  const url = computed(() => {
    const content = source()
    if (!activeUrl) {
      activeUrl = URL.createObjectURL(new Blob([content], { type }))
    }
    return activeUrl
  })
  const stop = watch(source, release, { flush: 'sync' })

  if (getCurrentScope()) {
    onScopeDispose(() => {
      stop()
      release()
    })
  }

  return url
}

export function useWarRoomArtifacts({ detail, isWarRoom, runVersions, selectedRunId, warRoomData, dataJsonPreview, showToast }) {
  const runDiff = ref(null)
  const runDiffLoading = ref(false)
  const compareBaseRunId = ref('')
  const compareTargetRunId = ref('')
  const replayPack = ref(null)
  const replayPackLoading = ref(false)
  const replayPreviewOpen = ref(false)

  const warRoomDiff = computed(() => runDiff.value?.changed_metrics?.war_room || null)
  const markdownUrl = useBlobUrl(() => detail.value?.report?.markdown || '', 'text/markdown;charset=utf-8')
  const replayPackUrl = useBlobUrl(() => replayPack.value?.markdown || '', 'text/markdown;charset=utf-8')
  const replayPackJsonUrl = useBlobUrl(() => replayPack.value?.artifacts?.json_manifest || '{}', 'application/json;charset=utf-8')
  const replayPackFilename = computed(() => `${String(detail.value?.project?.title || 'worldpulse').toLowerCase().replace(/[^a-z0-9]+/g, '-')}-${replayPack.value?.run_id || 'war-room'}-replay-pack.md`)
  const replayPackJsonFilename = computed(() => replayPackFilename.value.replace(/\.md$/, '-manifest.json'))
  const markdownPreview = computed(() => (replayPack.value?.markdown || '').slice(0, 6000))

  function prepareCompareDefaults(forceLatest = false) {
    if (!isWarRoom.value || runVersions.value.length < 2) return
    const runs = [...runVersions.value]
    const latest = selectedRunId.value || runs[0]?.run_id
    const previous = runs.find(run => run.run_id !== latest)?.run_id
    if (forceLatest || !compareTargetRunId.value) compareTargetRunId.value = latest
    if (forceLatest || !compareBaseRunId.value || compareBaseRunId.value === compareTargetRunId.value) compareBaseRunId.value = previous || ''
  }

  async function loadRunDiff() {
    if (!isWarRoom.value || !compareBaseRunId.value || !compareTargetRunId.value || compareBaseRunId.value === compareTargetRunId.value) {
      runDiff.value = null
      return
    }
    runDiffLoading.value = true
    try {
      runDiff.value = await warRoomData.compareRuns(compareBaseRunId.value, compareTargetRunId.value)
    } finally {
      runDiffLoading.value = false
    }
  }

  async function exportReplayPack() {
    if (!isWarRoom.value || !detail.value?.latest_run) return
    replayPackLoading.value = true
    try {
      const params = warRoomDiff.value ? { base_run_id: compareBaseRunId.value, target_run_id: compareTargetRunId.value } : { run_id: selectedRunId.value || detail.value.latest_run.run_id }
      replayPack.value = await warRoomData.exportReplayPack(params)
      replayPreviewOpen.value = true
    } finally {
      replayPackLoading.value = false
    }
  }

  async function copyRunId() {
    const runId = selectedRunId.value || detail.value?.latest_run?.run_id
    if (!runId) {
      showToast?.('当前没有可复制的运行 ID')
      return
    }
    try {
      await navigator.clipboard.writeText(runId)
    } catch {
      const input = document.createElement('textarea')
      input.value = runId
      input.style.position = 'fixed'
      input.style.opacity = '0'
      document.body.appendChild(input)
      input.select()
      document.execCommand('copy')
      input.remove()
    }
    showToast?.('运行 ID 已复制')
  }

  function downloadUiState() {
    const runId = selectedRunId.value || detail.value?.latest_run?.run_id
    if (!runId) {
      showToast?.('请先运行一次沙盘')
      return
    }
    const url = URL.createObjectURL(new Blob([dataJsonPreview.value], { type: 'application/json;charset=utf-8' }))
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `worldpulse_${detail.value?.project?.project_id || 'project'}_${runId}_ui_state.json`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 0)
    showToast?.('ui_state.json 已生成')
  }

  function resetReplayArtifacts() {
    replayPack.value = null
    replayPreviewOpen.value = false
  }

  return {
    runDiff,
    runDiffLoading,
    compareBaseRunId,
    compareTargetRunId,
    replayPack,
    replayPackLoading,
    replayPreviewOpen,
    warRoomDiff,
    markdownUrl,
    replayPackUrl,
    replayPackJsonUrl,
    replayPackFilename,
    replayPackJsonFilename,
    markdownPreview,
    prepareCompareDefaults,
    loadRunDiff,
    exportReplayPack,
    copyRunId,
    downloadUiState,
    resetReplayArtifacts,
  }
}
