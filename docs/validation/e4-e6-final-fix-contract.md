# E4-E6 最终集中修复合同 v1（派发前冻结）

授权沿用户剩余本地开发连续执行；本单落实整批独立审核4项Important及主控裁定的一处计划歧义。禁止提交/安装/推送/生产/付费模型/远程工单，不改原有安全策略或E0预期。
工作区仍 `.worktrees/short-session-remaining`。Terra-high执行，主控集成及独立复审。单执行者，不再派Agent。

## 冻结修复与验收

F1 Lite unchanged flush：已验证A，再读B时不能报告goal A + hash B。两读間换为不同goal或不同状态的合法NOW，必须unknown且无成功指纹；或者只捕获/验证同一份原始字节并拒绝可观测变化。保留原CRLF/mtime/原子失败/目标冲突测试，不以规范化文本代替原字节hash。新断言需先红，保持旧write默认语义。
F2 pressure提醒：有效低占用先defer且未通知，随后同sample到期且显式安全milestone，首次notify=true；之后20次false。已经通知的记忆不能在无通知时重置导致隔次重复。样本冲突仍unknown，跨session不复用提醒；关键阶段改变必须重新评估。
F3 时间：`0001-01-01T00:00:00+23:59`及上界负偏移导致UTC换算越界，usage、pressure输入、CLI --now及直接datetime now均结构化unknown，无traceback/假总量。有效跨时区继续正确，不一律拒绝合法时区。
F4 旧Lite validator：仅把`tests/test_context_lite_validator.py`的ROOT/TOOL定位兼容包根，保留全部旧断言；加入Lite同步/required_paths/一致性检查/包外CI，与handoff/usage一起非零实际运行。

## 主控裁决 F5（补足原U-R01，无新控制权限）

Ruling: 采用最终审核推荐B，将压力数值与安全/关联字段分别校验。原E6正文要求未知量回退阶段，P2允许unknown的宽写法不能永久删掉此路径。缺量、非法或过期压力值时，只有session/sample ID、UTC可解析且非未来的观测关联及全部4个bool安全字段有效，safe_point=true、milestone=true、task_complete=false、execution_unknown=false，才建议milestone；不伪造百分比，不返回prepare。缺身份/时间/安全字段、伪造累计口径、已完成/未知执行不得借milestone变绿。它是提醒建议，automatic_action=false；身份只指观察关联不是宿主认证，真实接管仍关闭。代价：新增少量降级/去重分支与反例，不新增宿主调用。

F5验收：缺window数值或None且明确安全milestone正例notify仅一次；缺session/sample、错时间、缺safe字段、非bool、task_complete、execution_unknown、未到milestone负例不prepare/不建议接续。重复20次无重复提醒；有效current-window无需milestone仍按原阈值prepare；不改其它权威门禁。相关按需说明必须同步，明确旧E6 v1“缺量一律unknown”为被本裁决替代的候选行为。

## 文件所有权

- Lite helper及tests/test_context_lite_handoff.py。
- scripts/context_usage.py及tests/test_context_usage.py、references/context-usage.md。
- tests/test_context_lite_validator.py、scripts/sync_context_tools.py、tests/test_distribution.py、skills/context-lite/skill-package.json、.github/workflows/ci.yml。
- docs/validation/e4-e6-final-fix-report.md。
主控保留同步生成动作、包重建、最终回归、计划/CONTEXT。不得改主控独立probe或冻结预期。

先行为RED，GREEN只跑针对性：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_context_lite_validator test_context_lite_handoff test_context_usage -q`及 `... docs/validation/e6_controller_probes.py -q`。包清单在主控同步前会有预期分发差异，必须报告不掩盖。
保留修改前后的关键输出/命令/案例数/耗时及源码清单；完成后明确停写。不要为报告重复跑整套。
