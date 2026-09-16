# E5 v1 — Lite短会话接续（派发前冻结）

工作区：`.worktrees/short-session-remaining`；Terra-high实施、独立审核。用户授权连续本地开发；禁止提交/安装/生产/远程发送/真实付费调用。E4宿主UNKNOWN不阻塞此轻量路径。
目标：复用现有NOW校验、原子写入、身份绑定和resume，提供不隐含记忆/控制权的轻量flush与冷启动核对材料，不引入Strict引擎。

## 文件与接口

仅 `skills/context-lite/scripts/context_lite.py`、`skills/context-lite/SKILL.md`、新增 `skills/context-lite/references/short-session.md`、`tests/test_context_lite_handoff.py` 和 `docs/validation/e5-executor-report.md`。
主控另做完整包声明/测试分发。模板固定标题与80行/8000字符/单行500/Next3项不变。

- `flush`：CLI别名复用现有`write`验证和原子替换；输出`now_sha256`帮助新会话固定读入版本，不增加第二事实库。
- `cold-check`：复用identity-bound `resume`的全部参数及hard stops，成功时返回只读恢复核对材料：task_id、now_sha256、目标、Acceptance、Current State、Decisions、In Flight、Blockers、唯一First action及稳定刷新映射。不得执行任何引用；该材料只供独立重观察/复述使用，非语义核验通过。
- `cold-check --expected-now-sha256`：可选固定交接版本；不匹配、不合法hash、读取失败或读取中内容变化，返回unknown且不交付恢复正文；不得静默以最新文本洗掉交接时的版本。
- 明确输出`history_inheritance: unknown`、`semantic_verification: pending`、`archive_allowed: false`。模型需独立观察来源并逐项复述，不能凭文档指纹或格式合法声称已冷启动成功；此单不实现模型评分器。
- 新会话验收前保留旧会话/任务文件；对话归档不移动仍需继续的NOW。原finish只用于任务结束，不能拿它代替rollover。

## 冻结验收

1. 合法flush与write同样写入；重复flush完全不改mtime/内容，指纹一致。
2. 缺标题、重复First、各项超限、同ID目标冲突、写中断均不破坏旧NOW；沿用旧错误码。
3. 完整包绑定后的cold-check可只读提取所有7段，不引入旧聊天，所有STATE/RUN刷新映射保留，当前语义仍pending。
4. 未绑定、错任务/工作区/包、requires-rule-proof、缺/不可读NOW均无恢复正文；optional experience不削弱旧门禁。
5. 错指纹及读取后变化拒绝；不因文件存在/文本pass提高semantic_verification。
6. 两次独立Python进程只靠完整包/绑定/NOW产出相同冻结材料；明确这是程序冷读取，不是模型冷启动证据。
7. 任意refresh_ref不自动执行；unknown in-flight不重试；20次cold-check无写入/模型/业务动作。
8. Skill仅补短流程与按需引用，保留现有hard stops；不添加Strict身份/授权控制引擎，旧路由行为不变。

TDD：先RED行为后GREEN；命令 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_context_lite_validator test_context_skill_router test_context_lite_handoff -v`。
报告原始红/绿片段、数量、耗时、修改清单和NOT_RUN。旧经验/身份专项最终由主控统一回归。
