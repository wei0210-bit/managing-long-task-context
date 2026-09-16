# 给新主控的接续任务（不要交给受测Agent）

状态：已于 2026-09-16 接续完成。不要再次派发；最终评分和原始答卷见 `2026-09-16-agent-pilot-report.md`。

目标：继续两次Terra-high真实Agent冷读取初测，不再开发Skill。本文件用于新主控恢复，不含全聊天。

先读同目录 `2026-09-16-agent-pilot-contract.md`、`2026-09-16-agent-pilot-report.md` 和 `2026-09-16-agent-pilot-setup.json`。
主目录不是候选源码；候选位于 `/Users/zhaowei/Desktop/David/project.nosync/managing-long-task-context/.worktrees/short-session-remaining`。
核对全部输入hash和两个完整包manifest。输入目录：`/var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i`。
如果已清理，执行 `prepare_agent_pilot_20260916.py` 前先保存旧回执为历史，然后记录新的路径/hash；不能跳过验证。

派发两次新的子Agent，模型gpt-5.6-terra，推理high，fork_turns=none；每次各收lite/ENTRY.json或strict/ENTRY.json。禁止旧Agent续聊假充冷启动。最多2次初始派发，不根据评分结果训练式重试。不要启动外部付费CLI/API。

执行者提示模板（替换KIND为lite或strict）：

> 做一次Context KIND只读任务恢复，用户已手动选择该Skill。读取 `/var/folders/71/c6qxyfgs7_7637gwxq34m7th0000gn/T/mltc-agent-pilot-1g4_jd0i/KIND/ENTRY.json`，再读指定完整包的SKILL.md和必要references，实际执行公开恢复命令。解释器 `/opt/homebrew/bin/python3.12`。逐task报告目标、现状、约束/验收、阻塞、下一步、完成/重试/归档判断，以及实际命令、诊断和原件依据。只读检查，不改输入、不改绑、不做业务动作或调用其他Agent/模型。只读本组入口及必要原件、完整包文档/API帮助，不读主仓库、旧聊天、其他组或评分材料。身份失败按Skill停。唯一可写输出为本组REPORT.md，用apply_patch。PYTHONDONTWRITEBYTECODE=1。不自评通过率，缺证据写unknown。

主控等待结果时独立核对原件和程序判定，不给执行者正确答案。结束后核对输入是否变化、逐项评价，输出模型原始答卷与主控评分，无法确认的工具执行声明不能算证据。宿主没有返回的token数据记UNKNOWN。
没有No-Skill对照、每组仅一次会话；只能报告小样本行为，不能声称节省token或统计稳定性。
用户授权的是本地隔离验收，不包含全局安装、提交、合并、推送、生产或付费扩展；新主控仍遵守宿主当前权限。
