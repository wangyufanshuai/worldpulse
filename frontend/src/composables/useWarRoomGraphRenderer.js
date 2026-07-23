import * as d3 from 'd3'

export function useWarRoomGraphRenderer({
  detail, graphEl, sectionGraphEl, selected, focusedEdgeKey, filteredGraphEdges,
  focusedGraphEdgeId, edgeKey, edgeLabel, graphEntityType, focusGraphEdge,
}) {
  let overviewSimulation = null
  let sectionSimulation = null

  function stopOverviewGraph() {
    overviewSimulation?.stop()
    overviewSimulation = null
  }

  function stopSectionGraph() {
    sectionSimulation?.stop()
    sectionSimulation = null
  }

  function renderGraph() {
    const graph = detail.value?.graph
    const el = graphEl.value
    stopOverviewGraph()
    if (!graph || !el) return
    el.innerHTML = ''
    const width = el.clientWidth || 760
    const height = 520
    const svg = d3.select(el).append('svg').attr('viewBox', `0 0 ${width} ${height}`)
    const nodes = graph.nodes.map(node => ({ ...node }))
    const edges = graph.edges.map(edge => ({ ...edge }))
    const simulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(edges).id(d => d.id).distance(130).strength(0.55))
      .force('charge', d3.forceManyBody().strength(-560))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collide', d3.forceCollide(56))
    overviewSimulation = simulation
    const link = svg.append('g').selectAll('line').data(edges).enter().append('line')
      .attr('class', d => edgeKey(d) === focusedEdgeKey.value ? 'edge-line edge-focused' : 'edge-line')
      .attr('stroke-width', d => 1 + Number(d.weight || 0.5) * 2)
      .on('click', (_, d) => { selected.value = { ...d, source: d.source.id || d.source, target: d.target.id || d.target } })
    const node = svg.append('g').selectAll('g').data(nodes).enter().append('g')
      .attr('class', d => `node node-${d.kind}`)
      .call(d3.drag()
        .on('start', (event, d) => { if (!event.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y })
        .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y })
        .on('end', (event, d) => { if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null }))
      .on('click', (_, d) => { selected.value = d })
    node.append('circle').attr('r', d => 18 + Number(d.score || 50) / 8)
    node.append('text').text(d => d.label).attr('dy', 44).attr('text-anchor', 'middle')
    simulation.on('tick', () => {
      link.attr('x1', d => d.source.x).attr('y1', d => d.source.y).attr('x2', d => d.target.x).attr('y2', d => d.target.y)
      node.attr('transform', d => `translate(${d.x},${d.y})`)
    })
  }

  function renderSectionGraph() {
    const el = sectionGraphEl.value
    stopSectionGraph()
    if (!el) return
    el.innerHTML = ''
    const edgeItems = filteredGraphEdges.value
    if (!edgeItems.length) {
      const empty = document.createElement('div')
      empty.className = 'graph-empty-state'
      empty.textContent = '当前筛选条件下没有因果链路'
      el.appendChild(empty)
      return
    }
    const width = el.clientWidth || 720
    const height = Math.max(420, Math.min(560, Math.round(width * 0.66)))
    const graphNodes = new Map()
    const links = edgeItems.map(item => {
      const sourceId = item.edge.source?.id || item.edge.source
      const targetId = item.edge.target?.id || item.edge.target
      if (!graphNodes.has(sourceId)) graphNodes.set(sourceId, { id: sourceId, label: edgeLabel(sourceId), kind: graphEntityType(sourceId) })
      if (!graphNodes.has(targetId)) graphNodes.set(targetId, { id: targetId, label: edgeLabel(targetId), kind: graphEntityType(targetId) })
      return { ...item.edge, source: sourceId, target: targetId, itemId: item.id }
    })
    const nodes = [...graphNodes.values()]
    const svg = d3.select(el).append('svg').attr('viewBox', `0 0 ${width} ${height}`).attr('role', 'img').attr('aria-label', 'War Room 因果链路图')
    const simulation = d3.forceSimulation(nodes)
      .force('link', d3.forceLink(links).id(node => node.id).distance(120).strength(0.62))
      .force('charge', d3.forceManyBody().strength(-430))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collide', d3.forceCollide(48))
    sectionSimulation = simulation
    const link = svg.append('g').attr('class', 'section-graph-links').selectAll('line').data(links).enter().append('line')
      .attr('class', item => item.itemId === focusedGraphEdgeId.value ? 'edge-line edge-focused' : 'edge-line')
      .attr('stroke-width', item => 1.4 + Number(item.weight || 0.5) * 2.6)
      .attr('data-entity-type', 'causal_edge').attr('data-entity-id', item => item.itemId)
      .on('click', (_, item) => {
        const edgeItem = edgeItems.find(candidate => candidate.id === item.itemId)
        if (edgeItem) focusGraphEdge(edgeItem)
      })
    const node = svg.append('g').attr('class', 'section-graph-nodes').selectAll('g').data(nodes).enter().append('g')
      .attr('class', item => `node node-${item.kind}`)
      .attr('data-entity-type', item => item.kind).attr('data-entity-id', item => item.id)
      .call(d3.drag()
        .on('start', (event, item) => { if (!event.active) simulation.alphaTarget(0.3).restart(); item.fx = item.x; item.fy = item.y })
        .on('drag', (event, item) => { item.fx = event.x; item.fy = event.y })
        .on('end', (event, item) => { if (!event.active) simulation.alphaTarget(0); item.fx = null; item.fy = null }))
    node.append('circle').attr('r', 21)
    node.append('text').text(item => item.label).attr('dy', 38).attr('text-anchor', 'middle')
    simulation.on('tick', () => {
      link.attr('x1', item => item.source.x).attr('y1', item => item.source.y).attr('x2', item => item.target.x).attr('y2', item => item.target.y)
      node.attr('transform', item => `translate(${item.x},${item.y})`)
    })
  }

  function stopGraphs() {
    stopOverviewGraph()
    stopSectionGraph()
  }

  return { renderGraph, renderSectionGraph, stopGraphs }
}
