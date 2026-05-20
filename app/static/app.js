const plotLayout = {
  paper_bgcolor: "rgba(0,0,0,0)",
  plot_bgcolor: "rgba(0,0,0,0)",
  font: { color: "#243044" },
  margin: { l: 42, r: 24, t: 24, b: 42 },
};

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function $(selector) {
  return document.querySelector(selector);
}

function setText(selector, value) {
  const element = $(selector);
  if (element) element.textContent = value;
}

function fmt(value, digits = 1) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : "--";
}

function signed(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return `${number >= 0 ? "+" : ""}${fmt(number, 1)}`;
}

function riskColor(score) {
  if (score >= 75) return "#b94235";
  if (score >= 60) return "#ce8b24";
  if (score >= 40) return "#315f86";
  return "#1f8a62";
}

function levelFromScore(score) {
  if (score >= 75) return "极高风险";
  if (score >= 60) return "高风险";
  if (score >= 40) return "中等风险";
  return "低风险";
}

function htmlEscape(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

function card(title, body, meta = "") {
  return `<article class="analysis-card"><strong>${htmlEscape(title)}</strong>${meta ? `<em>${htmlEscape(meta)}</em>` : ""}<p>${htmlEscape(body)}</p></article>`;
}

function postJson(url, payload) {
  return fetchJson(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
}

function setBusy(element, text = "加载中...") {
  if (element) element.innerHTML = card(text, "正在读取接口数据。");
}

async function boot() {
  $("#refresh")?.addEventListener("click", renderDashboard);
  $("#exportReport")?.addEventListener("click", exportReport);
  $("#loadSpecies")?.addEventListener("click", loadSelectedSpecies);
  $("#loadReplay")?.addEventListener("click", loadReplay);
  $("#runSimulation")?.addEventListener("click", runSimulationFromControls);
  $("#simulationScenario")?.addEventListener("change", applySelectedScenario);
  $("#analyzeRisk")?.addEventListener("click", () => runAiAnalysis("risk"));
  $("#analyzeSimulation")?.addEventListener("click", () => runAiAnalysis("simulation"));
  $("#aiAgentSelect")?.addEventListener("change", loadEventDigest);
  $("#aiWindow")?.addEventListener("change", loadEventDigest);
  ["shockIntensity", "shockDuration", "shockPropagation"].forEach((id) => $(`#${id}`)?.addEventListener("input", updateSimulationLabels));
  document.querySelectorAll(".module-tab").forEach((button) => button.addEventListener("click", () => showModule(button.dataset.module)));

  try {
    const health = await fetchJson("/api/health");
    setText("#health", health.status === "ok" ? "服务在线" : "服务降级");
  } catch {
    setText("#health", "服务不可用");
  }

  await Promise.allSettled([loadSpeciesPresets(), loadSimulationSetup(), loadWorkbench(), loadReports(), loadAiModule()]);
  await renderDashboard();
  const initialModule = window.location.hash.replace("#", "");
  if (initialModule) showModule(initialModule);
}

function showModule(name) {
  document.querySelectorAll(".module-view").forEach((view) => view.classList.add("hidden"));
  $(`#${name}Module`)?.classList.remove("hidden");
  document.querySelectorAll(".module-tab").forEach((button) => button.classList.toggle("active", button.dataset.module === name));
  window.location.hash = name;
  if (name === "analysis") loadAnalysis();
  if (name === "replay") loadReplay();
  if (name === "ai") loadAiModule();
}

async function renderDashboard() {
  const overview = await fetchJson("/api/risk/overview");
  window.worldPulseOverview = overview;
  renderLatest(overview.latest);
  renderComponents(overview.latest.components);
  renderDrivers(overview.latest.components);
  renderRiskChart(overview.history, "chart");
  renderScenarioControls(overview.latest.components);
}

function renderLatest(risk) {
  setText("#score", fmt(risk.score, 0));
  setText("#level", risk.display_level || levelFromScore(risk.score));
  setText("#headline", `${risk.display_level || levelFromScore(risk.score)}：${risk.display_trend || risk.trend || "状态已更新"}`);
  setText("#summary", risk.summary || "");
  setText("#forecast", risk.display_forecast_label || risk.forecast_label || "--");
  setText("#trend", risk.display_trend || risk.trend || "--");
  setText("#date", risk.date || "--");
}

function renderComponents(components) {
  const target = $("#components");
  if (!target) return;
  target.innerHTML = components.map((item) => `<article><span>${htmlEscape(item.name)}</span><strong style="color:${riskColor(item.score)}">${fmt(item.score, 1)}</strong><meter min="0" max="100" value="${item.score}"></meter></article>`).join("");
}

function renderDrivers(components) {
  const target = $("#drivers");
  if (!target) return;
  target.innerHTML = components
    .flatMap((component) => (component.drivers || []).map((driver) => ({ component: component.name, driver })))
    .slice(0, 8)
    .map((item) => card(item.driver, "该信号来自当前风险分项的主要驱动列表。", item.component))
    .join("");
}

function renderRiskChart(history, elementId) {
  if (!window.Plotly || !document.getElementById(elementId)) return;
  Plotly.newPlot(
    elementId,
    [{ x: history.map((p) => p.date), y: history.map((p) => p.score), type: "scatter", mode: "lines", line: { color: "#1d4ed8", width: 3 }, fill: "tozeroy", fillcolor: "rgba(29,78,216,0.08)" }],
    { ...plotLayout, yaxis: { range: [0, 100] } },
    { displayModeBar: false, responsive: true }
  );
}

function renderScenarioControls(components) {
  const target = $("#scenarioControls");
  if (!target || target.dataset.ready === "1") return;
  target.dataset.ready = "1";
  target.innerHTML = components.map((item) => `<label>${htmlEscape(item.name)} <b id="sc-${item.key}">${fmt(item.score, 0)}</b><input type="range" min="0" max="100" value="${item.score}" data-key="${item.key}" data-name="${htmlEscape(item.name)}" /></label>`).join("");
  target.querySelectorAll("input").forEach((input) => input.addEventListener("input", updateQuickScenario));
  updateQuickScenario();
}

function updateQuickScenario() {
  const inputs = [...document.querySelectorAll("#scenarioControls input")];
  if (!inputs.length) return;
  const values = inputs.map((input) => Number(input.value));
  inputs.forEach((input) => setText(`#sc-${input.dataset.key}`, fmt(input.value, 0)));
  const score = values.reduce((sum, value) => sum + value, 0) / values.length;
  setText("#scenarioScore", fmt(score, 0));
  setText("#scenarioLevel", levelFromScore(score));
  const top = inputs.sort((a, b) => Number(b.value) - Number(a.value))[0];
  setText("#scenarioOutput", `当前快速敏感性总分约 ${fmt(score, 1)}，主要压力来自 ${top?.dataset.name || "未知分项"}。`);
}

async function loadSimulationSetup() {
  const [agents, scenarios, health] = await Promise.all([fetchJson("/api/simulation/agents"), fetchJson("/api/simulation/scenarios"), fetchJson("/api/simulation/data-health")]);
  window.worldPulseAgents = agents;
  window.worldPulseScenarios = scenarios;
  const targetSelect = $("#shockTargets");
  if (targetSelect) targetSelect.innerHTML = agents.map((agent) => `<option value="${agent.code}">${htmlEscape(agent.name)} (${agent.code})</option>`).join("");
  const aiSelect = $("#aiAgentSelect");
  if (aiSelect) aiSelect.innerHTML = `<option value="">全球</option>${agents.map((agent) => `<option value="${agent.code}">${htmlEscape(agent.name)} (${agent.code})</option>`).join("")}`;
  const scenarioSelect = $("#simulationScenario");
  if (scenarioSelect) scenarioSelect.innerHTML = scenarios.map((scenario, index) => `<option value="${index}">${htmlEscape(scenario.name)}</option>`).join("");
  renderSimulationHealth(health);
  applySelectedScenario();
  await runSimulationFromControls();
}

function applySelectedScenario() {
  const scenario = window.worldPulseScenarios?.[Number($("#simulationScenario")?.value || 0)];
  if (!scenario?.shocks?.length) return;
  const shock = scenario.shocks[0];
  $("#shockType").value = shock.shock_type;
  $("#shockIntensity").value = shock.intensity;
  $("#shockDuration").value = shock.duration_months;
  $("#shockPropagation").value = shock.propagation;
  [...$("#shockTargets").options].forEach((option) => (option.selected = shock.target_codes.includes(option.value)));
  updateSimulationLabels();
}

function updateSimulationLabels() {
  setText("#shockIntensityLabel", fmt($("#shockIntensity")?.value, 2));
  setText("#shockDurationLabel", $("#shockDuration")?.value || "--");
  setText("#shockPropagationLabel", fmt($("#shockPropagation")?.value, 2));
}

async function runSimulationFromControls() {
  const selected = [...($("#shockTargets")?.selectedOptions || [])].map((option) => option.value);
  const shock = {
    shock_type: $("#shockType")?.value || "energy",
    target_codes: selected.length ? selected : ["EU", "JPN", "KOR", "IND"],
    intensity: Number($("#shockIntensity")?.value || 0.5),
    duration_months: Number($("#shockDuration")?.value || 6),
    propagation: Number($("#shockPropagation")?.value || 0.35),
  };
  setText("#simulationSummary", "正在运行蒙特卡洛模拟...");
  const result = await postJson("/api/simulation/run", { shocks: [shock], horizon_months: 12, runs: Number($("#simulationRuns")?.value || 500), seed: 42 });
  window.worldPulseLastSimulation = result;
  renderSimulation(result);
}

function renderSimulation(result) {
  setText("#simulationSummary", result.summary);
  const last = result.global_path.at(-1);
  setText("#simulationScore", fmt(last?.p50, 1));
  setText("#simulationBand", `P10 ${fmt(last?.p10, 1)} / P90 ${fmt(last?.p90, 1)}`);
  renderSimulationPath(result.global_path);
  renderSimulationMap(result.map_points);
  $("#simulationDrivers").innerHTML = result.drivers.map((driver) => card(driver.name, driver.explanation, `贡献 ${fmt(driver.contribution, 1)}`)).join("");
  $("#countryImpactList").innerHTML = result.countries.slice(0, 10).map((country) => card(`${country.name} (${country.code})`, `P50 ${fmt(country.p50, 1)}，不确定性 ${fmt(country.uncertainty, 1)}，上行概率 ${fmt(country.upside_probability * 100, 0)}%。`, `起点 ${fmt(country.start_risk, 1)}`)).join("");
  $("#propagationList").innerHTML = result.propagation_edges.slice(0, 10).map((edge) => card(`${edge.source} -> ${edge.target}`, `${edge.channel} 传播权重 ${fmt(edge.weight, 2)}，影响 ${fmt(edge.impact, 2)}。`)).join("");
  if (result.countries[0]) loadAgentDetail(result.countries[0].code);
}

function renderSimulationPath(points) {
  if (!window.Plotly || !$("#simulationPathChart")) return;
  const x = points.map((p) => `M${p.month}`);
  Plotly.newPlot(
    "simulationPathChart",
    [
      { x, y: points.map((p) => p.p90), type: "scatter", mode: "lines", line: { width: 0 }, showlegend: false },
      { x, y: points.map((p) => p.p10), type: "scatter", mode: "lines", fill: "tonexty", fillcolor: "rgba(42,93,170,0.16)", line: { width: 0 }, name: "P10-P90" },
      { x, y: points.map((p) => p.p50), type: "scatter", mode: "lines", line: { color: "#1d4ed8", width: 3 }, name: "P50" },
    ],
    { ...plotLayout, yaxis: { range: [0, 100] } },
    { displayModeBar: false, responsive: true }
  );
}

function renderSimulationMap(points) {
  if (!window.Plotly || !$("#simulationMap")) return;
  Plotly.newPlot(
    "simulationMap",
    [{ type: "scattergeo", lon: points.map((p) => p.longitude), lat: points.map((p) => p.latitude), text: points.map((p) => `${p.name} ${fmt(p.risk, 1)}`), customdata: points.map((p) => p.code), mode: "markers", marker: { size: points.map((p) => 8 + p.uncertainty), color: points.map((p) => p.risk), colorscale: "RdYlBu", reversescale: true, cmin: 20, cmax: 90, line: { color: "#ffffff", width: 1 } } }],
    { ...plotLayout, geo: { projection: { type: "natural earth" }, showland: true, landcolor: "#eef3f8", coastlinecolor: "#b7c2d0" } },
    { displayModeBar: false, responsive: true }
  );
  $("#simulationMap").on("plotly_click", (event) => loadAgentDetail(event.points?.[0]?.customdata));
}

async function loadAgentDetail(code) {
  if (!code) return;
  const detail = await fetchJson(`/api/simulation/agent/${code}`);
  setText("#agentDetailTitle", `${detail.agent.name} (${detail.agent.code})`);
  const states = Object.entries(detail.agent.state).map(([key, value]) => card(key, detail.state_explanations[key] || "状态变量", fmt(value, 1))).join("");
  const raw = Object.entries(detail.raw_indicators || {}).slice(0, 12).map(([key, value]) => `<span><b>${htmlEscape(key)}</b>${htmlEscape(value)}</span>`).join("");
  $("#agentDetail").innerHTML = `${card("数据可信度", `质量分 ${fmt(detail.agent.data_quality_score, 0)}，兜底字段：${detail.fallback_fields.join("、") || "无"}`)}${states}<article class="analysis-card"><strong>原始指标</strong><p class="chip-row">${raw}</p></article>`;
}

function renderSimulationHealth(items) {
  const target = $("#simulationDataHealth");
  if (!target) return;
  target.innerHTML = items.map((item) => `<article><strong>${htmlEscape(item.source)}</strong><p>${htmlEscape(item.note)}</p><span>状态：${htmlEscape(item.status)}</span><span>真实字段：${item.real_field_count}</span><span>兜底字段：${item.fallback_field_count}</span></article>`).join("");
}

async function loadAiModule() {
  const statusTarget = $("#aiStatus");
  if (!statusTarget) return;
  const status = await fetchJson("/api/ai/status");
  statusTarget.innerHTML = card(
    status.enabled ? "AI 已启用" : "AI 未启用",
    status.enabled ? `主模型：${status.provider} / ${status.model}；备用：${status.fallback_provider} / ${status.fallback_model}` : "未配置 SILICONFLOW_API_KEY 或 DEEPSEEK_API_KEY，页面会使用本地兜底分析，不影响其他功能。",
    status.mode
  );
  const controls = $("#aiAgentSelect")?.closest(".replay-controls");
  if (controls && !$("#exportAiReport")) {
    const button = document.createElement("button");
    button.id = "exportAiReport";
    button.type = "button";
    button.textContent = "导出 AI Markdown 报告";
    button.addEventListener("click", exportAiReport);
    controls.appendChild(button);
  }
  await loadEventDigest();
}

async function loadEventDigest() {
  const target = $("#eventDigest");
  if (!target) return;
  setBusy(target, "事件摘要加载中");
  const code = $("#aiAgentSelect")?.value;
  const days = $("#aiWindow")?.value || 30;
  const url = code ? `/api/events/agent/${code}?window_days=${days}` : `/api/events/digest?window_days=${days}&region=global`;
  const digest = await fetchJson(url);
  target.innerHTML = [
    card(`${digest.scope} / 近${digest.window_days}天`, `总事件量代理值：${digest.total_events}。来源：${digest.source}`),
    ...digest.topics.slice(0, 7).map((topic) => card(topic.name, topic.summary, `强度 ${fmt(topic.intensity, 1)} / ${topic.source}`)),
    ...(digest.notes || []).map((note) => card("数据提示", note)),
  ].join("");
}

async function runAiAnalysis(kind) {
  const target = $("#aiResult");
  setBusy(target, "AI 分析中");
  const payload = {
    focus: kind === "simulation" ? "simulation" : "risk",
    agent_code: $("#aiAgentSelect")?.value || null,
    window_days: Number($("#aiWindow")?.value || 30),
    simulation: kind === "simulation" ? window.worldPulseLastSimulation || null : null,
  };
  const result = await postJson(kind === "simulation" ? "/api/ai/analyze-simulation" : "/api/ai/analyze-risk", payload);
  window.worldPulseLastAiPayload = payload;
  renderAiResult(result);
}

async function exportAiReport() {
  const payload = window.worldPulseLastAiPayload || {
    focus: "risk",
    agent_code: $("#aiAgentSelect")?.value || null,
    window_days: Number($("#aiWindow")?.value || 30),
    simulation: null,
  };
  const result = await postJson("/api/ai/report/export", payload);
  alert(`AI 报告已导出：${result.path}`);
}

function renderAiResult(result) {
  setText("#aiResultTitle", result.title);
  $("#aiResult").innerHTML = [
    card("摘要", result.summary, result.mode),
    ...result.key_findings.map((item, index) => card(`主要结论 ${index + 1}`, item)),
    ...result.evidence.map((item) => card(item.title, item.interpretation, `${item.source} / ${item.value}`)),
    ...result.uncertainties.map((item) => card("关键不确定性", item)),
    ...result.watch_signals.map((item) => card(item.name, `${item.why_it_matters} 当前状态：${item.current_status}`, item.direction)),
    ...result.scenario_suggestions.map((item) => card(item.name, item.rationale, `${item.shock_type}: ${item.target_codes.join(", ")}`)),
    card("边界声明", result.disclaimer),
  ].join("");
}

async function loadAnalysis() {
  const analysis = await fetchJson("/api/risk/analysis");
  setText("#analysisScore", fmt(analysis.score, 0));
  setText("#analysisLevel", analysis.level || levelFromScore(analysis.score));
  setText("#analysisSummary", `本页拆解 ${analysis.date} 的综合风险贡献、上升驱动和下降驱动。`);
  $("#componentAttribution").innerHTML = analysis.components.map((item) => card(item.name, `权重 ${fmt(item.weight, 2)}，30天变化 ${signed(item.delta_30d)}。`, `贡献 ${fmt(item.contribution, 1)}`)).join("");
  $("#driverRanking").innerHTML = [...analysis.top_positive_drivers, ...analysis.top_negative_drivers].map((item) => card(item.name, item.explanation, signed(item.delta_30d))).join("");
  $("#indicatorMatrix").innerHTML = analysis.components.flatMap((component) => component.indicators.map((item) => card(item.name, item.explanation, `${item.source} / ${fmt(item.score, 1)}`))).join("");
}

async function loadReplay() {
  const days = $("#replayWindowSelect")?.value || 120;
  const result = await fetchJson(`/api/risk/replay?window_days=${days}`);
  setText("#replaySummary", result.interpretation);
  setText("#replayChange", signed(result.change));
  setText("#replayWindow", `近${days}日`);
  $("#downloadReplay")?.setAttribute("href", `/api/exports/replay.csv?window_days=${days}`);
  $("#assetMoves").innerHTML = result.assets.map((item) => card(item.name, `起点 ${fmt(item.start, 2)}，终点 ${fmt(item.end, 2)}`, signed(item.return_pct))).join("");
  $("#replayComponents").innerHTML = result.components.map((item) => `<article><strong>${htmlEscape(item.name)}</strong><span>起点 ${fmt(item.start, 1)}</span><span>终点 ${fmt(item.end, 1)}</span><span>变化 ${signed(item.change)}</span></article>`).join("");
  renderRiskChart(result.history, "replayChart");
}

async function loadSpeciesPresets() {
  const presets = await fetchJson("/api/species/presets");
  const select = $("#speciesSelect");
  if (!select) return;
  select.innerHTML = presets.map((item) => `<option value="${htmlEscape(item.scientific_name)}" data-source="${htmlEscape(item.source)}" data-region="${htmlEscape(item.region)}">${htmlEscape(item.chinese_name)} / ${htmlEscape(item.scientific_name)}</option>`).join("");
  await loadSelectedSpecies();
}

async function loadSelectedSpecies() {
  const option = $("#speciesSelect")?.selectedOptions?.[0];
  if (!option) return;
  const profile = await fetchJson(`/api/species/profile?scientific_name=${encodeURIComponent(option.value)}&source=${option.dataset.source}&region=${option.dataset.region}&limit=240`);
  setText("#speciesTitle", `${profile.chinese_name || "物种"} / ${profile.scientific_name}`);
  setText("#speciesMeta", `${profile.source} / ${profile.region} / 样本 ${profile.sample_size} / 总记录 ${profile.total_records}`);
  $("#speciesProfile").innerHTML = `<strong>${htmlEscape(profile.risk_label)}</strong><p>保护状态：${htmlEscape(profile.conservation_status)}。涉及国家/地区 ${profile.country_count} 个，最近年份 ${profile.recent_year || "--"}。</p><p>观测密度 ${fmt(profile.occurrence_density_score, 1)}，数据质量 ${fmt(profile.data_quality_score, 1)}，物种风险 ${fmt(profile.species_risk_score, 1)}。</p>`;
  $("#occurrenceList").innerHTML = profile.occurrences.slice(0, 12).map((item) => card(item.locality || item.country || "观测点", `${item.event_date || "--"} / ${item.source}`, `${fmt(item.latitude, 2)}, ${fmt(item.longitude, 2)}`)).join("");
  if (window.Plotly && $("#speciesMap")) {
    Plotly.newPlot("speciesMap", [{ type: "scattergeo", mode: "markers", lat: profile.occurrences.map((p) => p.latitude), lon: profile.occurrences.map((p) => p.longitude), text: profile.occurrences.map((p) => p.locality || p.country), marker: { size: 7, color: "#0f766e", opacity: 0.72 } }], { ...plotLayout, geo: { projection: { type: "natural earth" }, showland: true, landcolor: "#eef3f8" } }, { displayModeBar: false, responsive: true });
  }
}

async function loadWorkbench() {
  const status = await fetchJson("/api/workbench/status");
  $("#indicatorLibrary").innerHTML = status.indicators.map((item) => `<article><strong>${htmlEscape(item.name)}</strong><p>${htmlEscape(item.explanation || item.source)}</p><span>${htmlEscape(item.frequency)}</span><span>风险 ${fmt(item.score, 1)}</span></article>`).join("");
  $("#alertList").innerHTML = status.alerts.map((item) => card(item.title, item.message, item.level)).join("");
  $("#dataHealthList").innerHTML = status.data_sources.map((item) => card(item.source, item.note, item.status)).join("");
  $("#downloadCards").innerHTML = [
    ["/api/exports/risk-history.csv", "历史风险 CSV"],
    ["/api/exports/indicators.csv", "指标库 CSV"],
    ["/api/exports/alerts.csv", "预警列表 CSV"],
    ["/api/exports/replay.csv?window_days=120", "复盘 CSV"],
  ].map(([href, title]) => `<a class="report-card" href="${href}"><strong>${title}</strong><span>下载</span></a>`).join("");
}

async function loadReports() {
  const templates = await fetchJson("/api/reports/templates");
  $("#reportTemplates").innerHTML = templates.map((item) => `<a class="report-card" href="${item.endpoint}"><strong>${htmlEscape(item.title)}</strong><p>${htmlEscape(item.description)}</p></a>`).join("");
}

async function exportReport() {
  const result = await postJson("/api/report/export", {});
  alert(`报告已生成：${result.path}`);
}

window.addEventListener("DOMContentLoaded", () => {
  boot().catch((error) => {
    console.error(error);
    setText("#health", "前端加载异常");
  });
});
