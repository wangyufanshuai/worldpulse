# Idempotent Run Creation

`POST /api/v2/projects/{project_id}/runs` 支持可选 `Idempotency-Key` 请求头。

- 同一项目、同一 key、同一规范化请求 hash：返回原 job，不创建新事件或 job。
- 同一项目、同一 key、不同请求 hash：返回 `409`。
- 不提供 key：保持原有创建语义。

请求 hash 包含 engine mode、规范化 scenario、seed、parent_run_id 和 max_attempts。key 仅接受可打印 ASCII，长度不超过 200。该合同是追加能力，不改变现有 v1 API 或 v2 状态枚举。
