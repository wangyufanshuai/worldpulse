# Lifecycle Fault Injection

执行器提供测试专用的 before/after phase hook。测试在六个阶段的前后注入异常，确认：

- 失败 attempt 被记录并按退避策略重新排队。
- 连续有效 checkpoint 被复用，已完成阶段不重复执行。
- projection 在故障前后最多产生一份 lifecycle 结果。
- artifact 篡改、缺失或 hash 不匹配时 Replay fail-closed。
- pause/cancel 不会投影未完成结果。

安全 corpus 覆盖 prompt injection、authority escalation、unknown entity、fake evidence、budget overflow、未知参数和超长输出。Agent 输入必须经过结构合同与一致性评估；任何失败都不能改写确定性风险数值。
