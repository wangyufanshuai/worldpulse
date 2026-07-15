# WorldPulse Agent Action Contract

## 权限边界

Agent 只能产生结构化 `AgentActionProposal`。提案不是世界状态，也不是风险计算结果。以下字段在提案的任意层级都被禁止：

- `risk_score`
- `global_risk`
- `supply_chain_pressure`
- `pressure_score`
- `risk_delta`
- `numeric_weight`
- `deterministic_modifier`

提案只有通过一致性评估后，才可能在后续版本被确定性 Action Adapter 转换；V0.9 不进行任何数值转换。

## 支持动作

V0.9 固定支持：

- `diplomatic_signal`
- `alliance_request`
- `alliance_response`
- `sanction_proposal`
- `trade_reroute_request`
- `public_narrative`
- `humanitarian_offer`
- `deescalation_offer`
- `intelligence_request`

每个动作使用独立的 Pydantic parameters 模型并禁止额外字段。未知动作、缺少目标、缺少证据或包含权威数值字段会在合同解析阶段被拒绝。

## Mock Agent

`mock-deterministic` provider 从只读 `WarRoomRun` 生成四类提案：国家政策、外交、联盟协调和舆论叙事。Mock 的用途是测试合同和审计链路，不模拟真实模型能力。

稳定性规则：

- `proposal_id` 由 seed、turn、actor、action、targets、parameters、依据、方向和置信度生成。
- `run_id` 不参与 proposal ID 或 batch hash。
- `created_at` 使用明确的逻辑时钟；真实写入时间由 `run_artifacts.created_at` 记录。
- 同一确定性结果、seed 和 turn 产生相同 proposal IDs 与 batch hash。

## 仿真能力信封

V0.9 使用显式 `AgentConstraintContext`：

- actor 可提交的 action allowlist
- actor 每回合动作预算
- 确定性实体索引
- 可解析证据引用索引

这是系统配置的仿真准入边界，不是对现实国家能力或资源储备的断言。没有显式能力信封或预算时，评估器返回 `not_evaluated`，不会根据常识补全。

## 审计决策

每个 proposal 产生版本化决策：

- `accepted`
- `rejected`
- `needs_revision`
- `not_evaluated`

决策包含规则 findings、证据引用、中文解释和稳定 audit hash。V0.9 的 `accepted` 仅表示合同准入通过，不表示动作已经影响确定性结果。
