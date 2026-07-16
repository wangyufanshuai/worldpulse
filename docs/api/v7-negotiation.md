# WorldPulse API Contract v7

V7 只增加协商运行的只读查询；运行仍通过 v2 生命周期创建：

```http
POST /api/v2/projects/{project_id}/runs
Content-Type: application/json

{"engine_mode":"negotiation","scenario":{"scenario_key":"strait_blockade_30d"},"seed":42}
```

查询接口：

```text
GET /api/v7/agent-packs
GET /api/v7/runs/{run_id}/negotiation
GET /api/v7/runs/{run_id}/negotiation/rounds
GET /api/v7/runs/{run_id}/negotiation/messages?after_seq=0&tick=1
GET /api/v7/runs/{run_id}/negotiation/commitments
```

实时状态继续使用 v2 SSE；每个 Tick 产生 `AGENT`、`CONSISTENCY`/审计和 `SNAPSHOT` 事件。V7 不提供消息或承诺写入接口。v1–v6 URL、字段含义和生命周期状态不变。
