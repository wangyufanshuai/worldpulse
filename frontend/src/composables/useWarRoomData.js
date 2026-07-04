import { compareProjectRuns, getWarRoomPresets, getWarRoomReplayPack, getWarRoomWorkspace, runProjectWarRoom } from '../api'

export function useWarRoomData(projectId) {
  const projectIdValue = () => (typeof projectId === 'function' ? projectId() : projectId)

  return {
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
