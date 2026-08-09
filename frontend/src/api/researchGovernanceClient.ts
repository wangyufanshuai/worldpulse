import {
  cloneScenarioDraft,
  getEvidencePack,
  getCurrentOrganization,
  getProjectEvidenceSummary,
  getScenarioDraft,
  listScenarioCandidates,
  listScenarioDrafts,
  reviewScenarioDraft,
  searchEvidence,
  submitScenarioDraft,
  syncProjectEvidence,
} from '../api'
import type { ResearchGovernanceClient } from '../contracts/researchWorkspace'

export const researchGovernanceClient: ResearchGovernanceClient = {
  getCurrentOrganization,
  getProjectEvidenceSummary,
  getEvidencePack,
  syncProjectEvidence,
  searchEvidence,
  listScenarioCandidates,
  listScenarioDrafts,
  getScenarioDraft,
  submitScenarioDraft,
  reviewScenarioDraft,
  cloneScenarioDraft,
}
