# Lifecycle Incident Response

1. 查看 `GET /api/v2/lifecycle/health`，确认 queued/running/stale/failed、阶段 P50/P95 和 artifact integrity failures。
2. 查看具体 run 的 `/status`、`/events`、`/steps`、`/audit`，定位最后一个 verified checkpoint 和 attempt。
3. 若 worker lease stale，运行本地 worker；系统会在边界回收并恢复。不要手工删除 run_jobs、run_steps 或 artifacts。
4. 若 artifact integrity 失败，停止 Replay/报告导出，保留数据库副本并从备份恢复或重新运行；禁止绕过 hash 校验。
5. 若达到 max attempts，记录 terminal_reason，修复输入/规则或外部 provider 后通过 retry 创建 child job。

事故记录不得包含 API key、原始 prompt/response 或用户数据库文件。完成后运行全量 pytest、前端 build、E2E 和 `git diff --check`。
