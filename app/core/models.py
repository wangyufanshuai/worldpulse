from pydantic import BaseModel


class RiskComponent(BaseModel):
    key: str
    name: str
    display_name: str
    score: float
    weight: float
    trend: str
    display_trend: str
    source: str
    drivers: list[str]


class CompositeRisk(BaseModel):
    date: str
    score: float
    level: str
    display_level: str
    trend: str
    display_trend: str
    forecast_30d: float
    forecast_label: str
    display_forecast_label: str
    components: list[RiskComponent]
    summary: str


class RiskPoint(BaseModel):
    date: str
    score: float
    financial: float
    climate: float
    geopolitical: float
    ecology: float
    macro: float


class RiskOverview(BaseModel):
    latest: CompositeRisk
    history: list[RiskPoint]


class IndicatorAnalysis(BaseModel):
    key: str
    name: str
    score: float
    previous_score: float
    delta_30d: float
    source: str
    explanation: str


class ComponentAnalysis(BaseModel):
    key: str
    name: str
    score: float
    weight: float
    contribution: float
    delta_30d: float
    share_of_total: float
    indicators: list[IndicatorAnalysis]


class RiskAnalysis(BaseModel):
    date: str
    score: float
    level: str
    components: list[ComponentAnalysis]
    top_positive_drivers: list[IndicatorAnalysis]
    top_negative_drivers: list[IndicatorAnalysis]


class ReportExport(BaseModel):
    path: str
    markdown: str


class IndicatorLibraryItem(BaseModel):
    key: str
    name: str
    component: str
    score: float
    delta_30d: float
    source: str
    frequency: str
    formula: str
    status: str
    explanation: str


class AlertItem(BaseModel):
    level: str
    title: str
    message: str
    metric: str
    score: float


class DataSourceHealth(BaseModel):
    source: str
    status: str
    cache_file: str | None = None
    cache_age_hours: float | None = None
    note: str


class WorkbenchStatus(BaseModel):
    indicators: list[IndicatorLibraryItem]
    alerts: list[AlertItem]
    data_sources: list[DataSourceHealth]


class ReportTemplate(BaseModel):
    key: str
    title: str
    description: str
    endpoint: str


class ReplayComponentChange(BaseModel):
    key: str
    name: str
    start: float
    end: float
    change: float


class ReplayAssetMove(BaseModel):
    key: str
    name: str
    start: float
    end: float
    return_pct: float


class ReplayResult(BaseModel):
    start_date: str
    end_date: str
    start_score: float
    end_score: float
    change: float
    interpretation: str
    components: list[ReplayComponentChange]
    assets: list[ReplayAssetMove]
    history: list[RiskPoint]


class SpeciesPreset(BaseModel):
    key: str
    chinese_name: str
    scientific_name: str
    group: str
    source: str
    region: str
    conservation_status: str
    conservation_prior_score: float


class SpeciesOccurrence(BaseModel):
    source: str
    scientific_name: str
    common_name: str | None = None
    latitude: float
    longitude: float
    event_date: str | None = None
    year: int | None = None
    country: str | None = None
    locality: str | None = None
    dataset: str | None = None
    basis_of_record: str | None = None


class SpeciesCountryCount(BaseModel):
    country: str
    count: int


class SpeciesProfile(BaseModel):
    scientific_name: str
    chinese_name: str | None = None
    source: str
    region: str
    total_records: int
    sample_size: int
    recent_year: int | None = None
    country_count: int
    top_countries: list[SpeciesCountryCount]
    conservation_status: str
    conservation_prior_score: float
    occurrence_density_score: float
    recency_score: float
    data_quality_score: float
    species_risk_score: float
    risk_label: str
    notes: list[str]
    occurrences: list[SpeciesOccurrence]


class AgentState(BaseModel):
    gdp_pressure: float
    trade_exposure: float
    energy_vulnerability: float
    military_pressure: float
    sentiment_pressure: float
    rate_pressure: float
    conflict_pressure: float
    stability: float


class CountryAgent(BaseModel):
    code: str
    name: str
    region: str
    latitude: float
    longitude: float
    gdp_weight: float
    state: AgentState
    risk_score: float
    data_quality_score: float = 0
    source_breakdown: dict[str, str] = {}
    fallback_fields: list[str] = []
    raw_indicators: dict[str, float | str | None] = {}


class PolicyShock(BaseModel):
    shock_type: str
    target_codes: list[str]
    intensity: float = 0.45
    duration_months: int = 6
    propagation: float = 0.35


class SimulationRequest(BaseModel):
    shocks: list[PolicyShock]
    horizon_months: int = 12
    runs: int = 500
    seed: int | None = 42


class SimulationScenario(BaseModel):
    key: str
    name: str
    description: str
    shocks: list[PolicyShock]


class SimulationPathPoint(BaseModel):
    month: int
    p10: float
    p50: float
    p90: float


class CountrySimulationResult(BaseModel):
    code: str
    name: str
    region: str
    latitude: float
    longitude: float
    start_risk: float
    p10: float
    p50: float
    p90: float
    uncertainty: float
    upside_probability: float


class SimulationMapPoint(BaseModel):
    code: str
    name: str
    latitude: float
    longitude: float
    risk: float
    uncertainty: float
    region: str


class SimulationPropagationEdge(BaseModel):
    source: str
    target: str
    channel: str
    weight: float
    impact: float


class SimulationDriver(BaseModel):
    name: str
    contribution: float
    explanation: str


class SimulationAgentDetail(BaseModel):
    agent: CountryAgent
    state_explanations: dict[str, str]
    source_breakdown: dict[str, str]
    fallback_fields: list[str]
    raw_indicators: dict[str, float | str | None]


class SimulationDataHealth(BaseModel):
    source: str
    status: str
    cache_file: str | None = None
    cache_age_hours: float | None = None
    agent_count: int = 0
    real_field_count: int = 0
    fallback_field_count: int = 0
    note: str


class SimulationResult(BaseModel):
    summary: str
    horizon_months: int
    runs: int
    global_path: list[SimulationPathPoint]
    countries: list[CountrySimulationResult]
    map_points: list[SimulationMapPoint]
    propagation_edges: list[SimulationPropagationEdge]
    drivers: list[SimulationDriver]


class EventTopic(BaseModel):
    key: str
    name: str
    event_count: int
    intensity: float
    source: str
    summary: str


class EventDigest(BaseModel):
    scope: str
    window_days: int
    source: str
    total_events: int
    generated_at: str
    topics: list[EventTopic]
    notes: list[str]


class EvidenceItem(BaseModel):
    title: str
    source: str
    value: str
    interpretation: str


class WatchSignal(BaseModel):
    name: str
    direction: str
    why_it_matters: str
    current_status: str


class ScenarioSuggestion(BaseModel):
    name: str
    shock_type: str
    target_codes: list[str]
    rationale: str


class AIAnalysisRequest(BaseModel):
    focus: str = "global"
    agent_code: str | None = None
    window_days: int = 30
    simulation: SimulationResult | None = None


class AIAnalysisResult(BaseModel):
    enabled: bool
    mode: str
    title: str
    summary: str
    key_findings: list[str]
    evidence: list[EvidenceItem]
    uncertainties: list[str]
    watch_signals: list[WatchSignal]
    scenario_suggestions: list[ScenarioSuggestion]
    disclaimer: str


class CausalEvent(BaseModel):
    event_type: str
    name: str
    region: str
    window_days: int
    intensity: float
    event_count: int
    source: str
    summary: str
    confidence: float


class CausalGraphNode(BaseModel):
    id: str
    label: str
    kind: str
    score: float


class CausalGraphEdge(BaseModel):
    source: str
    target: str
    relation: str
    weight: float
    confidence: float
    explanation: str


class CausalChain(BaseModel):
    event_type: str
    title: str
    nodes: list[CausalGraphNode]
    edges: list[CausalGraphEdge]
    confidence: float
    explanation: str


class MarketImpact(BaseModel):
    asset_key: str
    asset_name: str
    direction: str
    expected_return_pct: float
    confidence: float
    rationale: str


class SimilarEvent(BaseModel):
    date: str
    event_type: str
    title: str
    similarity: float
    market_move: str
    notes: str


class CausalBacktestResult(BaseModel):
    event_type: str
    window_days: int
    sample_count: int
    hit_rate: float
    average_impact: float
    max_error: float
    impacts: list[MarketImpact]
    similar_events: list[SimilarEvent]
    error_attribution: list[str]


class CausalAnalysisRequest(BaseModel):
    event_type: str | None = None
    region: str = "global"
    window_days: int = 30
    horizon_days: int = 20
    use_ai: bool = True


class CausalAnalysisResult(BaseModel):
    title: str
    summary: str
    events: list[CausalEvent]
    chains: list[CausalChain]
    impacts: list[MarketImpact]
    similar_events: list[SimilarEvent]
    backtest: CausalBacktestResult
    uncertainty: list[str]
    error_attribution: list[str]
    reasoning_path: list[str]
    ai_explanation: str
    disclaimer: str


class ResearchProjectCreate(BaseModel):
    title: str
    question: str
    region: str = "global"
    asset_scope: list[str] = ["sp500", "nasdaq", "oil", "gold", "dollar", "vix"]
    event_window_days: int = 30
    event_types: list[str] = ["conflict", "sanctions", "energy", "food", "rates", "trade", "climate"]
    mode: str = "research"
    scenario_config: dict = {}


class ResearchProject(BaseModel):
    project_id: str
    title: str
    question: str
    region: str
    asset_scope: list[str]
    event_window_days: int
    event_types: list[str]
    mode: str = "research"
    scenario_config: dict = {}
    status: str
    created_at: str
    updated_at: str


class ResearchRun(BaseModel):
    run_id: str
    project_id: str
    status: str
    started_at: str
    completed_at: str | None = None
    summary: str
    data_snapshot: dict
    risk_snapshot: dict
    event_snapshot: list[dict]
    simulation_snapshot: dict
    backtest_snapshot: dict


class CausalGraphSnapshot(BaseModel):
    graph_id: str
    project_id: str
    run_id: str
    generated_at: str
    nodes: list[dict]
    edges: list[dict]
    confidence: float
    evidence_sources: list[str]


class GraphEditRequest(BaseModel):
    run_id: str | None = None
    nodes: list[dict] | None = None
    edges: list[dict] | None = None
    confidence: float | None = None
    evidence_sources: list[str] | None = None
    note: str | None = None


class ResearchRunDiff(BaseModel):
    project_id: str
    base_run_id: str
    target_run_id: str
    summary: str
    risk_delta: float | None = None
    confidence_delta: float | None = None
    event_count_delta: int = 0
    evidence_source_delta: int = 0
    added_events: list[str] = []
    removed_events: list[str] = []
    added_sources: list[str] = []
    removed_sources: list[str] = []
    changed_metrics: dict = {}


class ReportCitation(BaseModel):
    citation_id: str
    finding_index: int
    kind: str
    target_id: str
    title: str
    summary: str
    source: str
    confidence: float


class ProjectAIReport(BaseModel):
    report_id: str
    project_id: str
    run_id: str
    generated_at: str
    mode: str
    title: str
    summary: str
    key_findings: list[str]
    evidence: list[EvidenceItem]
    uncertainties: list[str]
    watch_signals: list[WatchSignal]
    scenario_suggestions: list[ScenarioSuggestion]
    citations: list[ReportCitation] = []
    markdown: str
    disclaimer: str


class ProjectChatRequest(BaseModel):
    message: str


class ProjectChatMessage(BaseModel):
    message_id: str
    project_id: str
    role: str
    content: str
    created_at: str
    mode: str = "local"


class ProjectDetail(BaseModel):
    project: ResearchProject
    latest_run: ResearchRun | None = None
    runs: list[ResearchRun] = []
    graph: CausalGraphSnapshot | None = None
    report: ProjectAIReport | None = None
    chat_messages: list[ProjectChatMessage] = []


class WarRoomWorkspaceState(BaseModel):
    project_id: str
    run_id: str | None = None
    project: dict = {}
    run_control: dict = {}
    ui_state: dict = {}
    entity_index: list[dict] = []
    command_actions: list[dict] = []
    insight_cards: list[dict] = []
    entity_details: dict = {}
    compare_ready: bool = False
    replay_ready: bool = False
    disclaimer: str


class WarRoomCountryAgent(BaseModel):
    code: str
    name: str
    region: str
    latitude: float
    longitude: float
    alliance: str
    energy_dependency: float
    food_dependency: float
    trade_exposure: float
    chip_dependency: float
    military_pressure: float
    public_opinion_pressure: float
    financial_stress: float
    stability: float
    risk_score: float


class SupplyChainLink(BaseModel):
    key: str
    name: str
    capacity: float
    disruption: float
    substitution: float
    lag_days: int
    affected_countries: list[str]
    pressure_score: float


class ConflictEvent(BaseModel):
    key: str
    name: str
    description: str
    default_duration_days: int
    target_chains: list[str]
    target_countries: list[str]


class WarRoomScenario(BaseModel):
    key: str
    name: str
    description: str
    duration_days: int = 30
    intensity: float = 0.65
    propagation: float = 0.42
    target_countries: list[str] = []
    target_chains: list[str] = []
    policy_actions: list[str] = []
    country_overrides: dict[str, dict[str, float]] = {}
    chain_overrides: dict[str, dict[str, float]] = {}


class WarRoomScenarioRequest(BaseModel):
    scenario_key: str = "strait_blockade_30d"
    duration_days: int = 30
    intensity: float = 0.65
    propagation: float = 0.42
    target_countries: list[str] = []
    target_chains: list[str] = []
    policy_actions: list[str] = []
    country_overrides: dict[str, dict[str, float]] = {}
    chain_overrides: dict[str, dict[str, float]] = {}
    seed: int | None = 42


class RunJobCreateRequest(BaseModel):
    engine_mode: str = "deterministic"
    scenario: WarRoomScenarioRequest | dict = {}
    seed: int | None = 42
    parent_run_id: str | None = None


class RunLifecycleEvent(BaseModel):
    run_id: str
    seq: int
    event_type: str
    phase: str
    tick: int | None = None
    title: str
    detail: str
    payload: dict = {}
    created_at: str


class RunArtifactSummary(BaseModel):
    artifact_id: str
    run_id: str
    artifact_type: str
    schema_version: str
    sha256: str
    created_at: str


class RunJobStatus(BaseModel):
    run_id: str
    project_id: str
    engine_mode: str
    status: str
    current_phase: str
    progress: float = 0
    seed: int | None = None
    parent_run_id: str | None = None
    result_run_id: str | None = None
    scenario: dict = {}
    error_code: str | None = None
    error_message: str | None = None
    created_at: str
    started_at: str | None = None
    updated_at: str
    completed_at: str | None = None
    cancel_requested_at: str | None = None
    pause_requested_at: str | None = None


class RunControlResponse(BaseModel):
    run: RunJobStatus
    events: list[RunLifecycleEvent] = []


class AgentDecision(BaseModel):
    country_code: str
    country_name: str
    action: str
    rationale: str
    drivers: list[str] = []
    confidence: float
    risk_delta: float
    expected_tradeoff: str = ""


class WarRoomTimelinePoint(BaseModel):
    day: int
    global_risk: float
    energy_pressure: float
    food_pressure: float
    trade_pressure: float
    financial_pressure: float
    public_opinion_pressure: float
    key_development: str
    turning_point: bool = False


class WarRoomHeatmapCell(BaseModel):
    country_code: str
    country_name: str
    region: str
    latitude: float
    longitude: float
    risk: float
    dominant_channel: str
    risk_breakdown: dict[str, float] = {}


class WarRoomImpactGraph(BaseModel):
    nodes: list[dict]
    edges: list[dict]
    confidence: float


class WarRoomPresetBundle(BaseModel):
    countries: list[WarRoomCountryAgent]
    supply_chains: list[SupplyChainLink]
    conflict_events: list[ConflictEvent]
    scenarios: list[WarRoomScenario]
    disclaimer: str


class WarRoomRun(BaseModel):
    scenario: WarRoomScenario
    timeline: list[WarRoomTimelinePoint]
    country_agents: list[WarRoomCountryAgent]
    supply_chains: list[SupplyChainLink]
    impact_graph: WarRoomImpactGraph
    risk_heatmap: list[WarRoomHeatmapCell]
    agent_decisions: list[AgentDecision]
    summary: str
    disclaimer: str
    assumptions: list[str] = []
    ui_state: dict = {}


class WarRoomReplayPack(BaseModel):
    project_id: str
    run_id: str
    base_run_id: str | None = None
    target_run_id: str | None = None
    title: str
    scenario: dict
    policy_actions: list[str] = []
    risk_heatmap: list[dict] = []
    supply_chain_delta: list[dict] = []
    agent_decisions: list[dict] = []
    timeline: list[dict] = []
    timeline_delta: dict = {}
    impact_graph: dict = {}
    assumptions: list[str] = []
    counterfactual_observations: list[str] = []
    summary: dict = {}
    manifest: dict = {}
    model_inputs: dict = {}
    model_outputs: dict = {}
    audit_trail: list[dict] = []
    artifacts: dict = {}
    markdown: str
    disclaimer: str
