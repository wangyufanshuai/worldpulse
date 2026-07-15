import { computed, reactive, ref } from 'vue'

export function useWarRoomScenarioDraft({ presets, warRoom, showToast }) {
  const fallbackCountries = ['USA', 'CHN', 'JPN', 'KOR', 'TWN', 'IND', 'EU', 'RUS', 'SAU', 'BRA'].map(code => ({ code }))
  const fallbackChains = ['energy', 'food', 'chips', 'shipping', 'settlement'].map(key => ({ key }))
  const policyActions = [
    { key: 'sanctions', label: '制裁', desc: '提高金融结算和贸易压力。' },
    { key: 'counter_sanctions', label: '反制裁', desc: '触发互惠贸易与金融压力。' },
    { key: 'energy_reroute', label: '能源改道', desc: '降低能源风险，但增加物流负载。' },
    { key: 'food_export_limit', label: '粮食出口限制', desc: '提高粮食与舆论压力。' },
    { key: 'alliance_deterrence', label: '联盟威慑', desc: '把部分风险转向军事信号。' },
    { key: 'liquidity_support', label: '流动性支持', desc: '缓冲金融结算压力。' },
    { key: 'public_messaging', label: '舆论沟通', desc: '降低公众情绪压力。' }
  ]
  const chainLabels = { energy: '能源', food: '粮食', chips: '关键芯片', shipping: '海运贸易', settlement: '金融结算' }
  const channelLabels = { energy: '能源', food: '粮食', trade: '贸易', chips: '芯片', financial: '金融', public_opinion: '舆论', military: '军事', settlement: '结算', shipping: '海运', social_stability: '社会稳定' }
  const scenarioLabels = { strait_blockade_30d: '海峡危机升级推演', energy_export_cut: '能源出口中断', food_shortfall: '粮食减产与出口限制' }
  const countryNames = { USA: '美国', CHN: '中国', JPN: '日本', KOR: '韩国', TWN: '台湾', IND: '印度', EU: '欧盟', RUS: '俄罗斯', SAU: '中东', BRA: '巴西' }

  const scenarioDraft = reactive({
    scenario_key: 'strait_blockade_30d',
    duration_days: 30,
    intensity: 0.65,
    propagation: 0.42,
    target_countries: [],
    target_chains: [],
    policy_actions: [],
    country_overrides: { JPN: { energy_dependency: 92 } },
    chain_overrides: { energy: { substitution: 38 }, settlement: { lag_days: 3 } }
  })
  const scenarioTitle = ref('台海危机升级推演 · 2025 Q3')
  const scenarioBackground = ref('台湾局势持续紧张，周边军事活动增加，美中战略博弈加剧。')
  const influenceFactor = ref(80)
  const retaliationFactor = ref(70)
  const supplyFactor = ref(60)
  const pressureFactor = ref(40)

  const countryOptions = computed(() => presets.value?.countries || warRoom.value?.country_agents || fallbackCountries)
  const chainOptions = computed(() => presets.value?.supply_chains || warRoom.value?.supply_chains || fallbackChains)
  const presetScenarios = computed(() => {
    const scenarios = presets.value?.scenarios || []
    return scenarios.length ? scenarios : [
      { key: 'strait_blockade_30d', name: '30-day Strait Blockade' },
      { key: 'energy_export_cut', name: 'Energy Export Interruption' },
      { key: 'food_shortfall', name: 'Food Shortfall / Export Controls' }
    ]
  })
  const factorControls = computed(() => [
    { key: 'influence', label: '美国介入力度', value: influenceFactor.value, model: influenceFactor },
    { key: 'retaliation', label: '中国反制强度', value: retaliationFactor.value, model: retaliationFactor },
    { key: 'supply', label: '日本响应程度', value: supplyFactor.value, model: supplyFactor },
    { key: 'pressure', label: '全球舆论压力', value: pressureFactor.value, model: pressureFactor }
  ])

  function chainName(key, fallback = '') { return chainLabels[key] || fallback || key || '--' }
  function riskChannel(key) { return channelLabels[key] || key || '--' }
  function scenarioLabel(scenario) { return scenario ? scenarioLabels[scenario.key || scenario.scenario_key] || scenario.name || scenario.key : '' }
  function policyActionLabel(key) { return policyActions.find(item => item.key === key)?.label || key }
  function countryNameShort(code) { return countryNames[code] || code }
  function scenarioPayload() { return JSON.parse(JSON.stringify(scenarioDraft)) }
  function toggleDraftList(field, value) {
    const list = scenarioDraft[field]
    scenarioDraft[field] = list.includes(value) ? list.filter(item => item !== value) : [...list, value]
    if (field === 'policy_actions') showToast?.(`${policyActionLabel(value)}${scenarioDraft[field].includes(value) ? '已启用' : '已移除'}`)
  }
  function clearPolicyActions() {
    scenarioDraft.policy_actions = []
    showToast?.('触发条件已重置')
  }
  function selectAllCountries() {
    scenarioDraft.target_countries = countryOptions.value.map(item => item.code || item.country_code).filter(Boolean).slice(0, 10)
    showToast?.('已添加全部国家 Agent 可变因素')
  }
  function syncScenarioDraft(detail) {
    const config = detail?.latest_run?.data_snapshot?.scenario_config || detail?.project?.scenario_config || {}
    Object.assign(scenarioDraft, {
      scenario_key: config.scenario_key || config.key || scenarioDraft.scenario_key,
      duration_days: Number(config.duration_days || scenarioDraft.duration_days),
      intensity: Number(config.intensity ?? scenarioDraft.intensity),
      propagation: Number(config.propagation ?? scenarioDraft.propagation),
      target_countries: [...(config.target_countries || scenarioDraft.target_countries || [])],
      target_chains: [...(config.target_chains || scenarioDraft.target_chains || [])],
      policy_actions: [...(config.policy_actions || scenarioDraft.policy_actions || [])],
      country_overrides: { ...scenarioDraft.country_overrides, ...(config.country_overrides || {}) },
      chain_overrides: { ...scenarioDraft.chain_overrides, ...(config.chain_overrides || {}) }
    })
  }
  function applySelectedScenarioDefaults() {
    const scenario = presets.value?.scenarios?.find(item => item.key === scenarioDraft.scenario_key)
    if (!scenario) return
    scenarioDraft.duration_days = Number(scenario.duration_days || scenarioDraft.duration_days)
    scenarioDraft.target_countries = [...(scenario.target_countries || [])]
    scenarioDraft.target_chains = [...(scenario.target_chains || [])]
  }

  return {
    chainLabels,
    channelLabels,
    countryNames,
    fallbackChains,
    fallbackCountries,
    policyActions,
    scenarioDraft,
    scenarioTitle,
    scenarioBackground,
    factorControls,
    countryOptions,
    chainOptions,
    presetScenarios,
    chainName,
    riskChannel,
    scenarioLabel,
    policyActionLabel,
    countryNameShort,
    scenarioPayload,
    toggleDraftList,
    clearPolicyActions,
    selectAllCountries,
    syncScenarioDraft,
    applySelectedScenarioDefaults,
  }
}
