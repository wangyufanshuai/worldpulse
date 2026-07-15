# WorldPulse 受控 Agent Runtime

## 执行边界

Agent Runtime 位于确定性 baseline 之后、一致性评估之前。它没有数据库写入工具、Shell、网络写入工具或代码执行工具。Runtime 的唯一业务输出是经过 `AgentActionProposal` Pydantic 合同验证的提案列表。

默认 provider 为 `mock`。真实 provider 仅允许 `siliconflow` 和 `deepseek`，API Key 只从既有环境变量读取。未配置 provider 时按配置降级到 Mock 或跳过 Agent 阶段，确定性 baseline 始终保留。

## 预算与隔离

`AgentRuntimeConfig` 固定限制：

- turn 数量
- Agent 数量
- 单次调用超时
- 调用次数
- token 估算预算
- 输入与输出字符数
- provider allowlist
- fallback 模式

Runtime 在每个 turn 和每次 Agent 调用之前读取 lifecycle pause/cancel 状态；控制请求在当前 provider 调用返回或超时后生效，不会继续启动下一次调用。

每个角色独立调用、独立解析、独立审计。一个角色超时、输出非法或 provider 失败不会撤销已经完成的确定性结果，也不会阻塞其他角色。

## Prompt 与不可信数据

场景、国家、时间线和证据文本统一放入 `<UNTRUSTED_WORLD_STATE>` 数据边界。系统提示明确禁止执行数据字段中的指令，并禁止输出确定性数值字段。Provider 输出只能包含 Action Contract 允许的七个字段，run、turn、actor 和逻辑时间由 Runtime 注入，不能由模型覆盖。

## 调用审计

`agent_runtime_audit` artifact 保存：

- provider / model / mode
- 结构化输出、temperature、timeout 和工具 allowlist 等模型参数
- role 与 prompt version
- prompt hash / response hash
- 输入输出字符数
- token 估算
- 状态、耗时、错误码
- proposal 与 runtime hash

不保存：

- API Key
- Authorization header
- 原始 system/user prompt
- 原始模型响应文本

错误文本在持久化前执行 secret redaction。token 数、耗时和 invocation 元数据不参与确定性结果 hash。

## 角色注册

V0.10 注册国家政策、外交协商、联盟协调、舆论传播和行动解释五类角色。行动解释角色没有 action allowlist，因此不产生世界状态提案；它将在产品层只解释已经保存的动作。
