# WorldPulse 全球综合风险指数

当前开发版本为 `1.12.0-dev`，V1.12 历史基准发布链与 V2.0 架构计划分别受治理。V2.0 采用兼容旧合同的模块化单体路线，详见 [`V2.0 Architecture Program`](docs/architecture/v2.0-architecture-program.md)、[`ADR-0001`](docs/architecture/adr/0001-v2-modular-monolith.md) 和 [`Phase 0 Baseline Runbook`](docs/runbooks/v2.0-phase0-baseline.md)。

V1.10.0-rc1 新增默认关闭的持续情报链路：公开 RSS/Atom/JSON Feed 经 SSRF 门禁、版本检测和不可变 Watchlist 匹配后，只能固化为受治理材料和待核验场景候选；它不会自动创建 Draft、启动推演或改写权威数值。详见 [`V1.10 架构`](docs/architecture/v1.10-continuous-intelligence.md)、[`V9 API`](docs/api/v9-continuous-intelligence.md) 和 [`V1.10 运行手册`](docs/runbooks/v1.10-continuous-intelligence.md)。

V1.9.0-rc1 增加证据驱动场景编译：PDF/TXT/Markdown/CSV 通过内容寻址上传、版本化抽取和确定性候选生成后，由 Analyst 整理、Reviewer/Admin 双人审批并冻结 Evidence Pack，才能编译为 deterministic、hybrid 或 negotiation 运行。材料与可选 LLM 只能提供带定位的定性候选，不能写入风险、供应链压力或国家/链路 override。详见 [`V1.9 架构`](docs/architecture/v1.9-scenario-compiler.md)、[`V8 API`](docs/api/v8-scenario-compiler.md) 和 [`V1.9 运行手册`](docs/runbooks/v1.9-scenario-compiler.md)。

V1.8.0-rc1 新增受控多轮外交博弈：12 个 Agent 在 6 个 Tick 内生成结构化提案、反提案、接受与公开声明；一致性评估器、承诺账本和确定性适配器决定哪些行动可以进入下一轮世界状态。风险、供应链压力和舆论数值仍只由确定性引擎生成。详见 [`V1.8 架构`](docs/architecture/v1.8-negotiation-runtime.md)、[`V7 API`](docs/api/v7-negotiation.md) 和 [`V1.8 运行手册`](docs/runbooks/v1.8-negotiation.md)。

V1.7.0-rc1 在 V1.6 PostgreSQL 生产基线上增加运维控制平面：生命周期与采集 worker 具备持久化注册、心跳、状态和安全排空；`/api/ready` 区分进程存活与平台就绪；组织项目、活跃运行、24 小时采集任务和证据快照受后端配额约束。War Room 新增中文“运维中心”。这些能力只治理执行容量，不改变确定性风险、供应链压力、Run Diff 或 Replay Pack。详见 [`V1.7 架构`](docs/architecture/v1.7-operations-control-plane.md)、[`V6 API`](docs/api/v6-operations.md) 与 [`V1.7 运维手册`](docs/runbooks/v1.7-operations.md)。

V1.6.0-rc1 完成 PostgreSQL 生产化收口：真实 PostgreSQL 迁移、并发 worker、确定性结果投影和 SQLite 全量转移均进入自动门禁；新增组织切换、SSE 组织上下文与 V4 证据资源隔离。SQLite 仍是零配置开发默认，团队部署推荐使用 PostgreSQL Compose overlay。详见 [`V1.6 PostgreSQL 生产手册`](docs/runbooks/v1.6-postgresql-production.md)。

V1.5.0-rc1 将 WorldPulse 推进到组织级运行与受控数据接入：组织成员和项目作用域由后端强制校验，版本化连接器与采集策略在写入 Evidence Registry 前执行许可、大小、类别和时间截点门禁；SQLite 继续可用，同时新增 PostgreSQL 运行时与编号迁移适配。确定性风险、供应链数值、Run Diff、Replay Pack 以及 V1–V4 合同保持不变。详见 [`V1.5 架构`](docs/architecture/v1.5-organization-ingestion.md)、[`V5 API`](docs/api/v5-organization-ingestion.md) 和 [`PostgreSQL 迁移手册`](docs/runbooks/v1.5-postgresql-migration.md)。

WorldPulse 是一个基于 FastAPI 的全球多源风险监测与预测看板。它不是“预测未来一切”的神秘模型，而是一个可扩展的数据工程项目：

V1.3.0-rc1 将 V1.2 受控混合引擎升级为面向小型内部团队的可信决策平台：确定性规则引擎继续独占风险与供应链数值权威；本地账户、RBAC、不可变 Rule Pack、30 案例校准生命周期、append-only 人工复核和可信度中心共同约束规则晋升与报告发布。Replay Pack 与离线复盘仍不会重新调用 LLM。

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
pip install -r requirements.lock
python -m app.manage migrate
uvicorn app.main:app --reload --port 8010
```

生命周期任务需要独立 worker：

```powershell
python -m app.workers.run_worker
```

受控数据接入也支持独立 worker：

```powershell
python -m app.workers.ingestion_worker
```

前端开发模式：

```powershell
npm --prefix frontend install
npm --prefix frontend run dev
```

启用本地账户与 RBAC：

```powershell
$env:WORLDPULSE_AUTH_MODE="local"
python -m app.manage create-admin --username admin
uvicorn app.main:app --port 8010
```

首个管理员只能通过 CLI 创建；production 必须启用 `WORLDPULSE_AUTH_MODE=local`，并显式配置 `WORLDPULSE_CORS_ORIGINS`。密码使用 Argon2id，数据库只保存 Session/CSRF Hash。

本地发布与数据库运维：

```powershell
python scripts/local_health.py
python scripts/verify_database.py --database data/worldpulse.db
python scripts/backup_database.py --source data/worldpulse.db --output data/backups/worldpulse.backup.db
python scripts/export_openapi.py
python -m app.manage migrate verify
python -m app.manage db-readiness --output docs/db/postgresql-v15-schema.sql
python scripts/verify_release_artifacts.py
```

`AI_PROVIDER` 服务于旧版解释/报告层；`AGENT_PROVIDER` 只服务于受控生命周期 Agent Runtime。两者都不能修改确定性风险和供应链数值，开发环境推荐 `AGENT_PROVIDER=mock`。

打开：

```text
http://127.0.0.1:8010
```

## API

V1.1 可信运行文档：[`lifecycle-step-contract.md`](docs/architecture/lifecycle-step-contract.md)、[`checkpoint-and-recovery.md`](docs/architecture/checkpoint-and-recovery.md)、[`idempotent-run-creation.md`](docs/api/idempotent-run-creation.md)。Golden Scenario、故障注入、备份和事故响应见 `docs/testing` 与 `docs/runbooks`。

V2 生命周期 API 参见 [`docs/api/v2-run-lifecycle.md`](docs/api/v2-run-lifecycle.md)，混合引擎边界参见 [`docs/architecture/v1-hybrid-engine.md`](docs/architecture/v1-hybrid-engine.md)。

V3 可信治理接口包含 `/api/v3/auth`、`/api/v3/rule-packs`、`/api/v3/calibration`、`/api/v3/reviews` 与项目 `trust-summary`。架构与运维说明见 [`v1.3-trust-governance.md`](docs/architecture/v1.3-trust-governance.md) 和 [`v1.3-operations.md`](docs/runbooks/v1.3-operations.md)。

V4 Evidence Registry 见 [`v4-evidence-registry.md`](docs/api/v4-evidence-registry.md)。V5 在 `/api/v5/organizations` 下提供组织成员、组织项目、采集策略、连接器、采集任务和审计事件。选择非默认组织时使用 `X-WorldPulse-Org`；服务端仍是权限与资源作用域的唯一权威。

V6 提供平台 readiness、worker 注册视图/安全排空和组织配额/用量摘要。`GET /api/health` 只证明 HTTP 进程存活；部署健康门禁应使用 `GET /api/ready`。

- `GET /api/health`：健康检查
- `GET /api/ready`：数据库、Schema、Rule Pack 与可选 worker 容量就绪检查
- `GET /api/version`：应用与 API 合同版本
- `GET /api/v2/lifecycle/health`：生命周期队列、阶段耗时、恢复和制品完整性摘要
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
