import { nextTick } from 'vue'

export function useWarRoomInteractions(ctx) {
  const fullEntityId = (type, id) => {
    if (!id) return ''
    const raw = String(id)
    if (raw.includes(':')) return raw
    return ({ country: `country:${raw}`, supply_chain: `chain:${raw}`, event: `event:${raw}`, unit: `unit:${raw}` })[type] || raw
  }
  const detailForSelectedEntity = () => {
    const entity = ctx.selectedMapEntity.value
    if (!entity) return null
    const id = fullEntityId(entity.type, entity.id)
    return ctx.entityDetails.value[id] || ctx.entityDetails.value[entity.id] || null
  }
  const openEntityDetail = (type, id, payload = {}) => {
    const fullId = fullEntityId(type, id)
    const detail = ctx.entityDetails.value[fullId] || ctx.entityDetails.value[id]
    ctx.entityDetailDrawer.value = detail || {
      id: fullId || id, type,
      title_zh: payload.title || payload.label || payload.country_name || id,
      summary_zh: payload.detail || payload.explanation || '该实体来自当前 War Room 沙盘图层。',
      metrics: [{ label_zh: '当前日', value: `D+${ctx.activeReplayDay.value}` }],
      actions: [{ key: 'focus', label_zh: '在地图中定位', action_type: 'focus', enabled: true }],
    }
  }
  const mapTooltipFor = (type, id, payload = {}) => {
    const fullId = fullEntityId(type, id)
    const detail = ctx.entityDetails.value[fullId] || ctx.entityDetails.value[id]
    const point = payload || {}
    return {
      x: Math.max(18, Math.min(860, Number(point.x || 500) * ctx.mapZoom.value / 1.2)),
      y: Math.max(18, Math.min(470, Number(point.y || 280) * ctx.mapZoom.value / 1.25)),
      title: detail?.title_zh || point.title || point.label || point.country_name || point.key || id,
      detail: detail?.summary_zh || point.detail || point.mechanism || point.dominant_channel_zh || '点击查看详情',
    }
  }
  const selectMapCountry = country => {
    ctx.replayPlaying.value = false
    ctx.selectedMapEntity.value = { type: 'country', id: country.code, day: ctx.activeReplayDay.value, payload: country }
    ctx.selected.value = {
      ...country, kind: '国家风险', label: country.country_name || ctx.countryNameShort(country.code),
      country_code: country.code,
      explanation: `${country.country_name || ctx.countryNameShort(country.code)} 风险为 ${Math.round(country.risk)}/100，主导通道为 ${ctx.riskChannel(country.dominant_channel)}。`,
    }
    openEntityDetail('country', country.code, country)
  }
  const selectSupplyChain = chain => {
    ctx.replayPlaying.value = false
    ctx.selectedMapEntity.value = { type: 'supply_chain', id: chain.key, day: ctx.activeReplayDay.value, payload: chain }
    ctx.selected.value = { ...chain, kind: '供应链瓶颈', label: ctx.chainName(chain.key, chain.name), explanation: `当前压力 ${Math.round(Number(chain.pressure || chain.disruption || 0))}/100。` }
    openEntityDetail('supply_chain', chain.key, chain)
  }
  const selectCausalEdge = (edge, edgeId = ctx.edgeKey(edge)) => {
    ctx.replayPlaying.value = false
    ctx.focusedGraphEdgeId.value = edgeId
    ctx.focusedEdgeKey.value = ctx.edgeKey(edge)
    ctx.selectedMapEntity.value = { type: 'causal_edge', id: edgeId, day: ctx.activeReplayDay.value, payload: edge }
    ctx.selected.value = { ...edge, kind: '因果边', label: `${ctx.edgeLabel(edge.source)} → ${ctx.edgeLabel(edge.target)}`, explanation: edge.explanation || edge.mechanism || edge.relation || '因果机制来自当前沙盘运行快照。' }
    openEntityDetail('causal_edge', edgeId, edge)
  }
  const selectMilitaryUnit = unit => {
    ctx.replayPlaying.value = false
    ctx.selectedMapEntity.value = { type: 'unit', id: unit.key, day: ctx.activeReplayDay.value, payload: unit }
    ctx.selected.value = { ...unit, kind: '军事单元', label: unit.label, explanation: `${unit.label} 用于表达当前态势中的军事部署信号。` }
    openEntityDetail('unit', unit.key, unit)
  }
  const selectMapEvent = event => {
    ctx.replayPlaying.value = false
    const index = ctx.timelineEvents.value.findIndex(item => item.eventKeys?.includes(event.key) || item.day === event.day)
    if (index >= 0) ctx.activeReplayIndex.value = index
    ctx.selectedMapEntity.value = { type: 'event', id: event.key, day: event.day ?? ctx.activeReplayDay.value, payload: event }
    ctx.selected.value = { ...event, kind: '事件热点', label: event.title, country_code: event.country_code || (event.key === 'china' ? 'CHN' : event.key === 'us' ? 'USA' : event.key === 'japan' ? 'JPN' : 'TWN'), explanation: event.detail || event.title }
    openEntityDetail('event', event.key, event)
  }
  const selectTimelineEvent = (event, index = ctx.timelineEvents.value.findIndex(item => item.key === event.key)) => {
    ctx.replayPlaying.value = false
    if (index >= 0) ctx.activeReplayIndex.value = index
    ctx.selectedMapEntity.value = null
    ctx.selected.value = { ...event, kind: '时间线事件', label: event.title, explanation: event.detail }
    ctx.entityDetailDrawer.value = ctx.entityDetails.value[`timeline:${event.key}`] || {
      id: `timeline:${event.key}`, type: 'timeline', title_zh: event.title, summary_zh: event.detail,
      metrics: [{ label_zh: '发生日', value: event.time }, { label_zh: '全局风险', value: `${Math.round(event.globalRisk || ctx.currentGlobalRisk.value)}/100` }],
      related_events: [], actions: [{ key: 'focus', label_zh: '在时间线中定位', action_type: 'focus', enabled: true }],
    }
  }
  const activateCommandResult = item => {
    ctx.commandSearchOpen.value = false
    ctx.commandQuery.value = ''
    if (item.type === 'timeline' || String(item.id).startsWith('timeline:')) {
      const index = ctx.timelineEvents.value.findIndex(event => event.key === item.ref || `timeline:${event.key}` === item.id || Number(event.day) === Number(item.day))
      if (index >= 0) selectTimelineEvent(ctx.timelineEvents.value[index], index)
      ctx.showToast(`已定位时间线：${item.title_zh}`)
      return
    }
    const ref = item.ref || item.id
    if (String(ref).startsWith('country:')) {
      const code = String(ref).split(':')[1]
      selectMapCountry(ctx.mapCountries.value.find(row => row.code === code) || { code, country_name: item.title_zh })
    } else if (String(ref).startsWith('chain:')) {
      const key = String(ref).split(':')[1]
      selectSupplyChain((ctx.warRoom.value?.supply_chains || []).find(row => row.key === key) || { key, name: item.title_zh })
    } else if (String(ref).startsWith('event:')) {
      const key = String(ref).split(':')[1]
      selectMapEvent(ctx.mapEvents.value.find(row => row.key === key) || { key, title: item.title_zh })
    } else if (String(ref).startsWith('edge:')) {
      const edge = ctx.mapCausalEdges.value.find(row => row.id === ref)
      if (edge) selectCausalEdge(edge.edge, edge.id)
    } else if (String(ref).startsWith('decision:')) ctx.navigateSection('analysis')
    if (item.section && item.section !== ctx.activeSection.value) ctx.navigateSection(item.section)
    openEntityDetail(item.type, item.ref || item.id, item)
    ctx.showToast(`已定位：${item.title_zh}`)
  }
  const handleEntityAction = (action, detail) => {
    if (action.action_type === 'section' && action.section) {
      ctx.navigateSection(action.section)
      ctx.showToast(`已进入${ctx.sectionMeta[action.section]?.label || action.section}`)
      return
    }
    if (action.action_type === 'replay') return openReplayShortcut()
    ctx.showToast(`${detail.title_zh || detail.title} 已在地图中高亮`)
  }
  const cloneFromCurrentRun = () => { ctx.syncScenarioDraft(); ctx.navigateSection('sandbox'); ctx.showToast('已克隆当前运行参数到场景构建器') }
  const openCompareShortcut = () => {
    if (!ctx.lifecycleControl.value.compareReady && !ctx.runControl.value.compare_ready) return ctx.showToast('需要至少两次 War Room 运行才能对比')
    ctx.loadRunDiff(); ctx.navigateSection('replay')
    nextTick(() => ctx.comparePanelEl.value?.scrollIntoView({ behavior: 'smooth', block: 'start' }))
    ctx.showToast('已打开反事实对比')
  }
  const openReplayShortcut = async () => {
    if (!ctx.lifecycleControl.value.replayReady && !ctx.runControl.value.replay_ready) return ctx.showToast('请先运行一次 War Room 沙盘')
    ctx.navigateSection('replay'); await ctx.exportReplayPack(); ctx.showToast('复盘包已生成')
  }
  const toggleDeltaOverlay = () => { ctx.showDeltaOverlay.value = !ctx.showDeltaOverlay.value; ctx.showToast(ctx.showDeltaOverlay.value ? '已开启反事实变化图层' : '已关闭反事实变化图层') }
  const toggleEventFilter = key => {
    ctx.eventFilters.value = ctx.eventFilters.value.includes(key) ? ctx.eventFilters.value.filter(item => item !== key) : [...ctx.eventFilters.value, key]
    ctx.showToast(ctx.eventFilters.value.length ? `已应用 ${ctx.eventFilters.value.length} 个事件筛选` : '事件筛选已清除')
  }
  const eventMatchesFilters = event => {
    if (!ctx.eventFilters.value.length) return true
    if (ctx.eventFilters.value.includes('selected_entity') && ctx.selectedMapEntity.value) {
      const detail = ctx.entityDetailDrawer.value || detailForSelectedEntity()
      const relatedCountries = new Set(ctx.selectedMapEntity.value.payload?.relatedCountries || ctx.selectedMapEntity.value.payload?.related_countries || detail?.related_countries || [])
      const relatedChains = new Set(ctx.selectedMapEntity.value.payload?.relatedChains || ctx.selectedMapEntity.value.payload?.related_chains || detail?.related_chains || [])
      const countryMatch = (event.relatedCountries || []).some(code => relatedCountries.has(code) || relatedCountries.has(ctx.countryNameShort(code)))
      const chainMatch = (event.relatedChains || []).some(key => relatedChains.has(key) || relatedChains.has(ctx.chainName(key)))
      if (!countryMatch && !chainMatch) return false
    }
    const derived = ({ blue: 'military', green: 'diplomatic', orange: 'economic', purple: 'social', red: 'turning', neutral: 'military' })[event.tone] || 'military'
    const typeFilters = ctx.eventFilters.value.filter(item => item !== 'selected_entity')
    return !typeFilters.length || typeFilters.includes(derived) || (event.turning && typeFilters.includes('turning'))
  }
  const eventVisible = event => {
    if (!ctx.eventFilters.value.length) return true
    const linked = ctx.timelineEvents.value.filter(item => item.eventKeys?.includes(event.key))
    return linked.length ? linked.some(eventMatchesFilters) : ctx.eventFilters.value.includes(event.tone === 'red' ? 'turning' : 'military')
  }
  const setAnalysisCountry = code => { ctx.focusedEntityId.value = `country:${code}`; selectMapCountry(ctx.mapCountries.value.find(item => item.code === code) || { code, risk: 0 }); ctx.showToast(`已定位 Agent：${ctx.countryNameShort(code)}`) }
  const entityActive = (type, id) => ctx.selectedMapEntity.value?.type === type && ctx.selectedMapEntity.value?.id === id
  const entityTypeLabel = type => ({ country: '国家节点', supply_chain: '供应链', causal_edge: '因果边', event: '事件热点', unit: '军事单元', timeline: '时间线' })[type] || '地图实体'
  const isCountryHot = code => ctx.activeCountryCodes.value.includes(code)
  const relatedEventLabels = code => {
    const labels = ctx.timelineEvents.value.filter(event => event.relatedCountries?.includes(code)).slice(0, 3).map(event => `${event.time} ${event.title}`)
    return labels.length ? labels : [`D+${ctx.activeReplayDay.value} ${ctx.activeTimelineEvent.value?.title || '态势更新'}`]
  }
  const riskColor = value => Number(value || 0) >= 72 ? '#ff4d5f' : Number(value || 0) >= 52 ? '#f59e32' : Number(value || 0) >= 35 ? '#36a7ff' : '#21d69b'
  const riskOpacity = value => Math.min(0.86, Math.max(0.18, Number(value || 0) / 100))
  const goDeepAnalysis = () => { ctx.navigateSection('analysis'); ctx.showToast(`已进入深度分析：${ctx.activeAgent.value.name}`) }
  const openEntityAnalysis = code => { ctx.focusedEntityId.value = `country:${code}`; selectMapCountry(ctx.mapCountries.value.find(item => item.code === code) || { code }); ctx.navigateSection('analysis'); ctx.showToast(`已进入智能分析：${ctx.countryNameShort(code)}`) }
  const openDecisionDrawer = chip => {
    const decision = ctx.warRoom.value?.agent_decisions?.find(item => item.country_code === ctx.activeAgent.value.code || item.country_name === ctx.activeAgent.value.enName) || {}
    ctx.decisionDrawer.value = {
      title: chip, country: ctx.activeAgent.value.name,
      confidence: decision.confidence !== undefined ? `${Math.round(Number(decision.confidence))}/100` : '规则解释',
      drivers: decision.drivers?.map(ctx.riskChannel).join('、') || ctx.activeAgent.value.decisions.join('、'),
      rationale: ctx.localizeText(decision.rationale) || ctx.activeAgent.value.decisionBasis,
      tradeoff: ctx.localizeText(decision.expected_tradeoff) || ctx.activeAgent.value.expectedTradeoff,
    }
    ctx.showToast('已打开 Agent 决策详情')
  }
  return {
    fullEntityId, detailForSelectedEntity, openEntityDetail, mapTooltipFor,
    activateCommandResult, handleEntityAction, cloneFromCurrentRun,
    openCompareShortcut, openReplayShortcut, toggleDeltaOverlay, toggleEventFilter,
    eventMatchesFilters, eventVisible, setAnalysisCountry, entityActive,
    entityTypeLabel, isCountryHot, relatedEventLabels, riskColor, riskOpacity,
    goDeepAnalysis, openEntityAnalysis, openDecisionDrawer, selectMapCountry,
    selectSupplyChain, selectCausalEdge, selectMilitaryUnit, selectMapEvent,
    selectTimelineEvent,
  }
}
