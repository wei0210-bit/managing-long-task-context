---
authority: AUTHORITATIVE_NOW
task: STRICT-LEDGER
baseline_head: 5c7827feba609ecb3f6d529a9b23cd847b87107d
package_version: 1.0.0
---

# Context Strict 项目事实入口

当前实现将 Strict 精简为多 agent 共用账本。会话、计划、派工、等待、执行与审核由
Orca 负责；Strict 保留事实、来源、证据指针、有效期、检查点、合同封印与历史、报告登记、
验收记录、共享存储、经验记录和包身份诊断。健康与证据报告只反映缺失、过期、未验证事实。

本轮批准依据为 STRICT-LEDGER 原始合同与 David 2026-10-14 的批准清单；共享账本位于
`context-skill-for-Orca/.prime/context/STRICT-LEDGER/`。交付证据在执行工作树
`.context-reports/STRICT-LEDGER/`，不进入 Git。合并、全局安装及仓库外规则更新由协调者另行处理。

历史迁移方案、旧派工模板和原始验收报告保留供追溯，均为 HISTORICAL_ONLY，不能充当当前执行规程。
当前能力说明见根 `SKILL.md`；回归条目退役记录见 `docs/regression-checklist.md`。
