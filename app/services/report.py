from __future__ import annotations

from datetime import date
from pathlib import Path

from app.core.models import CompositeRisk
from app.services.risk_engine import build_latest_risk


def render_report(risk: CompositeRisk | None = None) -> str:
    risk = risk or build_latest_risk()
    lines = [
        "# WorldPulse 全球综合风险报告",
        "",
        f"- 日期：{risk.date}",
        f"- 综合风险指数：{risk.score:.2f}/100",
        f"- 风险等级：{risk.display_level}",
        f"- 当前趋势：{risk.display_trend}",
        f"- 未来30天风险上升概率：{risk.forecast_30d:.1%}",
        f"- 预测结论：{risk.display_forecast_label}",
        "",
        "## 摘要",
        "",
        risk.summary,
        "",
        "## 分项风险",
        "",
        "| 分项 | 得分 | 权重 | 趋势 | 数据源 |",
        "|---|---:|---:|---|---|",
    ]
    for component in risk.components:
        lines.append(
            f"| {component.display_name} | {component.score:.2f} | {component.weight:.2f} | {component.display_trend} | {component.source} |"
        )
    lines.extend(["", "## 当前驱动因素", ""])
    for component in risk.components:
        lines.append(f"### {component.display_name}")
        lines.extend(f"- {driver}" for driver in component.drivers)
        lines.append("")
    lines.extend(
        [
            "## 方法说明",
            "",
            "本系统将金融市场、气候、地缘与政策、生态与粮食、宏观流动性五类指标标准化后合成为0-100的综合风险指数。",
            "当公共数据源暂时不可用时，系统会退回可复现的确定性演示数据，以保证管线可测试。",
            "未来30天预测是基线逻辑模型，用于研究和预警，不是生产级预测模型，也不是行动指令。",
        ]
    )
    return "\n".join(lines) + "\n"


def export_report() -> tuple[Path, str]:
    markdown = render_report()
    output_dir = Path("data/reports")
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"worldpulse_report_{date.today().isoformat()}.md"
    path.write_text(markdown, encoding="utf-8")
    return path, markdown
