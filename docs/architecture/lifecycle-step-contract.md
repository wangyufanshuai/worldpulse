# Lifecycle Step Contract

WorldPulse v1.1 将一次 Run 固定为六个版本化阶段：`scenario_compile`、`environment_prepare`、`deterministic_run`、`consistency_audit`、`report_generate`、`replay_archive`。每个阶段写入 `run_steps`，包含 `step_id`、`step_version`、`attempt_id`、输入/输出 hash、状态、时间、耗时、错误码和 artifact refs。

阶段输入必须显式引用前一阶段的 `step_id`、`output_hash` 和 artifact refs。`deterministic_run` 是风险、供应链、时间线、图谱和国家能力结果的唯一数值权威；Agent 提案和一致性审计只能作为后续阶段输入或审计证据。

阶段版本变化不能静默覆盖旧结果。任何规则合同变化都必须升级 `step_version` 与 `rule_set_version`，并新增 Golden Scenario 期望值。

## 合法状态

`running → completed` 或 `running → failed/paused/cancelled`。失败 attempt 不得被当作有效 checkpoint；恢复只读取版本匹配、输入链匹配、输出 hash 匹配且 artifact 完整性通过的连续阶段。

## 证据要求

每个可重放结果必须能沿 `run_steps → run_artifacts → research_runs` 追溯。Replay Pack 读取已验证 artifact，不重新调用 LLM；Run Diff 读取已投影的确定性 v1 run。
