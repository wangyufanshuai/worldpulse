# Golden Scenarios

`tests/golden_scenarios/` 保存 10 个版本化场景，覆盖海峡封锁、能源中断、粮食冲击、制裁、政策缓冲、链路替代、国家 override 和多政策组合。每个 fixture 固定输入、seed、`rule_set_version`、baseline/final hash、国家与链路排序、timeline turning points 和 Agent accepted/rejected 计数。

Golden 测试验证同版本同输入的确定性输出和 hash，不声称现实预测准确率。规则改变时必须升级规则版本、重新生成期望值并在 CHANGELOG 解释原因；不得静默修改 fixture。

敏感性测试覆盖 intensity、propagation、duration、policy actions 以及 chain substitution/lag，验证方向性和边界而不是统计预测能力。
