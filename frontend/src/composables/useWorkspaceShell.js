import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Activity, BookOpen, Cable, Database, FileSearch, MapPinned, PackageCheck,
  ScanText, ServerCog, Settings, ShieldAlert, ShieldCheck, UsersRound,
} from 'lucide-vue-next'

const sectionKeys = ['overview', 'compiler', 'sandbox', 'analysis', 'negotiation', 'evaluation', 'graph', 'data', 'settings', 'replay', 'trust', 'evidence', 'ingestion', 'intelligence', 'operations']
const sectionMeta = {
  compiler: { key: 'compiler', label: '场景编译', title: '证据驱动场景编译与材料导入', desc: '安全导入材料、核验带原文定位的候选、冻结 Evidence Pack 并经异人审批创建运行。', icon: ScanText },
  negotiation: { key: 'negotiation', label: '外交博弈', title: '受控多轮外交博弈与舆论扩散', desc: '观察 12 Agent、6 Tick 的结构化提案、反提案、承诺账本与确定性数值投影。', icon: UsersRound },
  overview: { key: 'overview', label: '战情总览', title: '全球态势总览', desc: '地图、KPI、Agent 和时间线的指挥台总览。', icon: ShieldAlert },
  sandbox: { key: 'sandbox', label: '推演沙盘', title: '场景构建与推演参数', desc: '集中管理目标国家、供应链、政策动作和高级假设。', icon: MapPinned },
  analysis: { key: 'analysis', label: '智能分析', title: 'Agent 决策与风险解释', desc: '解释当前国家 Agent 的触发源、驱动因素、预期代价和关联事件。', icon: Activity },
  graph: { key: 'graph', label: '知识图谱', title: '因果链路与机制', desc: '查看边权重、滞后天数和链路传播机制。', icon: BookOpen },
  data: { key: 'data', label: '数据中台', title: '运行快照与展示合同', desc: '审计 ui_state、时间线、供应链和快照数据。', icon: Database },
  settings: { key: 'settings', label: '系统设置', title: '显示设置与待上线能力', desc: '管理显示层、策略边界和未上线控件说明。', icon: Settings },
  replay: { key: 'replay', label: '复盘包', title: 'Replay Pack 导出', desc: '生成 Markdown 与 JSON 审计清单。', icon: PackageCheck },
  trust: { key: 'trust', label: '可信度中心', title: '规则、校准与人工复核', desc: '检查 Rule Pack、晋升门槛、证据覆盖与不可绕过的一致性准入。', icon: ShieldCheck },
  evidence: { key: 'evidence', label: '证据中心', title: '证据注册表与时间截点治理', desc: '统一检索冻结快照、报告声明、引用链和证据包完整性。', icon: FileSearch },
  ingestion: { key: 'ingestion', label: '接入治理', title: '组织、连接器与受控采集', desc: '管理许可元数据、不可变策略、截点校验和采集任务审计。', icon: Cable },
  intelligence: { key: 'intelligence', label: '持续情报', title: '持续情报监测与告警闭环', desc: '从公开 RSS、Atom 和 JSON Feed 生成受治理材料与待核验场景候选。', icon: Cable },
  operations: { key: 'operations', label: '运维中心', title: '平台就绪度、Worker 与组织配额', desc: '监控执行节点心跳、安全排空、任务积压和组织资源容量。', icon: ServerCog },
  evaluation: { key: 'evaluation', label: '跨模式评估', title: '跨模式基准评估与决策质量', desc: '比较 deterministic、hybrid 与 negotiation 的安全门禁、稳定性和执行成本。', icon: ShieldCheck },
}

export function useWorkspaceShell({ projectId, section }) {
  const route = useRoute()
  const router = useRouter()
  const upcomingFeature = ref(null)
  const toastMessage = ref('')
  const decisionDrawer = ref(null)
  const entityDetailDrawer = ref(null)
  const runDetailsDrawer = ref(false)
  const commandSearchOpen = ref(false)
  const notificationDrawerOpen = ref(false)
  const commandQuery = ref('')
  let toastTimer = null
  const activeSection = computed(() => {
    const raw = String(route.params.section || section() || 'overview')
    return sectionKeys.includes(raw) ? raw : 'overview'
  })
  const activeSectionMeta = computed(() => sectionMeta[activeSection.value] || sectionMeta.overview)
  const topSections = [sectionMeta.overview, sectionMeta.compiler, sectionMeta.sandbox, sectionMeta.analysis, sectionMeta.negotiation, sectionMeta.evaluation, sectionMeta.graph, sectionMeta.data]
  const railSections = [sectionMeta.overview, sectionMeta.compiler, sectionMeta.sandbox, sectionMeta.negotiation, sectionMeta.evaluation, sectionMeta.graph, sectionMeta.analysis, sectionMeta.data, sectionMeta.ingestion, sectionMeta.intelligence, sectionMeta.evidence, sectionMeta.trust, sectionMeta.operations, sectionMeta.replay, sectionMeta.settings]
  const sectionPath = key => `/projects/${projectId()}/war-room/${key}`
  const navigateSection = key => router.push(sectionPath(key))
  const showToast = message => {
    toastMessage.value = message
    if (toastTimer) window.clearTimeout(toastTimer)
    toastTimer = window.setTimeout(() => { toastMessage.value = '' }, 2600)
  }
  const showUpcoming = (title, body) => {
    upcomingFeature.value = { title, body }
    showToast(`${title}：已打开说明`)
  }
  const disposeShell = () => {
    if (toastTimer) window.clearTimeout(toastTimer)
    toastTimer = null
  }
  return {
    router, sectionKeys, sectionMeta, topSections, railSections, activeSection,
    activeSectionMeta, upcomingFeature, toastMessage, decisionDrawer,
    entityDetailDrawer, runDetailsDrawer, commandSearchOpen,
    notificationDrawerOpen, commandQuery, sectionPath, navigateSection,
    showToast, showUpcoming, disposeShell,
  }
}
