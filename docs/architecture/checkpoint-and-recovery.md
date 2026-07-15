# Checkpoint 与阶段恢复

worker 领取任务时创建新的 `attempt_id`。执行器从六阶段中最后一个经过验证的 completed step 继续，已完成阶段不会再次运行；失败阶段及其之后的阶段才会重试。

验证顺序：

1. step version 与当前合同匹配。
2. `stable_hash(input)` 等于 `input_hash`，并且前置 step 引用连续。
3. `stable_hash(output)` 等于 `output_hash`。
4. 所有 artifact refs 存在且 SHA-256 校验通过。
5. 恢复的 WarRoomRun、Agent 提案和 consistency report 能通过对应 Pydantic 合同。

暂停、取消和 stale lease 只在阶段边界生效。重试使用指数退避并受 `max_attempts` 限制；超过上限进入 `failed / max_attempts_exhausted`。投影采用 lifecycle job id 幂等键，进程在投影后崩溃时不会重复写入 `research_runs`。

恢复事件会标记 `attempt_id`、最后 checkpoint 和下一阶段。旧 attempt 与旧 artifact 保留用于审计，latest artifact 只从有效 attempt/step lineage 选择。
