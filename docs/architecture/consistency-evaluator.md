# WorldPulse 一致性评估器

## 定位

V0.8 的一致性评估器运行在确定性 War Room 计算完成之后、报告投影之前。它是只读 Shadow Mode：读取 `WarRoomRun`，生成版本化审计报告，但不修改风险值、供应链压力、时间线、因果图或项目持久化结果。

```text
WarRoomScenarioRequest
  -> deterministic run
  -> WarRoomRun (authoritative numeric result)
  -> consistency evaluator (read-only)
  -> consistency_audit artifact
  -> v1 research_run projection
```

## 合同与稳定性

`ConsistencyAuditReport` 包含：

- `schema_version` 与 `evaluator_version`
- `overall_status`: `passed | warning | failed | not_evaluated`
- 稳定排序的 `findings`
- 已评估与跳过的规则数量
- `deterministic_result_hash`
- `audit_hash`
- 运行 ID 与创建时间

`deterministic_result_hash` 使用规范化的完整 `WarRoomRun` JSON。`audit_hash` 不包含 `run_id` 和 `created_at`，因此相同确定性输入跨运行产生相同审计 hash。生命周期 artifact 自身仍保留运行身份和创建时间。

## V0.8 规则

| 规则 | 结果来源 | 数据缺失行为 |
| --- | --- | --- |
| 数值范围 | 国家、供应链、时间线、热力图、图谱、规则决策 | 无字段时 `not_evaluated` |
| 引用完整性 | 图节点/边、供应链国家、规则决策国家 | 发现悬空引用时 `failed` |
| 时间一致性 | timeline day 与 scenario duration | 无时间线时 `not_evaluated` |
| 事件实体引用 | `ui_state.timeline_events` | 无事件投影时 `not_evaluated` |
| KPI 可复算 | global risk、event count、affected countries | 无已知 KPI 时 `not_evaluated` |
| 因果说明 | graph edge mechanism/explanation | 无因果边时 `not_evaluated` |
| 结构化证据 | 预留给后续 evidence contract | V0.8 明确 `not_evaluated` |
| 国家能力 | 预留给 Agent Action Contract | 无真实 action 时 `not_evaluated` |
| 资源预算 | 预留给 Agent Action Contract | 无预算合同时 `not_evaluated` |

`not_evaluated` 不等于通过。只要存在可执行规则且部分规则因缺少结构化输入跳过，整体状态为 `warning`；没有任何规则可执行时才是 `not_evaluated`。

## 生命周期与 API

worker 在 `consistency_audit` 阶段：

1. 对内存中的确定性 `WarRoomRun` 执行评估。
2. 在现有 `run_artifacts` 写入 `artifact_type=consistency_audit`。
3. 在现有 `run_events` 写入带 `audit_hash` 的 `CONSISTENCY` 事件。
4. 继续使用公共 `persist_war_room_result` façade 投影 v1 结果。

`GET /api/v2/runs/{run_id}/audit` 在原有 `run/events/artifacts` 之外追加可选的 `consistency_audit`。排队中或历史无审计任务返回 `null`，不会推测通过率。

## 明确边界

- 不调用 LLM。
- 不运行或伪造 Agent。
- 不自动修正 finding。
- 不新增数据库表。
- 不改变 v1/v2 URL、生命周期状态和阶段枚举。
- `agent_decisions` 仍是确定性规则投影，不计为真实 Agent Action Proposal。
