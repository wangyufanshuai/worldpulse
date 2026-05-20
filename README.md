# WorldPulse 全球综合风险指数

WorldPulse 是一个基于 FastAPI 的全球多源风险监测与预测看板。它不是“预测未来一切”的神秘模型，而是一个可扩展的数据工程项目：

```text
公开数据源 -> 指标标准化 -> 分项风险 -> 综合指数 -> 30天基线预测 -> 看板/Markdown报告
```

## 当前能力

- 综合风险指数：`0-100`
- 风险等级：低风险 / 中等风险 / 高风险 / 极高风险
- 趋势判断：上升 / 下降 / 稳定
- 30天风险上升概率
- 五类分项风险：
  - 金融市场压力
  - 气候压力
  - 地缘与政策压力
  - 生态与粮食压力
  - 宏观流动性压力
- 中文网页看板
- 中文 Markdown 报告导出
- 生物多样性模块：非洲动物与海洋生物物种分布、样本记录、物种关注分
- 事件复盘模块：选择历史窗口，查看风险结构变化与资产联动
- 指标库、预警中心、数据源健康中心、下载中心

## 当前真实/公开数据源

- FRED CSV：标普500 `SP500`、纳斯达克100 `NASDAQ100`、VIX `VIXCLS`、WTI原油 `DCOILWTICO`
- FRED CSV：高收益信用利差 `BAMLH0A0HYM2`、10年-2年美债利差 `T10Y2Y`、贸易加权美元 `DTWEXBGS`、Henry Hub 天然气 `DHHNGSP`
- World Bank Commodity Price Data：黄金价格、食品指数、农业/谷物/油脂指数、化肥指数
- NASA GISTEMP：全球温度异常
- NOAA GML：Mauna Loa 大气 CO2 月度数据
- NOAA CPC：Oceanic Nino Index，刻画 ENSO 厄尔尼诺/拉尼娜压力
- UCDP GED 25.1：冲突事件数据
- World Uncertainty Index：全球不确定性指数
- GDELT DOC API：作为近实时地缘新闻补充，遇到限流时自动退回 UCDP/演示源
- GBIF Occurrence API：非洲动物公开物种观测记录
- OBIS v3 Occurrence API：海洋生物公开物种观测记录
- yfinance：仅作为金融市场数据的二级兜底

## 快速启动

```powershell
cd E:\xuexi\worldpulse
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8010
```

打开：

```text
http://127.0.0.1:8010
```

## API

- `GET /api/health`：健康检查
- `GET /api/risk/latest`：最新综合风险
- `GET /api/risk/overview`：最新综合风险 + 历史曲线，供看板一次性加载
- `GET /api/risk/history`：历史风险曲线
- `GET /api/risk/analysis`：详细归因分析
- `GET /api/risk/replay`：历史窗口复盘
- `GET /api/workbench/status`：指标库、预警中心、数据源健康
- `GET /api/reports/templates`：报告中心模板
- `GET /api/species/presets`：内置物种列表
- `GET /api/species/profile`：物种分布、样本记录与关注分
- `GET /api/exports/risk-history.csv`：导出历史风险 CSV
- `GET /api/exports/indicators.csv`：导出指标库 CSV
- `GET /api/exports/alerts.csv`：导出预警 CSV
- `GET /api/exports/replay.csv`：导出复盘 CSV
- `GET /api/exports/species-occurrences.csv`：导出物种样本 CSV
- `GET /api/report.md`：中文 Markdown 报告
- `GET /api/report/analysis.md`：详细归因 Markdown 报告
- `GET /api/report/system.md`：系统健康 Markdown 报告
- `POST /api/report/export`：导出中文报告到 `data/reports`

## 重要说明

本项目用于学习、研究和风险监测，不是投资建议，也不是世界局势的确定性预测器。30天预测是基线模型，适合做复盘和方法研究，不适合直接作为交易或决策指令。
