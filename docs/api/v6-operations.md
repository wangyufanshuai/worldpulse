# WorldPulse V6 Operations API

V6 是增量命名空间；v1-v5 URL、字段和状态保持兼容。认证开启时，除 `/api/health`、`/api/ready`、`/api/version` 和登录外仍要求服务端 Session；所有写操作要求 CSRF。

```text
GET  /api/ready
GET  /api/v6/platform/readiness
GET  /api/v6/workers
POST /api/v6/workers/{worker_id}/drain
GET  /api/v6/organizations/{organization_id}/operations
PUT  /api/v6/organizations/{organization_id}/quota
```

## Readiness

`PlatformReadiness` 返回：

- `status`: `ready | degraded | not_ready`
- `database_backend`: `sqlite | postgresql`
- `schema_ok`、`rule_pack_ok`
- `worker_requirement_enabled`、`worker_requirement_met`
- 两类新鲜 worker 数、两类排队任务数、原因代码和检查时间

`/api/ready` 在 `not_ready` 时返回 503，其余返回 200。`/api/v6/platform/readiness` 是认证后的详细合同端点。

## Worker

`WorkerNode` 状态为 `starting | ready | busy | draining | stopped | failed | stale`。`stale` 是根据 `lease_expires_at` 计算的只读投影。Drain 返回 409 表示目标已停止、失败或过期；排空不会中断当前阶段，只阻止下一次领取。

## Organization Operations

摘要同时返回 `quota`、`usage`、`workers` 和 `readiness`。配额字段固定为：

- `max_projects`
- `max_active_runs`
- `max_ingestion_jobs_per_day`（滚动 24 小时）
- `max_evidence_snapshots`

超额创建返回 429。降低配额可以低于当前用量，但只会冻结后续创建，不删除已有资源。配额状态冲突或组织权限不足分别遵循现有 409/403 语义。
