---
authority: AUTHORITATIVE_NOW
task: context-strict-real-migration-hardening
current_phase: phase-1-migration-truth-and-preflight
plan_path: docs/superpowers/plans/2026-09-16-context-strict-real-migration-hardening.md
plan_sha256: 80bdd97c7babbd7ba50236b7eafe6d972ff9dc8ad8dc382f8075ab19a0a0b3cf
package_manifest_sha256: df1a81abda8d5a1d8851bf972a0b8301b84ee8fc53c4e6f078dffa809c5af4e4
package_source_revision: git:0f9fdd1ab708a20e57bc9e73bdb294a7ded8d0af
baseline_head: 16c06eede42544eb7a4f0271b3590728352e2426
implementation_head: 0f9fdd1ab708a20e57bc9e73bdb294a7ded8d0af
verified_head: 0f9fdd1ab708a20e57bc9e73bdb294a7ded8d0af
verified_at: 2026-09-17T02:13:20Z
updated_at: 2026-09-17T02:17:10Z
---

# 项目恢复入口

## 当前权威依据

- 当前唯一方案：[Context Strict 真实迁移第一阶段](docs/superpowers/plans/2026-09-16-context-strict-real-migration-hardening.md)。授权只在该方案 frontmatter 与 Decision Record 中定义；本入口只导航，不授予权限。
- `baseline_head` 是本轮实施起点，`implementation_head` 是包含实现的提交，`verified_head` 是最后一次完整校验实际运行的提交。
- `current_head` 由 `handoff_preflight.py` 实时读取，不写入本文件；`documentation_head`、`merge_head` 只出现在提交后外部回读的验收记录中，缺失即 UNKNOWN。
- 值为 `null` 的字段表示尚无事实；preflight 按 UNKNOWN 处理，不猜测、不补填。
- `package_manifest_sha256` 是以 `package_source_revision` 从 `skills/context-strict` 重建的完整包 manifest；不同构建来源的包按 STALE 处理。

## 状态标签

- HISTORICAL_ONLY：只供追溯，不是当前事实。SUPERSEDED：人工标注的已替代资料。
- STALE：plan、package 或引用摘要不一致，或 `verified_head` 之后出现非允许列表变更。
- UNKNOWN：缺少完成比较所需的原件或可信解析器。NOT_RUN：尚未运行。BLOCKED：只用于具体外部阻塞。
- `brief_diagnostics().usable=true` 只证明结构可用，不等于事实仍是当前事实。

## 迁移结论口径

- 迁移前先选定 `strict_protocol` 或 `manual_fallback`，不得省略或静默切换。
- 分别报告 `information_recovery`、`control_transfer`、`source_retirement`；第一阶段 `archive_allowed=false`，不归档旧会话。
- `material_integrity=pass` 不等于信息恢复；只有 `clientThreadId`、自报成功或普通消息不能证明控制权转移。

## 历史资料

- SUPERSEDED / HISTORICAL_ONLY：[short-session-handoff.md v0.39](docs/superpowers/plans/short-session-handoff.md)，其内嵌 Node 校验器已退出权威校验链。
- HISTORICAL_ONLY：[发布前对抗复审](docs/validation/2026-09-16-prelanding-security-review.md)、[Agent 冷读取初测](docs/validation/2026-09-16-agent-pilot-report.md)、[Skill 验收](docs/validation/2026-09-16-skill-acceptance-report.md)。
- HISTORICAL_ONLY：v0.39 恢复入口原文见提交 `16c06ee` 中的 `CONTEXT.md`；更早入口见 [CONTEXT-v0.36](docs/validation/archive/CONTEXT-v0.36.md)。
- 历史 checkpoint、旧候选包和旧评审只作回归输入，不冒充当前结论。

## 未验证与授权边界

- NAT-01（授权的 manual fallback 冷恢复）与 EVAL-01（代理行为评估）：NOT_RUN。
- 真实宿主迁移与可信接管、远程 CI、token/费用/自然项目收益：NOT_RUN/UNKNOWN。
- 未授权：v2 回执、归档旧会话、修改共享 `context_doctor.py` 或 Lite 接口、合并、推送、部署。
- 本地实施与验证证据：`docs/superpowers/evidence/context-strict-migration/RUN-20260917-phase1-0f9fdd1/`；远程 CI NOT_RUN。
- 已知风险：`test_truth_sources` 中 3 个既有锁时序测试在高负载主机上曾失败一次，重跑通过，源码未改动。

## 下一步

First action: 以 `verified_head` 重建 Strict 包并运行 `handoff_preflight.py` 只读核验本入口；NAT-01、EVAL-01、真实宿主迁移、推送与合并须先取得用户单独授权。
