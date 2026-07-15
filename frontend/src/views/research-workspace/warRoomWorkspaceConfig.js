export const eventFilterOptions = [
  { key: 'military', label: '军事事件', tone: 'blue' },
  { key: 'diplomatic', label: '外交事件', tone: 'green' },
  { key: 'economic', label: '经济事件', tone: 'orange' },
  { key: 'social', label: '社会事件', tone: 'purple' },
  { key: 'turning', label: '关键拐点', tone: 'red' },
  { key: 'selected_entity', label: '只看选中实体', tone: 'green' },
]

export const graphTypeOptions = [
  { key: 'event', label: '事件' }, { key: 'country', label: '国家' },
  { key: 'supply_chain', label: '供应链' }, { key: 'market', label: '市场' },
  { key: 'public_opinion', label: '舆论' }, { key: 'alliance', label: '联盟' },
  { key: 'policy_response', label: '政策' },
]

export const prompts = ['证据链最弱的一环是什么？', '有没有历史反例？', '如果传播系数降低，结论怎么变？', '哪些国家 Agent 最值得观察？']
export const decisionLabels = { changed: '已变化', new: '新增', unchanged: '未变化' }

export const localizedText = {
  'Scenario initialized; baseline dependencies and alliance posture locked.': '场景初始化，基线依赖与联盟姿态已锁定。',
  'First-order logistics, deterrence, and market repricing begin.': '一阶物流、威慑与市场重定价开始显现。',
  'Supply-chain substitution and public narrative become dominant uncertainties.': '供应链替代与公共叙事成为主要不确定性。',
  'Second-order policy responses, sanctions, and financial stress propagate.': '二阶政策响应、制裁与金融压力继续扩散。',
  'High import dependency and rising supply-chain pressure make energy substitution the first stabilizer.': '高进口依赖与供应链压力上升，使能源替代成为首要稳定动作。',
  'Semiconductor exposure dominates the simulated causal chain.': '半导体暴露成为当前因果链中的主导压力。',
  'Protects critical capacity while raising trade friction.': '保护关键产能，但会抬高贸易摩擦。',
}
