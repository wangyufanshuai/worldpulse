const chartTheme = {
  paper_bgcolor: "rgba(0,0,0,0)",
  plot_bgcolor: "rgba(0,0,0,0)",
  font: { color: "rgba(244,248,251,0.82)", family: "Aptos, Segoe UI, Microsoft YaHei, sans-serif" },
  margin: { l: 46, r: 24, t: 28, b: 44 },
  xaxis: {
    gridcolor: "rgba(236,248,255,0.08)",
    zerolinecolor: "rgba(236,248,255,0.14)",
    tickfont: { color: "rgba(244,248,251,0.58)" },
  },
  yaxis: {
    gridcolor: "rgba(236,248,255,0.08)",
    zerolinecolor: "rgba(236,248,255,0.14)",
    tickfont: { color: "rgba(244,248,251,0.58)" },
  },
  legend: { orientation: "h", font: { color: "rgba(244,248,251,0.74)" } },
};

const plotConfig = { displayModeBar: false, responsive: true };

function $(selector) {
  return document.querySelector(selector);
}

function $all(selector) {
  return [...document.querySelectorAll(selector)];
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(await response.text());
  return response.json();
}

function postJson(url, payload) {
  return fetchJson(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function htmlEscape(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}

function setText(selector, value) {
  const element = $(selector);
  if (element) element.textContent = value ?? "--";
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
  if (score >= 75) return "#ff6b6b";
  if (score >= 60) return "#ffd27a";
  if (score >= 40) return "#63d7ff";
  return "#45e0bd";
}

function levelFromScore(score) {
  if (score >= 75) return "极高风险";
  if (score >= 60) return "高风险";
  if (score >= 40) return "中等风险";
  return "低风险";
}

function card(title, body, meta = "") {
  return `<article class="analysis-card"><strong>${htmlEscape(title)}</strong>${meta ? `<em>${htmlEscape(meta)}</em>` : ""}<p>${htmlEscape(body)}</p></article>`;
}

function setBusy(element, text = "加载中...") {
  if (element) element.innerHTML = card(text, "正在读取接口数据，请稍候。");
}

function setError(element, title, error) {
  if (element) element.innerHTML = card(title, error?.message || String(error || "未知错误"));
}

function animateNumber(selector, value, digits = 0) {
  const element = $(selector);
  const target = Number(value);
  if (!element || !Number.isFinite(target)) {
    setText(selector, "--");
    return;
  }
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduced) {
    element.textContent = fmt(target, digits);
    return;
  }
  const start = Number(element.dataset.value || element.textContent) || 0;
  const duration = 720;
  const startTime = performance.now();
  element.dataset.value = String(target);
  function tick(now) {
    const t = Math.min(1, (now - startTime) / duration);
    const eased = 1 - Math.pow(1 - t, 3);
    element.textContent = fmt(start + (target - start) * eased, digits);
    if (t < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

function touchModuleMotion(view) {
  if (!view) return;
  view.classList.remove("is-entering");
  void view.offsetWidth;
  view.classList.add("is-entering");
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
  $("#runCausal")?.addEventListener("click", runCausalAnalysis);
  $("#exportCausalReport")?.addEventListener("click", exportCausalReport);
  $("#aiAgentSelect")?.addEventListener("change", loadEventDigest);
  $("#aiWindow")?.addEventListener("change", loadEventDigest);
  ["shockIntensity", "shockDuration", "shockPropagation"].forEach((id) => $(`#${id}`)?.addEventListener("input", updateSimulationLabels));
  $all(".module-tab").forEach((button) => button.addEventListener("click", () => showModule(button.dataset.module)));

  try {
    const health = await fetchJson("/api/health");
    setText("#health", health.status === "ok" ? "服务在线" : "服务降级");
  } catch {
    setText("#health", "服务不可用");
  }

  await Promise.allSettled([loadSpeciesPresets(), loadSimulationSetup(), loadWorkbench(), loadReports(), loadAiModule(), loadCausalPreview()]);
  await renderDashboard();

  const initialModule = window.location.hash.replace("#", "");
  if (initialModule) showModule(initialModule);
}

function showModule(name) {
  const view = $(`#${name}Module`);
  if (!view) return;
  $all(".module-view").forEach((item) => item.classList.add("hidden"));
  view.classList.remove("hidden");
  touchModuleMotion(view);
  $all(".module-tab").forEach((button) => button.classList.toggle("active", button.dataset.module === name));
  window.location.hash = name;
  if (name === "analysis") loadAnalysis();
  if (name === "replay") loadReplay();
  if (name === "ai") loadAiModule();
  if (name === "causal") runCausalAnalysis();
}

async function renderDashboard() {
  try {
    const overview = await fetchJson("/api/risk/overview");
    window.worldPulseOverview = overview;
    renderLatest(overview.latest);
    renderComponents(overview.latest.components || []);
    renderDrivers(overview.latest.components || []);
    renderRiskChart(overview.history || [], "chart");
    renderScenarioControls(overview.latest.components || []);
  } catch (error) {
    setText("#headline", "风险总览加载失败");
    setText("#summary", error.message || "请检查后端服务。");
  }
}

function renderLatest(risk) {
  animateNumber("#score", risk.score, 0);
  const level = risk.display_level || levelFromScore(risk.score);
  setText("#level", level);
  setText("#headline", `${level}，${risk.display_trend || risk.trend || "状态已更新"}`);
  setText("#summary", risk.summary || "");
  setText("#forecast", risk.display_forecast_label || risk.forecast_label || "--");
  setText("#trend", risk.display_trend || risk.trend || "--");
  setText("#date", risk.date || "--");
  const dial = $("#riskDial");
  if (dial) dial.style.setProperty("--risk-color", riskColor(risk.score));
}

function renderComponents(components) {
  const target = $("#components");
  if (!target) return;
  if (!components.length) {
    target.innerHTML = card("暂无分项风险", "接口没有返回风险结构。");
    return;
  }
  target.innerHTML = components.map((item) => `
    <article>
      <span>${htmlEscape(item.display_name || item.name)}</span>
      <strong style="color:${riskColor(item.score)}">${fmt(item.score, 1)}</strong>
      <meter min="0" max="100" value="${htmlEscape(item.score)}"></meter>
      <small class="muted">${htmlEscape(item.display_trend || item.trend || item.source || "")}</small>
    </article>
  `).join("");
}

function renderDrivers(components) {
  const target = $("#drivers");
  if (!target) return;
  const drivers = components.flatMap((component) => (component.drivers || []).map((driver) => ({ component: component.display_name || component.name, driver }))).slice(0, 8);
  target.innerHTML = drivers.length
    ? drivers.map((item) => card(item.driver, "来自当前风险分项的主要驱动信号。", item.component)).join("")
    : card("暂无驱动信号", "接口没有返回主要驱动。");
}

function renderRiskChart(history, elementId) {
  const element = document.getElementById(elementId);
  if (!window.Plotly || !element || !history.length) return;
  Plotly.newPlot(
    elementId,
    [{
      x: history.map((p) => p.date),
      y: history.map((p) => p.score),
      type: "scatter",
      mode: "lines",
      line: { color: "#63d7ff", width: 3, shape: "spline" },
      fill: "tozeroy",
      fillcolor: "rgba(99,215,255,0.12)",
      hovertemplate: "%{x}<br>风险 %{y:.1f}<extra></extra>",
    }],
    { ...chartTheme, yaxis: { ...chartTheme.yaxis, range: [0, 100] } },
    plotConfig
  );
}

function renderScenarioControls(components) {
  const target = $("#scenarioControls");
  if (!target || target.dataset.ready === "1") return;
  target.dataset.ready = "1";
  target.innerHTML = components.map((item) => `
    <label class="scenario-slider">
      <span>${htmlEscape(item.display_name || item.name)} <b id="sc-${htmlEscape(item.key)}">${fmt(item.score, 0)}</b></span>
      <input type="range" min="0" max="100" value="${htmlEscape(item.score)}" data-key="${htmlEscape(item.key)}" data-name="${htmlEscape(item.display_name || item.name)}" />
    </label>
  `).join("");
  target.querySelectorAll("input").forEach((input) => input.addEventListener("input", updateQuickScenario));
  updateQuickScenario();
}

function updateQuickScenario() {
  const inputs = $all("#scenarioControls input");
  if (!inputs.length) return;
  const values = inputs.map((input) => Number(input.value));
  inputs.forEach((input) => setText(`#sc-${input.dataset.key}`, fmt(input.value, 0)));
  const score = values.reduce((sum, value) => sum + value, 0) / values.length;
  animateNumber("#scenarioScore", score, 0);
  setText("#scenarioLevel", levelFromScore(score));
  const top = [...inputs].sort((a, b) => Number(b.value) - Number(a.value))[0];
  setText("#scenarioOutput", `当前快速敏感性总分约 ${fmt(score, 1)}，主要压力来自 ${top?.dataset.name || "未知分项"}。`);
}

async function loadSimulationSetup() {
  try {
    const [agents, scenarios, health] = await Promise.all([
      fetchJson("/api/simulation/agents"),
      fetchJson("/api/simulation/scenarios"),
      fetchJson("/api/simulation/data-health"),
    ]);
    window.worldPulseAgents = agents;
    window.worldPulseScenarios = scenarios;
    const targetSelect = $("#shockTargets");
    if (targetSelect) targetSelect.innerHTML = agents.map((agent) => `<option value="${htmlEscape(agent.code)}">${htmlEscape(agent.name)} (${htmlEscape(agent.code)})</option>`).join("");
    const aiSelect = $("#aiAgentSelect");
    if (aiSelect) aiSelect.innerHTML = `<option value="">全球</option>${agents.map((agent) => `<option value="${htmlEscape(agent.code)}">${htmlEscape(agent.name)} (${htmlEscape(agent.code)})</option>`).join("")}`;
    const scenarioSelect = $("#simulationScenario");
    if (scenarioSelect) scenarioSelect.innerHTML = scenarios.map((scenario, index) => `<option value="${index}">${htmlEscape(scenario.name)}</option>`).join("");
    renderSimulationHealth(health);
    applySelectedScenario();
    await runSimulationFromControls();
  } catch (error) {
    setError($("#simulationSummary"), "模拟器初始化失败", error);
  }
}

function applySelectedScenario() {
  const scenario = window.worldPulseScenarios?.[Number($("#simulationScenario")?.value || 0)];
  if (!scenario?.shocks?.length) return;
  const shock = scenario.shocks[0];
  if ($("#shockType")) $("#shockType").value = shock.shock_type;
  if ($("#shockIntensity")) $("#shockIntensity").value = shock.intensity;
  if ($("#shockDuration")) $("#shockDuration").value = shock.duration_months;
  if ($("#shockPropagation")) $("#shockPropagation").value = shock.propagation;
  const select = $("#shockTargets");
  if (select) [...select.options].forEach((option) => (option.selected = shock.target_codes.includes(option.value)));
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
  try {
    const result = await postJson("/api/simulation/run", {
      shocks: [shock],
      horizon_months: 12,
      runs: Number($("#simulationRuns")?.value || 500),
      seed: 42,
    });
    window.worldPulseLastSimulation = result;
    renderSimulation(result);
  } catch (error) {
    setText("#simulationSummary", `模拟失败：${error.message || error}`);
  }
}

function renderSimulation(result) {
  setText("#simulationSummary", result.summary);
  const last = result.global_path?.at(-1);
  animateNumber("#simulationScore", last?.p50, 1);
  setText("#simulationBand", `P10 ${fmt(last?.p10, 1)} / P90 ${fmt(last?.p90, 1)}`);
  renderSimulationPath(result.global_path || []);
  renderSimulationMap(result.map_points || []);
  $("#simulationDrivers").innerHTML = (result.drivers || []).map((driver) => card(driver.name, driver.explanation, `贡献 ${fmt(driver.contribution, 1)}`)).join("");
  $("#countryImpactList").innerHTML = (result.countries || []).slice(0, 10).map((country) => card(`${country.name} (${country.code})`, `P50 ${fmt(country.p50, 1)}，不确定性 ${fmt(country.uncertainty, 1)}，上行概率 ${fmt(country.upside_probability * 100, 0)}%。`, `起点 ${fmt(country.start_risk, 1)}`)).join("");
  $("#propagationList").innerHTML = (result.propagation_edges || []).slice(0, 10).map((edge) => card(`${edge.source} -> ${edge.target}`, `${edge.channel} 传播权重 ${fmt(edge.weight, 2)}，影响 ${fmt(edge.impact, 2)}。`)).join("");
  if (result.countries?.[0]) loadAgentDetail(result.countries[0].code);
}

function renderSimulationPath(points) {
  if (!window.Plotly || !$("#simulationPathChart") || !points.length) return;
  const x = points.map((p) => `M${p.month}`);
  Plotly.newPlot(
    "simulationPathChart",
    [
      { x, y: points.map((p) => p.p90), type: "scatter", mode: "lines", line: { width: 0 }, showlegend: false, hoverinfo: "skip" },
      { x, y: points.map((p) => p.p10), type: "scatter", mode: "lines", fill: "tonexty", fillcolor: "rgba(99,215,255,0.16)", line: { width: 0 }, name: "P10-P90" },
      { x, y: points.map((p) => p.p50), type: "scatter", mode: "lines", line: { color: "#63d7ff", width: 3, shape: "spline" }, name: "P50" },
    ],
    { ...chartTheme, yaxis: { ...chartTheme.yaxis, range: [0, 100] } },
    plotConfig
  );
}

function renderSimulationMap(points) {
  if (!window.Plotly || !$("#simulationMap") || !points.length) return;
  Plotly.newPlot(
    "simulationMap",
    [{
      type: "scattergeo",
      lon: points.map((p) => p.longitude),
      lat: points.map((p) => p.latitude),
      text: points.map((p) => `${p.name} ${fmt(p.risk, 1)}`),
      customdata: points.map((p) => p.code),
      mode: "markers",
      marker: {
        size: points.map((p) => 9 + p.uncertainty),
        color: points.map((p) => p.risk),
        colorscale: [[0, "#45e0bd"], [0.5, "#ffd27a"], [1, "#ff6b6b"]],
        cmin: 20,
        cmax: 90,
        line: { color: "rgba(255,255,255,0.9)", width: 1 },
      },
      hovertemplate: "%{text}<extra></extra>",
    }],
    {
      ...chartTheme,
      geo: {
        projection: { type: "natural earth" },
        bgcolor: "rgba(0,0,0,0)",
        showland: true,
        landcolor: "rgba(236,248,255,0.08)",
        showocean: true,
        oceancolor: "rgba(99,215,255,0.035)",
        coastlinecolor: "rgba(236,248,255,0.22)",
        countrycolor: "rgba(236,248,255,0.16)",
      },
    },
    plotConfig
  );
  $("#simulationMap").on("plotly_click", (event) => loadAgentDetail(event.points?.[0]?.customdata));
}

async function loadAgentDetail(code) {
  if (!code) return;
  try {
    const detail = await fetchJson(`/api/simulation/agent/${code}`);
    setText("#agentDetailTitle", `${detail.agent.name} (${detail.agent.code})`);
    const states = Object.entries(detail.agent.state || {}).map(([key, value]) => card(key, detail.state_explanations?.[key] || "状态变量", fmt(value, 1))).join("");
    const raw = Object.entries(detail.raw_indicators || {}).slice(0, 12).map(([key, value]) => `<span><b>${htmlEscape(key)}</b>${htmlEscape(value)}</span>`).join("");
    $("#agentDetail").innerHTML = `${card("数据可信度", `质量分 ${fmt(detail.agent.data_quality_score, 0)}，兜底字段：${(detail.fallback_fields || []).join("、") || "无"}`)}${states}<article class="analysis-card"><strong>原始指标</strong><p class="chip-row">${raw}</p></article>`;
  } catch (error) {
    setError($("#agentDetail"), "国家详情加载失败", error);
  }
}

function renderSimulationHealth(items) {
  const target = $("#simulationDataHealth");
  if (!target) return;
  target.innerHTML = (items || []).map((item) => `<article><strong>${htmlEscape(item.source)}</strong><p>${htmlEscape(item.note)}</p><span>状态：${htmlEscape(item.status)}</span><span>真实字段：${htmlEscape(item.real_field_count)}</span><span>兜底字段：${htmlEscape(item.fallback_field_count)}</span></article>`).join("");
}

async function loadAiModule() {
  const statusTarget = $("#aiStatus");
  if (!statusTarget) return;
  try {
    const status = await fetchJson("/api/ai/status");
    statusTarget.innerHTML = card(
      status.enabled ? "AI 已启用" : "AI 未启用",
      status.enabled
        ? `主模型：${status.provider} / ${status.model}；备用：${status.fallback_provider} / ${status.fallback_model}；推荐：${status.recommended_provider || "deepseek"} / ${status.recommended_model || "deepseek-v4-pro"}${status.last_error ? `；最近错误：${status.last_error}` : ""}`
        : "未配置 SILICONFLOW_API_KEY 或 DEEPSEEK_API_KEY，页面会使用本地兜底分析，不影响其他功能。",
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
  } catch (error) {
    setError(statusTarget, "AI 状态加载失败", error);
  }
}

async function loadEventDigest() {
  const target = $("#eventDigest");
  if (!target) return;
  setBusy(target, "事件摘要加载中");
  const code = $("#aiAgentSelect")?.value;
  const days = $("#aiWindow")?.value || 30;
  const url = code ? `/api/events/agent/${code}?window_days=${days}` : `/api/events/digest?window_days=${days}&region=global`;
  try {
    const digest = await fetchJson(url);
    target.innerHTML = [
      card(`${digest.scope} / 近 ${digest.window_days} 天`, `总事件量代理值：${digest.total_events}。来源：${digest.source}`),
      ...(digest.topics || []).slice(0, 7).map((topic) => card(topic.name, topic.summary, `强度 ${fmt(topic.intensity, 1)} / ${topic.source}`)),
      ...(digest.notes || []).map((note) => card("数据提示", note)),
    ].join("");
  } catch (error) {
    setError(target, "事件摘要加载失败", error);
  }
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
  try {
    const result = await postJson(kind === "simulation" ? "/api/ai/analyze-simulation" : "/api/ai/analyze-risk", payload);
    window.worldPulseLastAiPayload = payload;
    renderAiResult(result);
  } catch (error) {
    setError(target, "AI 分析失败", error);
  }
}

async function exportAiReport() {
  const payload = window.worldPulseLastAiPayload || {
    focus: "risk",
    agent_code: $("#aiAgentSelect")?.value || null,
    window_days: Number($("#aiWindow")?.value || 30),
    simulation: null,
  };
  try {
    const result = await postJson("/api/ai/report/export", payload);
    alert(`AI 报告已导出：${result.path}`);
  } catch (error) {
    alert(`AI 报告导出失败：${error.message || error}`);
  }
}

function renderAiResult(result) {
  setText("#aiResultTitle", result.title);
  $("#aiResult").innerHTML = [
    card("摘要", result.summary, result.mode),
    ...(result.key_findings || []).map((item, index) => card(`主要结论 ${index + 1}`, item)),
    ...(result.evidence || []).map((item) => card(item.title, item.interpretation, `${item.source} / ${item.value}`)),
    ...(result.uncertainties || []).map((item) => card("关键不确定性", item)),
    ...(result.watch_signals || []).map((item) => card(item.name, `${item.why_it_matters} 当前状态：${item.current_status}`, item.direction)),
    ...(result.scenario_suggestions || []).map((item) => card(item.name, item.rationale, `${item.shock_type}: ${item.target_codes.join(", ")}`)),
    card("边界声明", result.disclaimer),
  ].join("");
}

function causalPayload() {
  return {
    event_type: $("#causalEventType")?.value || null,
    region: $("#causalRegion")?.value || "global",
    window_days: Number($("#causalWindow")?.value || 30),
    horizon_days: Number($("#causalHorizon")?.value || 20),
    use_ai: true,
  };
}

async function loadCausalPreview() {
  const target = $("#causalEvents");
  if (!target) return;
  try {
    const events = await fetchJson("/api/causal/events?window_days=30&region=global");
    renderCausalEvents(events);
  } catch (error) {
    setError(target, "因果事件加载失败", error);
  }
}

async function runCausalAnalysis() {
  const reasoning = $("#causalReasoning");
  setBusy(reasoning, "因果分析中");
  try {
    const payload = causalPayload();
    const result = await postJson("/api/causal/analyze", payload);
    window.worldPulseLastCausalPayload = payload;
    renderCausalResult(result);
  } catch (error) {
    setError(reasoning, "因果分析失败", error);
  }
}

async function exportCausalReport() {
  const payload = window.worldPulseLastCausalPayload || causalPayload();
  try {
    const result = await postJson("/api/causal/report/export", payload);
    alert(`因果报告已导出：${result.path}`);
  } catch (error) {
    alert(`因果报告导出失败：${error.message || error}`);
  }
}

function renderCausalResult(result) {
  setText("#causalTitle", result.title);
  renderCausalEvents(result.events || []);
  renderCausalGraph(result.chains?.[0]);
  $("#causalImpacts").innerHTML = (result.impacts || []).map((item) => card(
    item.asset_name,
    `方向：${directionLabel(item.direction)}，期望变化 ${signed(item.expected_return_pct)}%，置信度 ${fmt(item.confidence, 1)}。${item.rationale}`,
    item.asset_key
  )).join("");
  const backtest = result.backtest || {};
  $("#causalBacktest").innerHTML = [
    card("方向一致性", `样本数 ${backtest.sample_count || 0}，胜率 ${fmt((backtest.hit_rate || 0) * 100, 0)}%，平均影响 ${fmt(backtest.average_impact, 2)}%，最大反向误差 ${fmt(backtest.max_error, 2)}%。`, backtest.event_type || "--"),
    ...((backtest.impacts || []).slice(0, 4).map((item) => card(item.asset_name, `历史平均变化 ${signed(item.expected_return_pct)}%，置信度 ${fmt(item.confidence, 1)}。`, item.direction))),
  ].join("");
  $("#causalSimilar").innerHTML = (result.similar_events || []).map((item) => card(
    `${item.date} / 相似度 ${fmt(item.similarity, 1)}`,
    `${item.market_move}。${item.notes}`,
    item.event_type
  )).join("");
  $("#causalErrors").innerHTML = (result.error_attribution || []).map((item) => card("错误归因风险", item)).join("");
  $("#causalReasoning").innerHTML = [
    card("摘要", result.summary),
    card(result.ai_explanation?.startsWith("[") ? "AI live 解释" : "本地兜底解释", result.ai_explanation),
    ...(result.reasoning_path || []).map((item, index) => card(`推理步骤 ${index + 1}`, item)),
    ...(result.uncertainty || []).map((item) => card("关键不确定性", item)),
    card("边界声明", result.disclaimer),
  ].join("");
}

function renderCausalEvents(events) {
  const target = $("#causalEvents");
  if (!target) return;
  target.innerHTML = events.length
    ? events.slice(0, 7).map((item) => card(item.name, `${item.summary} 强度 ${fmt(item.intensity, 1)}，置信度 ${fmt(item.confidence, 1)}。`, `${item.region} / ${item.source}`)).join("")
    : card("暂无事件候选", "当前窗口没有形成稳定事件信号。");
}

function renderCausalGraph(chain) {
  if (!window.Plotly || !$("#causalGraph") || !chain?.nodes?.length) return;
  const nodes = chain.nodes;
  const edges = chain.edges || [];
  const positions = {};
  nodes.forEach((node, index) => {
    positions[node.id] = {
      x: index % 3,
      y: 1.5 - Math.floor(index / 3),
    };
  });
  const edgeX = [];
  const edgeY = [];
  edges.forEach((edge) => {
    const source = positions[edge.source];
    const target = positions[edge.target];
    if (!source || !target) return;
    edgeX.push(source.x, target.x, null);
    edgeY.push(source.y, target.y, null);
  });
  Plotly.newPlot(
    "causalGraph",
    [
      { x: edgeX, y: edgeY, type: "scatter", mode: "lines", line: { color: "rgba(99,215,255,0.34)", width: 2 }, hoverinfo: "skip", showlegend: false },
      {
        x: nodes.map((node) => positions[node.id].x),
        y: nodes.map((node) => positions[node.id].y),
        type: "scatter",
        mode: "markers+text",
        text: nodes.map((node) => node.label),
        textposition: "bottom center",
        marker: { size: nodes.map((node) => 24 + node.score * 0.26), color: nodes.map((node) => node.score), colorscale: [[0, "#45e0bd"], [0.5, "#ffd27a"], [1, "#ff6b6b"]], line: { color: "rgba(255,255,255,0.9)", width: 1 } },
        customdata: nodes.map((node) => `${node.kind} / ${fmt(node.score, 1)}`),
        hovertemplate: "%{text}<br>%{customdata}<extra></extra>",
        showlegend: false,
      },
    ],
    { ...chartTheme, xaxis: { visible: false }, yaxis: { visible: false }, annotations: edges.map((edge) => {
      const source = positions[edge.source];
      const target = positions[edge.target];
      return source && target ? { x: (source.x + target.x) / 2, y: (source.y + target.y) / 2 + 0.08, text: edge.relation, showarrow: false, font: { size: 11, color: "rgba(244,248,251,0.68)" } } : null;
    }).filter(Boolean) },
    plotConfig
  );
}

function directionLabel(direction) {
  return { up: "上行", down: "下行", mixed: "分化" }[direction] || direction;
}

async function loadAnalysis() {
  try {
    const analysis = await fetchJson("/api/risk/analysis");
    animateNumber("#analysisScore", analysis.score, 0);
    setText("#analysisLevel", analysis.level || levelFromScore(analysis.score));
    setText("#analysisSummary", `本页拆解 ${analysis.date} 的综合风险贡献、上升驱动和下降驱动。`);
    $("#componentAttribution").innerHTML = (analysis.components || []).map((item) => card(item.name, `权重 ${fmt(item.weight, 2)}，30 天变化 ${signed(item.delta_30d)}。`, `贡献 ${fmt(item.contribution, 1)}`)).join("");
    $("#driverRanking").innerHTML = [...(analysis.top_positive_drivers || []), ...(analysis.top_negative_drivers || [])].map((item) => card(item.name, item.explanation, signed(item.delta_30d))).join("");
    $("#indicatorMatrix").innerHTML = (analysis.components || []).flatMap((component) => (component.indicators || []).map((item) => card(item.name, item.explanation, `${item.source} / ${fmt(item.score, 1)}`))).join("");
  } catch (error) {
    setText("#analysisSummary", `详细分析加载失败：${error.message || error}`);
  }
}

async function loadReplay() {
  const days = $("#replayWindowSelect")?.value || 120;
  try {
    const result = await fetchJson(`/api/risk/replay?window_days=${days}`);
    setText("#replaySummary", result.interpretation);
    animateNumber("#replayChange", result.change, 1);
    setText("#replayWindow", `近 ${days} 日`);
    $("#downloadReplay")?.setAttribute("href", `/api/exports/replay.csv?window_days=${days}`);
    $("#assetMoves").innerHTML = (result.assets || []).map((item) => card(item.name, `起点 ${fmt(item.start, 2)}，终点 ${fmt(item.end, 2)}`, signed(item.return_pct))).join("");
    $("#replayComponents").innerHTML = (result.components || []).map((item) => `<article><strong>${htmlEscape(item.name)}</strong><span>起点 ${fmt(item.start, 1)}</span><span>终点 ${fmt(item.end, 1)}</span><span>变化 ${signed(item.change)}</span></article>`).join("");
    renderRiskChart(result.history || [], "replayChart");
  } catch (error) {
    setText("#replaySummary", `复盘加载失败：${error.message || error}`);
  }
}

async function loadSpeciesPresets() {
  try {
    const presets = await fetchJson("/api/species/presets");
    const select = $("#speciesSelect");
    if (!select) return;
    select.innerHTML = presets.map((item) => `<option value="${htmlEscape(item.scientific_name)}" data-source="${htmlEscape(item.source)}" data-region="${htmlEscape(item.region)}">${htmlEscape(item.chinese_name)} / ${htmlEscape(item.scientific_name)}</option>`).join("");
    await loadSelectedSpecies();
  } catch (error) {
    setText("#speciesTitle", `物种预设加载失败：${error.message || error}`);
  }
}

async function loadSelectedSpecies() {
  const option = $("#speciesSelect")?.selectedOptions?.[0];
  if (!option) return;
  try {
    const profile = await fetchJson(`/api/species/profile?scientific_name=${encodeURIComponent(option.value)}&source=${option.dataset.source}&region=${option.dataset.region}&limit=240`);
    setText("#speciesTitle", `${profile.chinese_name || "物种"} / ${profile.scientific_name}`);
    setText("#speciesMeta", `${profile.source} / ${profile.region} / 样本 ${profile.sample_size} / 总记录 ${profile.total_records}`);
    $("#speciesProfile").innerHTML = `<article class="analysis-card"><strong>${htmlEscape(profile.risk_label)}</strong><p>保护状态：${htmlEscape(profile.conservation_status)}。涉及国家或地区 ${profile.country_count} 个，最近年份 ${profile.recent_year || "--"}。</p><p>观测密度 ${fmt(profile.occurrence_density_score, 1)}，数据质量 ${fmt(profile.data_quality_score, 1)}，物种风险 ${fmt(profile.species_risk_score, 1)}。</p></article>`;
    $("#occurrenceList").innerHTML = (profile.occurrences || []).slice(0, 12).map((item) => card(item.locality || item.country || "观测点", `${item.event_date || "--"} / ${item.source}`, `${fmt(item.latitude, 2)}, ${fmt(item.longitude, 2)}`)).join("");
    if (window.Plotly && $("#speciesMap")) {
      Plotly.newPlot(
        "speciesMap",
        [{
          type: "scattergeo",
          mode: "markers",
          lat: profile.occurrences.map((p) => p.latitude),
          lon: profile.occurrences.map((p) => p.longitude),
          text: profile.occurrences.map((p) => p.locality || p.country),
          marker: { size: 7, color: "#45e0bd", opacity: 0.76, line: { color: "rgba(255,255,255,0.8)", width: 1 } },
        }],
        { ...chartTheme, geo: { projection: { type: "natural earth" }, bgcolor: "rgba(0,0,0,0)", showland: true, landcolor: "rgba(236,248,255,0.08)", showocean: true, oceancolor: "rgba(99,215,255,0.035)", coastlinecolor: "rgba(236,248,255,0.22)" } },
        plotConfig
      );
    }
  } catch (error) {
    setText("#speciesTitle", `物种加载失败：${error.message || error}`);
  }
}

async function loadWorkbench() {
  try {
    const status = await fetchJson("/api/workbench/status");
    $("#indicatorLibrary").innerHTML = (status.indicators || []).map((item) => `<article><strong>${htmlEscape(item.name)}</strong><p>${htmlEscape(item.explanation || item.source)}</p><span>${htmlEscape(item.frequency)}</span><span>风险 ${fmt(item.score, 1)}</span></article>`).join("");
    $("#alertList").innerHTML = (status.alerts || []).map((item) => card(item.title, item.message, item.level)).join("");
    $("#dataHealthList").innerHTML = (status.data_sources || []).map((item) => card(item.source, item.note, item.status)).join("");
    $("#downloadCards").innerHTML = [
      ["/api/exports/risk-history.csv", "历史风险 CSV"],
      ["/api/exports/indicators.csv", "指标库 CSV"],
      ["/api/exports/alerts.csv", "预警列表 CSV"],
      ["/api/exports/replay.csv?window_days=120", "复盘 CSV"],
    ].map(([href, title]) => `<a class="report-card" href="${href}"><strong>${title}</strong><span>下载</span></a>`).join("");
  } catch (error) {
    $("#dataHealthList").innerHTML = card("工作台加载失败", error.message || error);
  }
}

async function loadReports() {
  try {
    const templates = await fetchJson("/api/reports/templates");
    $("#reportTemplates").innerHTML = templates.map((item) => `<a class="report-card" href="${htmlEscape(item.endpoint)}"><strong>${htmlEscape(item.title)}</strong><p>${htmlEscape(item.description)}</p></a>`).join("");
  } catch (error) {
    $("#reportTemplates").innerHTML = card("报告模板加载失败", error.message || error);
  }
}

async function exportReport() {
  try {
    const result = await postJson("/api/report/export", {});
    alert(`报告已生成：${result.path}`);
  } catch (error) {
    alert(`报告导出失败：${error.message || error}`);
  }
}

window.addEventListener("DOMContentLoaded", () => {
  boot().catch((error) => {
    console.error(error);
    setText("#health", "前端加载异常");
  });
});
