import {
  chatWithProject,
  compareProjectRuns,
  getProject,
  getProjectRun,
  listProjectRuns,
  runProject,
} from '../api'
import type { ResearchWorkspaceClient } from '../contracts/researchWorkspace'

export const researchWorkspaceClient: ResearchWorkspaceClient = {
  getProject,
  getProjectRun,
  listProjectRuns,
  compareProjectRuns,
  runProject,
  chatWithProject,
}
