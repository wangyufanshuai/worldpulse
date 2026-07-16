# V5 Organization and Ingestion API

认证开启时，所有写请求继续要求 HttpOnly Session 与 `X-CSRF-Token`。非默认组织可通过 `X-WorldPulse-Org: org_...` 选择；URL 中显式包含 organization ID 的 v5 接口仍会再次校验成员身份和组织角色。

## Organizations and projects

```text
GET  /api/v5/organizations
GET  /api/v5/organizations/current
POST /api/v5/organizations
GET  /api/v5/organizations/{organization_id}/members
POST /api/v5/organizations/{organization_id}/members
GET  /api/v5/organizations/{organization_id}/projects
POST /api/v5/organizations/{organization_id}/projects
```

全局 `admin` 才能创建 organization。组织 `owner/admin` 管理成员，`owner/admin/analyst` 创建组织项目；所有活动成员可读。v1 项目模型没有增加强制字段。

## Policies and connectors

```text
GET  /api/v5/organizations/{organization_id}/ingestion/policies
POST /api/v5/organizations/{organization_id}/ingestion/policies
GET  /api/v5/organizations/{organization_id}/ingestion/connectors
POST /api/v5/organizations/{organization_id}/ingestion/connectors
```

首个 connector 会在默认组织自动建立 `ingestion-policy.v1`。显式策略仅 `owner/admin` 可创建；策略不可原地修改。V1.5 connector type 固定为 `manual_json`。

```json
{
  "name": "能源月报冻结导入",
  "connector_type": "manual_json",
  "source_locator": "manual://energy-monthly",
  "config": {
    "publisher": "Example Publisher",
    "license": "internal-license-2026"
  }
}
```

Secret-like 配置键返回 422，服务端不会保存该配置。

## Ingestion jobs

```text
GET  /api/v5/organizations/{organization_id}/ingestion/jobs
POST /api/v5/organizations/{organization_id}/ingestion/jobs
GET  /api/v5/organizations/{organization_id}/ingestion/jobs/{job_id}
GET  /api/v5/organizations/{organization_id}/ingestion/jobs/{job_id}/events?after_seq=0
POST /api/v5/organizations/{organization_id}/ingestion/jobs/{job_id}/execute
POST /api/v5/organizations/{organization_id}/ingestion/jobs/{job_id}/cancel
POST /api/v5/organizations/{organization_id}/ingestion/jobs/{job_id}/retry
GET  /api/v5/organizations/{organization_id}/ingestion/summary
```

```json
{
  "connector_id": "con_...",
  "project_id": "proj_...",
  "idempotency_key": "energy-2026-07",
  "records": [{
    "external_ref": "ENERGY-2026-07",
    "title": "能源供应压力",
    "category": "energy",
    "content": {"pressure": 0.72, "direction": "up"},
    "content_text": "能源供应压力上行",
    "observed_at": "2026-07-10",
    "cutoff_at": "2026-07-16"
  }]
}
```

状态为 `queued/running/cancelling/cancelled/failed/completed`。同一组织内复用相同 idempotency key 和相同 request hash 返回原 job；内容不同返回 409。事件 `seq` 严格单调，`after_seq` 用于增量读取。完成响应包含 `manifest_hash`；每条 accepted record 对应一个不可变 Evidence Snapshot。

错误语义：未登录 401、全局或组织权限不足 403、资源不属于当前组织 404、状态/幂等冲突 409、策略或截点违反 422。
