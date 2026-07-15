# Agent Security Corpus

安全回归 corpus 的每个样本都必须明确预期结果：拒绝、needs_revision、not_evaluated 或脱敏后记录。

覆盖类别：

- Prompt injection：要求忽略系统约束或重写数值权威。
- Authority escalation：在 proposal parameters 深层写入 `risk_score`、`global_risk`、`supply_chain_pressure` 等禁止字段。
- Unknown entity：引用不在 deterministic entity index 的国家、链路或事件。
- Fake evidence：引用不存在的 evidence/artifact ref。
- Budget overflow：超过 actor/turn action budget。
- Output abuse：未知 action 参数、超长 justification、超长 provider 输出和非法 JSON。

处理规则：模型输出先过 Pydantic Action Contract，再过 capability/resource/causal/evidence 一致性评估。确定性数值字段永不由 Agent 写入；日志和事件 payload 统一脱敏。
