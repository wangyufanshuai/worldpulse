from __future__ import annotations

from app.core.models import CausalChain, CausalEvent, CausalGraphEdge, CausalGraphNode, MarketImpact


EVENT_CHAINS = {
    "conflict": {
        "nodes": [
            ("event", "地区冲突升级", "event"),
            ("oil", "原油风险溢价", "commodity"),
            ("airlines", "航空利润压力", "sector"),
            ("defense", "军工需求预期", "sector"),
            ("risk", "全球风险偏好", "macro"),
        ],
        "edges": [
            ("event", "oil", "供应中断预期", 0.86, "冲突升级会抬高能源供应风险和运输风险。"),
            ("oil", "airlines", "燃油成本上升", 0.72, "油价上行会压缩航空和运输链利润率。"),
            ("event", "defense", "安全支出预期", 0.68, "冲突和安全压力通常会提升军工订单预期。"),
            ("event", "risk", "避险情绪上升", 0.74, "冲突信号会降低风险偏好并推高波动率。"),
        ],
    },
    "sanctions": {
        "nodes": [("event", "制裁与出口管制", "event"), ("trade", "贸易链摩擦", "macro"), ("dollar", "美元融资压力", "fx"), ("risk", "市场风险溢价", "macro")],
        "edges": [
            ("event", "trade", "供应链重定价", 0.78, "制裁会改变贸易流向和关键商品可得性。"),
            ("event", "dollar", "结算与融资约束", 0.62, "制裁常通过美元结算和融资渠道外溢。"),
            ("trade", "risk", "利润与通胀不确定性", 0.65, "供应链调整会影响企业利润和通胀预期。"),
        ],
    },
    "energy": {
        "nodes": [("event", "能源供需冲击", "event"), ("oil", "WTI 原油", "commodity"), ("inflation", "通胀预期", "macro"), ("nasdaq", "成长股估值", "asset")],
        "edges": [
            ("event", "oil", "现货与预期共振", 0.82, "能源新闻会影响原油价格和库存预期。"),
            ("oil", "inflation", "成本推动", 0.70, "能源价格上行会推高通胀压力。"),
            ("inflation", "nasdaq", "折现率压力", 0.58, "通胀预期可能带来利率上行和成长股估值压力。"),
        ],
    },
    "food": {
        "nodes": [("event", "粮食供给压力", "event"), ("food", "粮食价格", "commodity"), ("em", "新兴市场民生压力", "macro"), ("risk", "社会稳定风险", "macro")],
        "edges": [
            ("event", "food", "供给扰动", 0.76, "极端天气和冲突可能影响粮食出口与库存。"),
            ("food", "em", "进口成本上升", 0.66, "粮食进口经济体对价格冲击更敏感。"),
            ("em", "risk", "政策与社会压力", 0.58, "民生压力会向政策和市场风险扩散。"),
        ],
    },
    "rates": {
        "nodes": [("event", "央行与利率信号", "event"), ("rates", "利率路径", "macro"), ("dollar", "美元指数压力", "fx"), ("sp500", "权益估值", "asset")],
        "edges": [
            ("event", "rates", "政策预期重定价", 0.82, "央行信号会影响收益率曲线和风险资产折现率。"),
            ("rates", "dollar", "利差驱动", 0.62, "更高利率会提高美元资产吸引力。"),
            ("rates", "sp500", "估值压缩", 0.64, "利率上行通常压低权益估值倍数。"),
        ],
    },
    "trade": {
        "nodes": [("event", "贸易摩擦", "event"), ("supply", "供应链成本", "macro"), ("nasdaq", "科技硬件链", "asset"), ("risk", "盈利不确定性", "macro")],
        "edges": [
            ("event", "supply", "关税与限制", 0.80, "贸易壁垒会增加跨境供应链成本。"),
            ("supply", "nasdaq", "硬件利润率压力", 0.56, "科技硬件和半导体链条对贸易限制敏感。"),
            ("supply", "risk", "盈利能见度下降", 0.63, "供应链重定价会降低盈利可预测性。"),
        ],
    },
    "climate": {
        "nodes": [("event", "气候灾害", "event"), ("food", "农产品供给", "commodity"), ("insurance", "保险损失", "sector"), ("risk", "经济活动扰动", "macro")],
        "edges": [
            ("event", "food", "产量风险", 0.66, "干旱、洪水和热浪会影响农产品供给。"),
            ("event", "insurance", "赔付压力", 0.61, "极端天气会提高保险和再保险损失。"),
            ("event", "risk", "区域活动中断", 0.54, "灾害会影响物流、产出和区域需求。"),
        ],
    },
}

IMPACT_RULES = {
    "conflict": [("oil", "WTI 原油", "up", 2.4), ("gold", "黄金", "up", 1.1), ("sp500", "标普500", "down", -0.8), ("nasdaq", "纳斯达克100", "down", -1.0), ("vix", "VIX 波动率", "up", 4.0)],
    "sanctions": [("oil", "WTI 原油", "up", 1.4), ("dollar", "美元压力", "up", 1.2), ("sp500", "标普500", "down", -0.5), ("nasdaq", "纳斯达克100", "down", -0.7)],
    "energy": [("oil", "WTI 原油", "up", 2.8), ("sp500", "标普500", "down", -0.6), ("nasdaq", "纳斯达克100", "down", -0.8), ("gold", "黄金", "up", 0.5)],
    "food": [("gold", "黄金", "up", 0.4), ("sp500", "标普500", "down", -0.3), ("dollar", "美元压力", "up", 0.5)],
    "rates": [("dollar", "美元压力", "up", 1.0), ("sp500", "标普500", "down", -0.9), ("nasdaq", "纳斯达克100", "down", -1.3), ("gold", "黄金", "down", -0.4)],
    "trade": [("nasdaq", "纳斯达克100", "down", -0.9), ("sp500", "标普500", "down", -0.5), ("dollar", "美元压力", "up", 0.4)],
    "climate": [("gold", "黄金", "up", 0.3), ("sp500", "标普500", "down", -0.2), ("oil", "WTI 原油", "up", 0.4)],
}


def build_causal_chain(event: CausalEvent) -> CausalChain:
    spec = EVENT_CHAINS.get(event.event_type, EVENT_CHAINS["conflict"])
    nodes = [CausalGraphNode(id=node_id, label=label, kind=kind, score=_node_score(event, node_id)) for node_id, label, kind in spec["nodes"]]
    edges = [
        CausalGraphEdge(
            source=source,
            target=target,
            relation=relation,
            weight=weight,
            confidence=round(min(95, event.confidence * 0.55 + weight * 45), 1),
            explanation=explanation,
        )
        for source, target, relation, weight, explanation in spec["edges"]
    ]
    return CausalChain(
        event_type=event.event_type,
        title=f"{event.name}因果链",
        nodes=nodes,
        edges=edges,
        confidence=round(min(92, event.confidence * 0.62 + sum(edge.weight for edge in edges) / max(len(edges), 1) * 38), 1),
        explanation=_chain_explanation(event),
    )


def estimate_market_impacts(event: CausalEvent, backtest_confidence: float = 50) -> list[MarketImpact]:
    impacts = []
    scale = 0.55 + event.intensity / 100
    confidence = min(92, event.confidence * 0.55 + backtest_confidence * 0.45)
    for asset_key, asset_name, direction, base_return in IMPACT_RULES.get(event.event_type, IMPACT_RULES["conflict"]):
        expected = base_return * scale
        impacts.append(
            MarketImpact(
                asset_key=asset_key,
                asset_name=asset_name,
                direction=direction,
                expected_return_pct=round(expected, 2),
                confidence=round(confidence, 1),
                rationale=f"{event.name}通过既定因果链影响{asset_name}，方向为{_direction_label(direction)}。",
            )
        )
    return impacts


def _node_score(event: CausalEvent, node_id: str) -> float:
    base = event.intensity if node_id == "event" else event.intensity * 0.72
    return round(min(100, max(0, base)), 1)


def _chain_explanation(event: CausalEvent) -> str:
    examples = {
        "conflict": "冲突升级可能先影响能源和避险预期，再传导至航空、军工和宽基风险偏好。",
        "sanctions": "制裁会通过贸易链、融资链和供应链重定价扩散。",
        "energy": "能源冲击主要通过油价、通胀预期和利率路径影响风险资产。",
        "food": "粮食压力会通过民生成本、进口压力和政策反应影响宏观稳定度。",
        "rates": "利率信号会通过折现率、美元和信用条件影响权益与商品。",
        "trade": "贸易摩擦会通过供应链成本和盈利能见度影响科技与宽基资产。",
        "climate": "气候灾害会通过粮食、保险损失和区域经济活动形成冲击。",
    }
    return examples.get(event.event_type, examples["conflict"])


def _direction_label(direction: str) -> str:
    return {"up": "上行", "down": "下行", "mixed": "分化"}.get(direction, direction)
