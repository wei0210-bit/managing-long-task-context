---
status: validated-release-candidate
ceo_review: complete
eng_review: complete
task: short-session-handoff
updated_at: 2026-09-16T01:45:39Z
branch: codex/short-session-remaining
observed_head: 0f5898e19b4951c661edce1f7db80f95cc1b2ecc
plan_version: 0.39
plan_sha256: caa698a5bcdc385685c99d063b6d4636a3e6e5bc85ddaca10abe4bbd312d6472
---

# 项目恢复入口

## 目标与权威依据

Context Strict／Lite 支持可验证的短会话接续：有效、精致而经济。
当前主计划：[short-session-handoff.md](docs/superpowers/plans/short-session-handoff.md)。v0.39位于候选工作区；原main目录的v0.37计划仅为历史快照。
保留15项需求、23项选择、29组案例和20个子案例；详情按需读取，不重读全部对话。
原始对话副本 `方案对话内容.txt` 仅保留在本机且不进入 PR；其指纹与已采纳决定已冻结在主计划。

## 工作区与当前结论

原main：`/Users/zhaowei/Desktop/David/project.nosync/managing-long-task-context`，保留E1-E3未提交源码。
最新开发：该根下 `.worktrees/short-session-remaining`，分支 `codex/short-session-remaining`。
该分支以HEAD加E1-E3未提交快照为基线；HEAD本身不代表当前代码，恢复先核对Git和文件身份。
E0-E3及E5/E6本地验收通过；E4仅能力报告/拒绝路径本地通过，真实原生宿主接管BLOCKED；E7预算条件未触发。
最新：[发布前对抗复审](docs/validation/2026-09-16-prelanding-security-review.md)。569/569全回归、完整包Strict434/434、Lite64/64，均0skip/资源警告；R1–R4及后续7项安全/分发缺陷均已闭环。
F1-F5全部独立复审关闭；先前42/42、549/549中间绿色不足的原因、修复及原日志保留，不替代最终结果。
Strict0.8.0与Lite1.4.0最终包必须以提交 SHA 重建；临时候选可能清理，不能只凭版本号或旧manifest安装。
旧E2/E3、E4-E6、v0.37及review-fix包均为历史候选，不能误装。
全部执行Agent已停写，所有验证进程退出已收取；无未领取结果，不重复派E0-E6。

## 未验证与授权边界

用户授权本地任务连续完成，无须逐步问“继续”；不等于新增生产或付费权限。
2026-09-16 用户另行授权安装两个完整包、提交、推送并创建 PR；仍不包含合并、部署、修改生产项目或新建付费评估。
Codex/Claude真实接管、宿主可信身份/fencing/干净会话、模型冷启动和自然项目效果仍未验证。
真实token节省/缓存费用/模型稳定性UNKNOWN；本地合成耗时与进程RSS不能冒充收益。
无Strict运行绑定/控制权证明；本入口是导航，不能从旧摘要继承权限。外置记录不授予授权，未知执行不自动重试。
先前远程上传受阻；用户随后明确授权脱敏摘要，已发布并回读 [Issue #22](https://github.com/wei0210-bit/managing-long-task-context/issues/22)。仅摘要已同步，源码未推送、远程CI未运行，不重复发送。

## 下一步

2026-09-16 真实 Agent 冷读取初测已接续完成：[报告](docs/validation/2026-09-16-agent-pilot-report.md)。两次新的 Terra-high 单会话共 8 个合成任务全部通过冻结语义标准，错误放行 0/6、错误阻塞 0/2，38/38 输入哈希保持不变；旧线程上限阻断报告仅作归档。没有 No-Skill 对照，token、费用、严格墙钟和自然项目效果仍为 UNKNOWN，不得据此宣称收益或稳定性。

2026-09-16追加只读/隔离使用验收：[报告](docs/validation/2026-09-16-skill-acceptance-report.md)。review-fix两包身份重新核实；Strict55/Lite14项定向测试通过，公开合成链通过。Lite原件变化仍返回待核实材料，不能当自动stale拦截；真实Agent冷启动与token收益未验证。没有产品修补、安装或发布。

First action: 以最终提交 SHA 重建并核验两个完整包，安装后再以安装路径执行 full doctor；远程状态以本分支 PR 和 CI 回执为准。若扩大真实自动接管，先补可信宿主证据与隔离真实路径验证，未验证能力保持关闭。
旧恢复入口完整保留于 [CONTEXT-v0.36](docs/validation/archive/CONTEXT-v0.36.md)，仅具体争议时读取。
各阶段红绿、主控裁决与代价在最终报告及隔离工作区 `.superpowers/sdd/short-session-handoff/progress.md`；不得只信执行者自报。
