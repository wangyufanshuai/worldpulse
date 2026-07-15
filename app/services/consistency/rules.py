from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.core.models import WarRoomRun

from .hashing import stable_hash
from .models import ConsistencyFinding, RuleEvaluation


Rule = Callable[[WarRoomRun], RuleEvaluation]


def _finding(
    rule_id: str,
    *,
    category: str,
    status: str,
    severity: str,
    subject_type: str,
    subject_id: str,
    message_zh: str,
    expected: Any = None,
    actual: Any = None,
    evidence_refs: list[str] | None = None,
    suggested_action: str = "",
) -> ConsistencyFinding:
    identity = {
        "rule_id": rule_id,
        "category": category,
        "status": status,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "expected": expected,
        "actual": actual,
    }
    return ConsistencyFinding(
        finding_id=f"finding_{stable_hash(identity)[:16]}",
        rule_id=rule_id,
        category=category,
        status=status,
        severity=severity,
        subject_type=subject_type,
        subject_id=subject_id,
        message_zh=message_zh,
        expected=expected,
        actual=actual,
        evidence_refs=evidence_refs or [],
        suggested_action=suggested_action,
    )


def numeric_bounds(run: WarRoomRun) -> RuleEvaluation:
    rule_id = "CONSISTENCY.NUMERIC_BOUNDS.V1"
    values: list[tuple[str, Any, float, float]] = []
    country_fields = (
        "energy_dependency", "food_dependency", "trade_exposure", "chip_dependency",
        "military_pressure", "public_opinion_pressure", "financial_stress", "stability", "risk_score",
    )
    for country in run.country_agents:
        for field in country_fields:
            values.append((f"country:{country.code}.{field}", getattr(country, field), 0, 100))
    for chain in run.supply_chains:
        for field in ("capacity", "disruption", "substitution", "pressure_score"):
            values.append((f"chain:{chain.key}.{field}", getattr(chain, field), 0, 100))
        values.append((f"chain:{chain.key}.lag_days", chain.lag_days, 0, 365))
    for point in run.timeline:
        for field in (
            "global_risk", "energy_pressure", "food_pressure", "trade_pressure",
            "financial_pressure", "public_opinion_pressure",
        ):
            values.append((f"timeline:{point.day}.{field}", getattr(point, field), 0, 100))
    for cell in run.risk_heatmap:
        values.append((f"heatmap:{cell.country_code}.risk", cell.risk, 0, 100))
        for channel, value in sorted(cell.risk_breakdown.items()):
            values.append((f"heatmap:{cell.country_code}.{channel}", value, 0, 100))
    values.append(("impact_graph.confidence", run.impact_graph.confidence, 0, 100))
    for index, edge in enumerate(run.impact_graph.edges):
        if "weight" in edge:
            values.append((f"impact_graph.edge:{index}.weight", edge.get("weight"), 0, 1))
        if "confidence" in edge:
            values.append((f"impact_graph.edge:{index}.confidence", edge.get("confidence"), 0, 100))
        if "lag_days" in edge:
            values.append((f"impact_graph.edge:{index}.lag_days", edge.get("lag_days"), 0, 365))
    for decision in run.agent_decisions:
        values.append((f"decision:{decision.country_code}.confidence", decision.confidence, 0, 100))

    if not values:
        return RuleEvaluation(rule_id, False, (_not_evaluated(rule_id, "schema", "war_room_result", "numeric_fields", "没有可检查的数值字段。"),))

    findings = []
    for path, value, minimum, maximum in sorted(values, key=lambda item: item[0]):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not minimum <= float(value) <= maximum:
            findings.append(_finding(
                rule_id,
                category="schema",
                status="failed",
                severity="error",
                subject_type="numeric_field",
                subject_id=path,
                message_zh=f"数值字段 {path} 超出确定性合同允许范围。",
                expected={"minimum": minimum, "maximum": maximum},
                actual=value,
                evidence_refs=[path],
                suggested_action="检查确定性规则输入或数值投影，不要由 Agent 覆盖该字段。",
            ))
    return RuleEvaluation(rule_id, True, tuple(findings))


def referential_integrity(run: WarRoomRun) -> RuleEvaluation:
    rule_id = "CONSISTENCY.REFERENTIAL_INTEGRITY.V1"
    node_ids = [str(node.get("id", "")) for node in run.impact_graph.nodes]
    known_nodes = {node_id for node_id in node_ids if node_id}
    known_countries = {country.code for country in run.country_agents}
    findings = []

    duplicates = sorted({node_id for node_id in node_ids if node_id and node_ids.count(node_id) > 1})
    for node_id in duplicates:
        findings.append(_finding(
            rule_id,
            category="causal",
            status="failed",
            severity="error",
            subject_type="graph_node",
            subject_id=node_id,
            message_zh="因果图包含重复节点 ID。",
            expected="unique node id",
            actual=node_id,
            evidence_refs=[f"impact_graph.nodes:{node_id}"],
            suggested_action="在持久化前统一节点 ID。",
        ))
    for index, edge in enumerate(run.impact_graph.edges):
        for endpoint in ("source", "target"):
            node_id = str(edge.get(endpoint, ""))
            if node_id not in known_nodes:
                findings.append(_finding(
                    rule_id,
                    category="causal",
                    status="failed",
                    severity="error",
                    subject_type="graph_edge",
                    subject_id=f"edge:{index}.{endpoint}",
                    message_zh=f"因果边 {endpoint} 引用了不存在的节点。",
                    expected="existing graph node id",
                    actual=node_id,
                    evidence_refs=[f"impact_graph.edges:{index}"],
                    suggested_action="补齐节点或移除无效因果边。",
                ))
    for chain in run.supply_chains:
        for code in sorted(set(chain.affected_countries) - known_countries):
            findings.append(_finding(
                rule_id,
                category="causal",
                status="failed",
                severity="error",
                subject_type="supply_chain",
                subject_id=f"chain:{chain.key}",
                message_zh="供应链引用了不存在的国家实体。",
                expected="country code in country_agents",
                actual=code,
                evidence_refs=[f"supply_chains:{chain.key}.affected_countries"],
                suggested_action="补齐国家实体或修正供应链影响范围。",
            ))
    for decision in run.agent_decisions:
        if decision.country_code not in known_countries:
            findings.append(_finding(
                rule_id,
                category="causal",
                status="failed",
                severity="error",
                subject_type="decision_projection",
                subject_id=f"decision:{decision.country_code}",
                message_zh="规则决策投影引用了不存在的国家实体。",
                expected="country code in country_agents",
                actual=decision.country_code,
                evidence_refs=[f"agent_decisions:{decision.country_code}"],
                suggested_action="在生成决策投影前验证国家实体。",
            ))
    return RuleEvaluation(rule_id, True, tuple(findings))


def timeline_integrity(run: WarRoomRun) -> RuleEvaluation:
    rule_id = "CONSISTENCY.TIMELINE_ORDER.V1"
    if not run.timeline:
        return RuleEvaluation(rule_id, False, (_not_evaluated(rule_id, "temporal", "timeline", "timeline", "没有时间线数据，无法检查时序。"),))
    days = [point.day for point in run.timeline]
    expected = sorted(set(days))
    findings = []
    if days != expected:
        findings.append(_finding(
            rule_id,
            category="temporal",
            status="failed",
            severity="error",
            subject_type="timeline",
            subject_id="timeline.days",
            message_zh="时间线节点必须严格递增且不能重复。",
            expected=expected,
            actual=days,
            evidence_refs=["timeline"],
            suggested_action="按 day 排序并移除重复时间点。",
        ))
    invalid_days = [day for day in days if day < 0 or day > run.scenario.duration_days]
    if invalid_days:
        findings.append(_finding(
            rule_id,
            category="temporal",
            status="failed",
            severity="error",
            subject_type="timeline",
            subject_id="timeline.bounds",
            message_zh="时间线包含场景持续时间之外的节点。",
            expected={"minimum": 0, "maximum": run.scenario.duration_days},
            actual=invalid_days,
            evidence_refs=["scenario.duration_days", "timeline"],
            suggested_action="限制时间线节点到场景持续时间范围内。",
        ))
    return RuleEvaluation(rule_id, True, tuple(findings))


def event_entity_references(run: WarRoomRun) -> RuleEvaluation:
    rule_id = "CONSISTENCY.EVENT_ENTITY_REFERENCES.V1"
    events = run.ui_state.get("timeline_events") if isinstance(run.ui_state, dict) else None
    if not isinstance(events, list):
        return RuleEvaluation(rule_id, False, (_not_evaluated(rule_id, "causal", "ui_projection", "timeline_events", "结果中没有可审计的事件实体引用。"),))
    country_codes = {country.code for country in run.country_agents}
    chain_keys = {chain.key for chain in run.supply_chains}
    findings = []
    for index, event in enumerate(events):
        for code in sorted(set(event.get("related_countries") or []) - country_codes):
            findings.append(_finding(
                rule_id,
                category="causal",
                status="failed",
                severity="error",
                subject_type="timeline_event",
                subject_id=str(event.get("key") or index),
                message_zh="时间线事件引用了不存在的国家实体。",
                expected="country code in country_agents",
                actual=code,
                evidence_refs=[f"ui_state.timeline_events:{index}"],
                suggested_action="修正事件的 related_countries。",
            ))
        for key in sorted(set(event.get("related_chains") or []) - chain_keys):
            findings.append(_finding(
                rule_id,
                category="causal",
                status="failed",
                severity="error",
                subject_type="timeline_event",
                subject_id=str(event.get("key") or index),
                message_zh="时间线事件引用了不存在的供应链实体。",
                expected="chain key in supply_chains",
                actual=key,
                evidence_refs=[f"ui_state.timeline_events:{index}"],
                suggested_action="修正事件的 related_chains。",
            ))
    return RuleEvaluation(rule_id, True, tuple(findings))


def kpi_recomputability(run: WarRoomRun) -> RuleEvaluation:
    rule_id = "CONSISTENCY.KPI_RECOMPUTABILITY.V1"
    kpis = run.ui_state.get("kpis") if isinstance(run.ui_state, dict) else None
    if not isinstance(kpis, list) or not run.timeline:
        return RuleEvaluation(rule_id, False, (_not_evaluated(rule_id, "schema", "ui_projection", "kpis", "缺少 KPI 或时间线，无法复算展示值。"),))
    by_key = {str(item.get("key")): item for item in kpis if isinstance(item, dict)}
    checks = {
        "global_risk": round(float(run.timeline[-1].global_risk), 1),
        "events": len(run.timeline),
        "countries": len(
            {country.code for country in run.country_agents if country.risk_score >= 45}
            | {cell.country_code for cell in run.risk_heatmap if cell.risk >= 45}
        ),
    }
    findings = []
    evaluated = 0
    for key, expected in checks.items():
        if key not in by_key:
            continue
        evaluated += 1
        actual = by_key[key].get("value")
        numeric_actual = float(actual) if isinstance(actual, (int, float)) else actual
        if numeric_actual != expected:
            findings.append(_finding(
                rule_id,
                category="schema",
                status="failed",
                severity="error",
                subject_type="lifecycle_kpi",
                subject_id=key,
                message_zh=f"KPI {key} 与确定性明细复算结果不一致。",
                expected=expected,
                actual=actual,
                evidence_refs=[f"ui_state.kpis:{key}", "timeline", "country_agents"],
                suggested_action="修正 UI projection，不能覆盖确定性明细。",
            ))
    if not evaluated:
        return RuleEvaluation(rule_id, False, (_not_evaluated(rule_id, "schema", "ui_projection", "kpis", "没有可识别的可复算 KPI。"),))
    return RuleEvaluation(rule_id, True, tuple(findings))


def evidence_descriptions(run: WarRoomRun) -> RuleEvaluation:
    rule_id = "CONSISTENCY.EVIDENCE_DESCRIPTIONS.V1"
    if not run.impact_graph.edges:
        return RuleEvaluation(rule_id, False, (_not_evaluated(rule_id, "evidence", "impact_graph", "edges", "没有因果边，无法检查机制说明。"),))
    findings = []
    for index, edge in enumerate(run.impact_graph.edges):
        if not str(edge.get("mechanism") or "").strip() or not str(edge.get("explanation") or "").strip():
            findings.append(_finding(
                rule_id,
                category="evidence",
                status="warning",
                severity="warning",
                subject_type="graph_edge",
                subject_id=f"edge:{index}",
                message_zh="因果边缺少机制或解释文本。",
                expected="non-empty mechanism and explanation",
                actual={"mechanism": edge.get("mechanism"), "explanation": edge.get("explanation")},
                evidence_refs=[f"impact_graph.edges:{index}"],
                suggested_action="补充可审计的因果机制和解释。",
            ))
    return RuleEvaluation(rule_id, True, tuple(findings))


def structured_evidence_references(run: WarRoomRun) -> RuleEvaluation:
    rule_id = "CONSISTENCY.STRUCTURED_EVIDENCE_REFERENCES.V1"
    return RuleEvaluation(rule_id, False, (_not_evaluated(
        rule_id,
        "evidence",
        "war_room_result",
        "evidence_refs",
        "V0.8 确定性结果尚未提供结构化证据引用，因此该项未评估。",
    ),))


def capability_constraints(run: WarRoomRun) -> RuleEvaluation:
    rule_id = "CONSISTENCY.CAPABILITY_ACTION_CONSTRAINT.V1"
    return RuleEvaluation(rule_id, False, (_not_evaluated(
        rule_id,
        "capability",
        "agent_action",
        "none",
        "当前运行没有真实 Agent Action Proposal，国家能力约束未评估。",
    ),))


def resource_constraints(run: WarRoomRun) -> RuleEvaluation:
    rule_id = "CONSISTENCY.RESOURCE_BUDGET_CONSTRAINT.V1"
    return RuleEvaluation(rule_id, False, (_not_evaluated(
        rule_id,
        "resource",
        "agent_action",
        "none",
        "当前运行没有资源预算合同，资源约束未评估。",
    ),))


def _not_evaluated(rule_id: str, category: str, subject_type: str, subject_id: str, message: str) -> ConsistencyFinding:
    return _finding(
        rule_id,
        category=category,
        status="not_evaluated",
        severity="info",
        subject_type=subject_type,
        subject_id=subject_id,
        message_zh=message,
        expected="structured input available",
        actual="unavailable",
        suggested_action="补充结构化输入后再执行该规则；不得用推测数据替代。",
    )


RULES: tuple[Rule, ...] = (
    numeric_bounds,
    referential_integrity,
    timeline_integrity,
    event_entity_references,
    kpi_recomputability,
    evidence_descriptions,
    structured_evidence_references,
    capability_constraints,
    resource_constraints,
)
