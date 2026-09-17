---
authority: AUTHORITATIVE_NOW
task: context-strict-real-migration-hardening
current_phase: phase-1-migration-truth-and-preflight
plan_path: docs/superpowers/plans/2026-09-16-context-strict-real-migration-hardening.md
plan_sha256: 489bea1f008650d1f1fa819550c1e484e76d6fdc4b9a7e6f3a2063b0d965d46d
package_manifest_sha256: null
package_source_revision: null
baseline_head: 16c06eede42544eb7a4f0271b3590728352e2426
implementation_head: null
verified_head: null
verified_at: null
updated_at: 2026-09-17T00:00:00Z
---

# 项目恢复入口

## 当前权威依据

- 当前唯一方案：[Context Strict 真实迁移第一阶段](docs/superpowers/plans/2026-09-16-context-strict-real-migration-hardening.md)。授权只在该方案 frontmatter 与 Decision Record 中定义；本入口只导航，不授予权限。
- `baseline_head` 是本轮实施起点，`implementation_head` 是包含实现的提交，`verified_head` 是最后一次完整校验实际运行的提交。
- `current_head` 由 `handoff_preflight.py` 实时读取，不写入本文件；`documentation_head`、`merge_head` 只出现在提交后外部回读的验收记录中，缺失即 UNKNOWN。
- 值为 `null` 的字段表示尚无事实；preflight 按 UNKNOWN 处理，不猜测、不补填。

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

## 下一步

First action: 按方案 T2–T4 只编辑维护源，运行同步器与完整验证，再以实际完成完整校验的提交填写 `implementation_head`、`verified_head` 和包 SHA。
