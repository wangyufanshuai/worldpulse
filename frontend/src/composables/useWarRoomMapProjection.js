import { computed, ref } from 'vue'

const COUNTRY_COORDINATES = {
  USA: { x: 728, y: 216 }, BRA: { x: 830, y: 430 }, EU: { x: 214, y: 232 },
  RUS: { x: 322, y: 140 }, SAU: { x: 322, y: 330 }, IND: { x: 438, y: 322 },
  CHN: { x: 497, y: 276 }, JPN: { x: 603, y: 255 }, KOR: { x: 576, y: 250 }, TWN: { x: 565, y: 304 },
}
const CHAIN_ANCHORS = { energy: ['SAU', 'JPN'], food: ['BRA', 'IND'], chips: ['TWN', 'USA'], shipping: ['CHN', 'EU'], settlement: ['USA', 'EU'] }
const FALLBACK_LAYERS = [
  { key: 'military', label: '军事部署' }, { key: 'economic', label: '经济联系' },
  { key: 'diplomatic', label: '外交关系' }, { key: 'events', label: '事件热点' },
  { key: 'risk', label: '风险区域' },
]
const FALLBACK_UNITS = [
  { key: 'carrier-1', label: '航母', x: 584, y: 320 }, { key: 'ship-1', label: '舰队', x: 740, y: 386 },
  { key: 'air-1', label: '空巡', x: 630, y: 382 }, { key: 'ship-2', label: '护航', x: 456, y: 392 },
]

export function useWarRoomMapProjection({ warRoomUi, warRoom, detail, fallbackChains, countryNameShort, localizeText, normalizeRiskValue, averageRisk, countryDelta, edgeKey, showToast }) {
  const visibleMapLayers = ref(['military', 'economic', 'diplomatic', 'events', 'risk', 'causal'])
  const mapZoom = ref(1)
  const layerMenuOpen = ref(true)
  const eventFilterOpen = ref(false)
  const eventFilters = ref([])
  const hoveredMapEntity = ref(null)
  const selectedMapEntity = ref(null)
  const uiMapEntities = computed(() => Array.isArray(warRoomUi.value?.map_entities) ? warRoomUi.value.map_entities : [])

  function coordinateForCode(code, index = 0) {
    const normalized = String(code || '').toUpperCase()
    if (COUNTRY_COORDINATES[normalized]) return COUNTRY_COORDINATES[normalized]
    const angle = (index / 10) * Math.PI * 2
    return { x: 500 + Math.cos(angle) * 260, y: 280 + Math.sin(angle) * 150 }
  }
  function coordinateForEntity(entity, index = 0) {
    const raw = typeof entity === 'object' ? entity.id || entity.code || entity.key || entity.label : entity
    const value = String(raw || '').toUpperCase()
    const countryCode = Object.keys(COUNTRY_COORDINATES).find(code => value.includes(code))
    return countryCode ? COUNTRY_COORDINATES[countryCode] : coordinateForCode('', index)
  }
  function chainRouteEndpoints(chain) {
    const affected = (chain.affected_countries || chain.affected_country_codes || []).filter(Boolean)
    const defaults = CHAIN_ANCHORS[chain.key] || ['USA', 'CHN']
    return [affected[0] || defaults[0], affected[affected.length - 1] || defaults[1] || defaults[0]]
  }
  function arcPath(start, end, direction = 1, lift = 0.28) {
    const dx = end.x - start.x
    const dy = end.y - start.y
    const mx = (start.x + end.x) / 2
    const my = (start.y + end.y) / 2
    return `M ${start.x} ${start.y} Q ${mx - dy * lift * direction} ${my + dx * lift * direction} ${end.x} ${end.y}`
  }

  const mapLayerButtons = computed(() => {
    const layers = Array.isArray(warRoomUi.value?.map_layers) ? warRoomUi.value.map_layers : []
    return layers.length ? layers.map(layer => ({ key: layer.key, label: layer.label_zh || layer.label || layer.key, enabled: layer.enabled !== false })) : FALLBACK_LAYERS
  })
  const militaryUnits = computed(() => {
    const units = uiMapEntities.value.filter(entity => entity.type === 'unit')
    return units.length ? units.map(entity => ({ key: entity.key || entity.id?.replace('unit:', ''), label: entity.label_zh || entity.label, x: entity.x, y: entity.y, ...entity })) : FALLBACK_UNITS
  })
  const mapCountries = computed(() => {
    const uiCountries = uiMapEntities.value.filter(entity => entity.type === 'country')
    if (uiCountries.length) {
      return uiCountries.map((entity, index) => {
        const code = entity.key || entity.id?.replace('country:', '') || entity.country_code
        const point = coordinateForCode(code, index)
        return { ...entity, code, country_code: code, country_name: entity.label_zh || countryNameShort(code), x: Number(entity.x ?? point.x), y: Number(entity.y ?? point.y), risk: Number(entity.risk || 0), dominant_channel: entity.dominant_channel, radius: 7 + Math.min(20, Number(entity.risk || 0) / 5), delta: countryDelta(code) }
      })
    }
    const riskRows = warRoom.value?.risk_heatmap?.length ? warRoom.value.risk_heatmap : [
      { country_code: 'CHN', country_name: '中国', risk: 82, dominant_channel: 'military' },
      { country_code: 'TWN', country_name: '台湾', risk: 88, dominant_channel: 'military' },
      { country_code: 'USA', country_name: '美国', risk: 64, dominant_channel: 'financial' },
      { country_code: 'JPN', country_name: '日本', risk: 62, dominant_channel: 'energy' },
      { country_code: 'EU', country_name: '欧盟', risk: 41, dominant_channel: 'trade' },
      { country_code: 'RUS', country_name: '俄罗斯', risk: 45, dominant_channel: 'energy' },
      { country_code: 'IND', country_name: '印度', risk: 38, dominant_channel: 'trade' },
      { country_code: 'SAU', country_name: '中东', risk: 36, dominant_channel: 'energy' },
      { country_code: 'BRA', country_name: '巴西', risk: 28, dominant_channel: 'food' },
    ]
    return riskRows.map((cell, index) => {
      const code = cell.country_code || cell.code
      const point = coordinateForCode(code, index)
      return { ...cell, code, x: point.x, y: point.y, risk: Number(cell.risk || 0), radius: 7 + Math.min(20, Number(cell.risk || 0) / 5), delta: countryDelta(code) }
    })
  })
  const supplyRoutes = computed(() => {
    const chains = warRoom.value?.supply_chains?.length ? warRoom.value.supply_chains : fallbackChains
    return chains.map((chain, index) => {
      const [startCode, endCode] = chainRouteEndpoints(chain)
      const start = coordinateForCode(startCode, index)
      const end = coordinateForCode(endCode, index + 2)
      return { key: chain.key, chain, start, end, mid: { x: (start.x + end.x) / 2, y: (start.y + end.y) / 2 }, path: arcPath(start, end, index % 2 === 0 ? -1 : 1) }
    })
  })
  const mapCausalEdges = computed(() => {
    const uiEdges = uiMapEntities.value.filter(entity => entity.type === 'causal_edge')
    if (uiEdges.length) {
      return uiEdges.slice(0, 24).map((entity, index) => ({
        id: entity.id || `edge:${entity.source}->${entity.target}`, entity,
        edge: { source: entity.source, target: entity.target, relation: entity.label_zh, mechanism: entity.mechanism_zh, weight: entity.weight, lag_days: entity.lag_days, related_countries: entity.related_countries, related_chains: entity.related_chains },
        path: arcPath(coordinateForEntity(entity.source, index), coordinateForEntity(entity.target, index + 4), index % 2 === 0 ? 1 : -1, 0.18),
      }))
    }
    const edges = warRoom.value?.impact_graph?.edges || detail.value?.graph?.edges || []
    const fallback = edges.length ? edges : [
      { source: 'CHN', target: 'TWN', relation: '军事压力', mechanism: '区域军事活动推升风险' },
      { source: 'USA', target: 'TWN', relation: '战略支援', mechanism: '外部支援改变威慑结构' },
      { source: 'TWN', target: 'JPN', relation: '供应链外溢', mechanism: '芯片与航运压力传导' },
    ]
    return fallback.slice(0, 12).map((edge, index) => ({ id: `${edgeKey(edge)}-${index}`, edge, path: arcPath(coordinateForEntity(edge.source, index), coordinateForEntity(edge.target, index + 4), index % 2 === 0 ? 1 : -1, 0.18) }))
  })
  const mapEvents = computed(() => {
    const uiEvents = uiMapEntities.value.filter(entity => entity.type === 'event')
    if (uiEvents.length) return uiEvents.map(entity => ({ ...entity, key: entity.key || entity.id?.replace('event:', ''), label: entity.label_zh || entity.label, title: entity.title_zh || entity.title || entity.label_zh, detail: entity.detail_zh || entity.detail, relatedCountries: entity.related_countries || [], relatedChains: entity.related_chains || [] }))
    return [
      { key: 'taiwan', label: '台湾', title: '经济封锁加码', x: 586, y: 332, tone: 'red', day: 21, country_code: 'TWN', relatedCountries: ['TWN', 'CHN', 'JPN'] },
      { key: 'china', label: '中国', title: '军事演习升级', x: 531, y: 249, tone: 'blue', day: 3, country_code: 'CHN', relatedCountries: ['CHN', 'TWN', 'USA'] },
      { key: 'japan', label: '日本', title: '加强西南部署', x: 632, y: 230, tone: 'orange', day: 14, country_code: 'JPN', relatedCountries: ['JPN', 'TWN', 'USA'] },
      { key: 'us', label: '美国', title: '宣布对台警戒', x: 760, y: 236, tone: 'blue', day: 7, country_code: 'USA', relatedCountries: ['USA', 'TWN', 'CHN'] },
    ]
  })
  const timelineEvents = computed(() => {
    const uiEvents = Array.isArray(warRoomUi.value?.timeline_events) ? warRoomUi.value.timeline_events : []
    if (uiEvents.length) return uiEvents.map((event, index) => ({ key: event.key || `day-${event.day ?? index}`, day: Number(event.day || index), time: event.time || `D+${event.day ?? index}`, title: event.title_zh || event.title || '态势更新', detail: event.detail_zh || event.detail || '', tone: event.tone || (event.turning_point ? 'red' : 'blue'), position: Number(event.position ?? Math.min(95, index / Math.max(1, uiEvents.length - 1) * 100)), globalRisk: normalizeRiskValue(event.global_risk ?? averageRisk()), riskDelta: Number(event.global_risk_delta || 0), turning: !!event.turning_point, eventKeys: event.event_keys || event.eventKeys || [], relatedCountries: event.related_countries || event.relatedCountries || [], relatedChains: event.related_chains || event.relatedChains || [] }))
    const timeline = warRoom.value?.timeline || []
    if (!timeline.length) return [
      { key: 'e1', day: 0, time: 'D+0', title: '美国宣布对台警戒', detail: '扩大对台军事支援范围', tone: 'red', position: 6, globalRisk: 68, riskDelta: 0, turning: false, eventKeys: ['us'], relatedCountries: ['USA', 'TWN'] },
      { key: 'e2', day: 3, time: 'D+3', title: '中国军演升级', detail: '多军兵种联合演习', tone: 'blue', position: 24, globalRisk: 72, riskDelta: 4, turning: true, eventKeys: ['china'], relatedCountries: ['CHN', 'TWN'] },
      { key: 'e3', day: 7, time: 'D+7', title: '外交紧急磋商', detail: '联合国安理会紧急会议', tone: 'green', position: 42, globalRisk: 70, riskDelta: -2, turning: false, eventKeys: ['us', 'japan'], relatedCountries: ['USA', 'EU', 'JPN'] },
      { key: 'e4', day: 14, time: 'D+14', title: '日本加强西南部署', detail: '自卫队警戒级别提升', tone: 'orange', position: 64, globalRisk: 76, riskDelta: 6, turning: true, eventKeys: ['japan'], relatedCountries: ['JPN', 'TWN', 'USA'] },
      { key: 'e5', day: 21, time: 'D+21', title: '经济封锁加码', detail: '多国扩大对华出口限制', tone: 'red', position: 82, globalRisk: 81, riskDelta: 5, turning: true, eventKeys: ['taiwan'], relatedCountries: ['TWN', 'CHN', 'USA'] },
      { key: 'e6', day: 30, time: 'D+30', title: '二阶压力扩散', detail: '金融结算与供应链替代压力进入复盘窗口', tone: 'red', position: 95, globalRisk: 78, riskDelta: -3, turning: true, eventKeys: ['taiwan', 'china'], relatedCountries: ['CHN', 'TWN', 'JPN'] },
    ]
    const keys = ['us', 'china', 'us', 'japan', 'taiwan', 'taiwan']
    const countries = [['USA', 'TWN'], ['CHN', 'TWN'], ['USA', 'EU', 'JPN'], ['JPN', 'TWN', 'USA'], ['TWN', 'CHN', 'USA'], ['CHN', 'TWN', 'JPN']]
    return timeline.slice(0, 6).map((point, index) => ({ key: `day-${point.day}`, day: Number(point.day || index), time: `D+${point.day}`, title: point.turning_point ? '关键拐点' : '态势更新', detail: localizeText(point.key_development), tone: point.turning_point ? 'red' : index % 2 ? 'green' : 'blue', position: Math.min(95, (index / Math.max(1, Math.min(6, timeline.length) - 1)) * 100), globalRisk: normalizeRiskValue(point.global_risk ?? averageRisk()), riskDelta: index ? normalizeRiskValue(point.global_risk || 0) - normalizeRiskValue(timeline[index - 1]?.global_risk || 0) : 0, turning: !!point.turning_point, eventKeys: [keys[index % keys.length]], relatedCountries: countries[index % countries.length] }))
  })

  function zoomMap(delta) { mapZoom.value = Math.min(1.35, Math.max(0.78, Number((mapZoom.value + delta).toFixed(2)))) }
  function resetMapView() {
    mapZoom.value = 1
    visibleMapLayers.value = ['military', 'economic', 'diplomatic', 'events', 'risk', 'causal']
    eventFilters.value = []
    selectedMapEntity.value = null
  }
  function layerLabel(key) { return mapLayerButtons.value.find(item => item.key === key)?.label || key }
  function layerActive(key) { return visibleMapLayers.value.includes(key) }
  function toggleMapLayer(key) {
    visibleMapLayers.value = layerActive(key) ? visibleMapLayers.value.filter(item => item !== key) : [...visibleMapLayers.value, key]
    showToast?.(`${layerLabel(key)}${layerActive(key) ? '已显示' : '已隐藏'}`)
  }

  return { visibleMapLayers, mapZoom, layerMenuOpen, eventFilterOpen, eventFilters, hoveredMapEntity, selectedMapEntity, uiMapEntities, mapLayerButtons, militaryUnits, mapCountries, supplyRoutes, mapCausalEdges, mapEvents, timelineEvents, coordinateForCode, coordinateForEntity, chainRouteEndpoints, arcPath, zoomMap, resetMapView, layerLabel, layerActive, toggleMapLayer }
}
