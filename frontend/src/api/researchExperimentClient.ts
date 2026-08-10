import {
  getEvaluation,
  getEvaluationMembers,
  getEvaluationMetrics,
  listEvaluationBatches,
} from '../api'
import type { ResearchExperimentClient } from '../contracts/researchWorkspace'

// This is an application-facing type boundary over api.js. The shared Axios
// transport remains the sole owner of organization and CSRF headers.
export const researchExperimentClient: ResearchExperimentClient = {
  listEvaluationBatches,
  getEvaluation,
  getEvaluationMembers,
  getEvaluationMetrics,
}
