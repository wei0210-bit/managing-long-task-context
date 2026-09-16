# 真实Agent冷读取初测：已准备，派发受阻

状态：BLOCKED_HOST_THREAD_LIMIT。2026-09-16T00:20:08Z。
本轮没有真实模型结果，不能报告8例通过、0次错误、token节省或冷启动成功。

## 已完成

- 已在派发前冻结[验收与评分](2026-09-16-agent-pilot-contract.md)，不将评分答案交给执行者。
- 创建Lite/Strict各4个合成任务：正常、原件变化、未知在途、错误工作区；保留完整包及显式任务绑定。
- 两个包manifest重新匹配上一轮收据并完整verify通过。
- 主控实际运行8个公开恢复命令：6个返回材料；两个错工作区均exit1/WORKSPACE_MISMATCH，不返回材料。
- Strict本轮是既有绑定恢复路径，未启用truth-sources/v1或handoff控制权迁移。原件变化/未知动作案例的材料可读，不代表允许依赖、重试或完成；这正是待测的模型行为。不得拿这组数据判断Strict启用全部可选安全能力的表现。
- [准备脚本](prepare_agent_pilot_20260916.py)和[原始回执及输入指纹](2026-09-16-agent-pilot-setup.json)已保存。git diff --check通过；未修改产品文件。

## 实际派发

一次spawn_agent请求：cold_lite_20260916，gpt-5.6-terra/high，fork_turns=none。
工具返回原文：`collab spawn failed: agent thread limit reached`。
没有创建成功的子Agent ID或模型答卷；Strict未继续派发。没有续用旧Agent、没有额外CLI/API模型调用、没有创建用户侧新任务。
这是宿主创建子Agent受限，不是测试案例失败，不据此推断账号余额或并发上限。没有证据表明归档现有任务就能解除该限制。

## 统计

真实Agent可评分结果：0/8。错误放行、错误阻塞、模型一致性全部UNKNOWN/NOT_RUN，不填0%。
只有准备阶段程序检查结果，不能替代Agent读原件、遵守约束的实际行为。
Agent输入/缓存/输出token及费用UNKNOWN；准备工作与本轮主控对话存在成本，未做独立归因。
真实自动迁移、旧主控退出后的子任务存活、跨父会话控制、自然项目收益仍未测。

## 接续入口

从一个能新建子Agent的新主控会话继续，先读[接续任务](2026-09-16-agent-pilot-handoff.md)。旧会话不得作为执行Agent历史注入。
执行者只接收各自的ENTRY和完整包，不读本报告、评分合同或主控准备回执。
临时目录可能清理；如需重建，先运行准备脚本，再冻结新输入hash与新绝对路径；不得继续使用本次旧回执冒充新夹具。
本轮不安装、提交、合并、推送或部署。
