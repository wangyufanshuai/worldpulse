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
