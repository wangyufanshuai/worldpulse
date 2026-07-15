import { computed, onUnmounted, ref, watch } from 'vue'

export function useWarRoomReplayControls({ timelineEvents, selectedMapEntity, showToast }) {
  const replayPlaying = ref(false)
  const replaySpeed = ref(1)
  const activeReplayIndex = ref(0)
  let replayTimer = null

  const activeTimelineEvent = computed(() => timelineEvents.value[Math.min(activeReplayIndex.value, Math.max(0, timelineEvents.value.length - 1))] || timelineEvents.value[0] || null)
  const activeReplayDay = computed(() => activeTimelineEvent.value?.day ?? 0)
  const activeReplayProgress = computed(() => activeTimelineEvent.value?.position ?? 0)
  const activeEventKeys = computed(() => activeTimelineEvent.value?.eventKeys || [])

  function selectReplayDay(day) {
    const target = timelineEvents.value.findIndex(event => Number(event.day) >= Number(day))
    activeReplayIndex.value = target >= 0 ? target : Math.max(0, timelineEvents.value.length - 1)
    replayPlaying.value = false
    showToast?.(`已切换到 D+${day} 阶段`)
  }
  function toggleReplay() { replayPlaying.value = !replayPlaying.value }
  function cycleReplaySpeed() {
    replaySpeed.value = replaySpeed.value === 1 ? 2 : replaySpeed.value === 2 ? 4 : 1
    if (replayPlaying.value) restartReplayTimer()
  }
  function advanceReplay() {
    if (!timelineEvents.value.length) return
    activeReplayIndex.value = (activeReplayIndex.value + 1) % timelineEvents.value.length
    selectedMapEntity.value = null
  }
  function stopReplayTimer() {
    if (replayTimer) {
      window.clearInterval(replayTimer)
      replayTimer = null
    }
  }
  function restartReplayTimer() {
    stopReplayTimer()
    if (!replayPlaying.value) return
    replayTimer = window.setInterval(advanceReplay, Math.max(650, 1800 / replaySpeed.value))
  }

  watch(replayPlaying, restartReplayTimer)
  watch(replaySpeed, () => {
    if (replayPlaying.value) restartReplayTimer()
  })
  watch(() => timelineEvents.value.length, length => {
    if (!length) {
      activeReplayIndex.value = 0
      replayPlaying.value = false
      return
    }
    if (activeReplayIndex.value >= length) activeReplayIndex.value = length - 1
  })
  onUnmounted(stopReplayTimer)

  return {
    replayPlaying,
    replaySpeed,
    activeReplayIndex,
    activeTimelineEvent,
    activeReplayDay,
    activeReplayProgress,
    activeEventKeys,
    selectReplayDay,
    advanceReplay,
    toggleReplay,
    cycleReplaySpeed,
    stopReplayTimer,
  }
}
