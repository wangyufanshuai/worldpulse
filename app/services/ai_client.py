from __future__ import annotations

import json
import os
from typing import Any

from app.core.models import AIAnalysisResult, EvidenceItem, ScenarioSuggestion, WatchSignal
from app.services.llm_client import LLMMessage, call_llm_json, get_llm_status


def ai_status() -> dict[str, Any]:
    return get_llm_status()


def request_structured_analysis(prompt: str, context: dict[str, Any]) -> AIAnalysisResult:
    schema = _analysis_schema()
    llm_result = call_llm_json(
        [
            LLMMessage(
                role="system",
                content=(
                    "你是 WorldPulse 的金融与地缘局势研判层。"
                    "你只能基于输入 JSON 中的数据、模拟结果、事件摘要和数据质量进行分析。"
                    "不要输出确定性预测，不要给投资、政治或安全行动指令。"
                    "必须输出一个 JSON 对象，字段严格包含 schema 要求的全部字段。"
                ),
            ),
            LLMMessage(
                role="user",
                content=(
                    f"{prompt}\n\n"
                    "输出字段要求：title、summary、key_findings、evidence、uncertainties、watch_signals、scenario_suggestions、disclaimer。"
                    "evidence 必须引用输入中的数据源或指标；watch_signals 必须可观察；scenario_suggestions 必须能映射到现有模拟器 shock_type。"
                    f"\n\n上下文 JSON:\n{json.dumps(context, ensure_ascii=False)}"
                ),
            ),
        ],
        schema_hint={"required": []},
        timeout=int(os.getenv("AI_TIMEOUT_SECONDS", "45")),
    )
    if llm_result.enabled:
        payload = _normalize_ai_payload(json.loads(llm_result.content), context, f"{llm_result.provider}:{llm_result.model}")
        return AIAnalysisResult(**payload)

    result = fallback_analysis(context, mode="disabled")
    if llm_result.error:
        result.uncertainties.append(f"模型网关未返回可用结果：{llm_result.error}")
    return result


def fallback_analysis(context: dict[str, Any], mode: str = "fallback") -> AIAnalysisResult:
    risk = context.get("risk", {}).get("latest", {})
    simulation = context.get("simulation") or {}
    events = context.get("events", {})
    event_topics = events.get("topics", [])[:3]
    countries = simulation.get("countries") or []
    top_country = countries[0] if countries else {}
    catalysts = "、".join(item.get("name", "") for item in event_topics if item.get("name")) or "暂无明显事件主题"
    evidence = [
        EvidenceItem(
            title="风险评分解释",
            source="WorldPulse risk engine",
            value=f"{risk.get('score', '--')}/100",
            interpretation=risk.get("summary", "当前风险总览不可用。"),
        ),
        EvidenceItem(
            title="证据链：事件主题",
            source=events.get("source", "events"),
            value="、".join(f"{item.get('name')}:{item.get('event_count')}" for item in event_topics) or "暂无事件摘要",
            interpretation=f"当前可观察催化因素集中在：{catalysts}。事件数量只代表公开信息热度，不等于严重程度。",
        ),
    ]
    if top_country:
        evidence.append(
            EvidenceItem(
                title="证据链：模拟承压经济体",
                source="WorldPulse simulation",
                value=f"{top_country.get('name', '--')} P50 {top_country.get('p50', '--')}",
                interpretation="模拟结果用于观察政策冲击的相对敏感性，不代表真实未来路径。",
            )
        )
    return AIAnalysisResult(
        enabled=mode != "disabled",
        mode=mode,
        title="WorldPulse AI 局势研判报告",
        summary="当前使用本地规则生成结构化研判。配置硅基流动或 DeepSeek API Key 后，将自动切换为模型生成的结构化报告。",
        key_findings=[
            "核心结论：当前输出是数据解释和情景推演，不是确定性预测。",
            "风险警报：若综合风险、事件主题强度和模拟承压方向同时上升，应提高复盘优先级。",
            "催化因素：重点跟踪冲突、能源、贸易、利率和粮食相关事件主题。",
        ],
        evidence=evidence,
        uncertainties=[
            "公开数据存在延迟、缺失和口径差异。",
            "事件数量不等于事件严重程度，需要结合来源可信度和主题解释。",
            "模拟参数是可解释代理，不代表真实政策反应函数。",
        ],
        watch_signals=[
            WatchSignal(name="冲突事件强度", direction="上升", why_it_matters="冲突信号会影响能源、避险和区域传播链。", current_status="查看事件摘要中的 GDELT/UCDP 信号。"),
            WatchSignal(name="能源价格与进口脆弱性", direction="上升", why_it_matters="能源冲击会放大进口经济体通胀和利率压力。", current_status="查看能源情景和国家 energy_vulnerability。"),
            WatchSignal(name="贸易政策新闻", direction="波动", why_it_matters="关税、制裁、出口管制会沿贸易网络传播。", current_status="查看贸易/制裁主题事件。"),
        ],
        scenario_suggestions=[
            ScenarioSuggestion(name="能源价格冲击复盘", shock_type="energy", target_codes=["EU", "JPN", "KOR", "IND"], rationale="用于检验能源进口经济体的风险弹性。"),
            ScenarioSuggestion(name="关税壁垒升温", shock_type="tariff", target_codes=["CHN", "USA", "EU", "VNM"], rationale="用于观察贸易开放经济体和供应链节点的外溢。"),
        ],
        disclaimer="AI 仅解释数据和情景，不构成投资、政治或安全决策建议。",
    )


def _analysis_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["title", "summary", "key_findings", "evidence", "uncertainties", "watch_signals", "scenario_suggestions", "disclaimer"],
    }


def _normalize_ai_payload(payload: dict[str, Any], context: dict[str, Any], mode: str) -> dict[str, Any]:
    fallback = fallback_analysis(context, mode=mode).model_dump()
    merged = {**fallback, **{key: value for key, value in payload.items() if value not in (None, "", [])}}
    merged["enabled"] = True
    merged["mode"] = mode
    merged["evidence"] = _normalize_list_of_dicts(merged.get("evidence"), fallback["evidence"])
    merged["watch_signals"] = _normalize_list_of_dicts(merged.get("watch_signals"), fallback["watch_signals"])
    merged["scenario_suggestions"] = _normalize_list_of_dicts(merged.get("scenario_suggestions"), fallback["scenario_suggestions"])
    for key in ["key_findings", "uncertainties"]:
        if not isinstance(merged.get(key), list) or not merged[key]:
            merged[key] = fallback[key]
        else:
            merged[key] = [str(item) for item in merged[key]]
    return merged


def _normalize_list_of_dicts(value: Any, fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        return fallback
    clean = [item for item in value if isinstance(item, dict)]
    if not clean:
        return fallback
    normalized = []
    for index, item in enumerate(clean):
        base = fallback[min(index, len(fallback) - 1)] if fallback else {}
        normalized.append({**base, **item})
    return normalized
