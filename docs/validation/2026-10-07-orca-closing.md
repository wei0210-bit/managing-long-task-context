# Orca closing validation 2026-10-07（草稿，协调者逐步填写）

依据：接手材料 `docs/validation/2026-10-06-program-handoff.md`「要完成的程序」第 5 步；与试点 `docs/validation/2026-10-06-orca-pilot.md` 同构，用于对比五项度量。

## 固定事实
- 协调者工作区：/Users/zhaowei/orca/workspaces/managing-long-task-context/context-skill-for-Orca（main @ 017aa63，#45、#46、#47 全部合入后）
- 固定包：/Users/zhaowei/orca/workspaces/managing-long-task-context/.pinned-packages/context-strict-017aa63，Strict 0.13.0，manifest bf7688fedac119d299416bae8856cdb4a7e832086dca4d0f8520fe48b21886df（lineage pass、build pass、verify pass；进程内加载证明一致）
- Orca Run：run_b7ed73396b54（协调者 Claude Code，program-coordinator-3）
- 任务库：<协调者工作区>/.prime/context/CLOSE-A、CLOSE-B（合同已封印并在发布后立即 init-binding）
  - CLOSE-A sha256:e3596f9e58e00af1d71b6293689c2c98eb36d777e00872eed84799901fed0e48：状态命令第 4 段不再把普通条目计为派单跳过（#45 审核 M-001），Strict 0.13.1
  - CLOSE-B sha256:085ff9a5c10bc16aac01cab693d621d2b366998acf5a3b6ab4f1d77cff236611：publish_contract 拒绝非正整数 version（#46 审核发现）
  - 两份合同的验收条目都使用 `worker-report` 证据类型与封印的 `worker_report_claim.commands`（#53 新能力）
- 拓扑（与试点相同）：执行者 A、B 各一个 Codex gpt-6.1-sol high，在 new-child 子工作树；审核者一个 Codex；协调者 Claude Code
- 中断一（与试点相同）：执行者 B 写完报告后、发 worker_done 前，按派工说明先 ask 一次；协调者不回复，改用 worker-stop
- 中断二（试点为「协调者收到 A 的 worker_done 后、入账前退出，新会话接手」）：收到 A 的 worker_done 后协调者暂停一切入账；派一个没看过对话的新 Claude worker，只凭接手材料与 `scripts/context_status.py`、Orca 只读命令恢复现场，记录其操作数与证据收集步骤；之后由协调者按其结论入账
- 冷读（第 5 步「六问」）：验收记录写入后，派一个没看过对话的 Codex worker 只凭派工说明与任务库回答六问

## 度量（五项，按事件逐条记；口径与试点相同）
| 时间(UTC) | 事项 | 遗漏的上下文 | 协调者手工操作 | 证据收集步骤 | 恢复失败 | 人传话 |
|---|---|---|---|---|---|---|
| 03:31 | 从 main 构建固定包并校验；发布 CLOSE-A、CLOSE-B 两份合同并立即 init-binding（一次通过，无探路） | - | 2 | 0 | - | 0 |
| 03:32 | dispatch_spec.py 生成两份派工说明并补提交与结算规则；比对 Codex 版本（0.160.1，无需升级）；worker-start 派 A（task_fccbe90d4653 / ctx_d41ef14f6047）、B（task_ef0acbdfbead / ctx_0a66a2766d6e），均 input_accepted | - | 2 | 0 | - | 0 |
| 03:34 | A 提问：合同目标措辞「只把带 orca_dispatch_id 键但取值无效的条目计为跳过」字面上会让现有 F006–F010 断言（非 dict metadata 计为跳过）变红；A 提议保留畸形 metadata 行为、只忽略合法 dict 中无该键的普通条目。协调者确认（符合 AC-01 原文与「现有断言不改」约束） | 合同目标措辞过宽（协调者撰写合同时未核对现有隔离断言） | 1 | 0 | - | 0 |
| 03:40 | B 停下提问：正整数 version 校验使 4 个现有测试报错（tests/test_contract_history.py:56,282 发布恶意字符串 version；tests/test_truth_sources.py:1082,1100 发布 version=0），封印范围不允许改这两个测试文件。协调者裁决保持范围、B 如实以 AC-02 未通过收尾；是否授权夹具适配上报 David | 合同撰写时未检索现有测试对 publish_contract 非整数 version 的依赖 | 1 | 0 | - | 0 |
| 03:43 | 中断一：B 按派工说明 ask「Report written; may I send worker_done?」，协调者不回复，worker-stop（state stopped，终端关闭）。按派工说明的报告路径模板找到报告（无需人转述），核对合同摘要与固定包摘要一致；入账 1 主条目 + 1 建议条目；复跑去重：已入账判定为真、账本行数不变；checkpoint | 无 | 3 | 2（按路径找报告、读报告核对身份） | 否 | 0 |
| 03:44 | A 两次停下：仓库外 Strict 包全量与单独重跑 PreflightPerformanceTests 均 PERF-04 峰值内存越线（67.27 / 67.40 MB > 67.11 MB）。协调者在同机单独运行基线与候选包各 3 次全部通过（66.3 MB 左右，二者无差异），判定为执行环境开销，A 按 succeeded 交付并引用诊断日志 | PERF-04 阈值在 macOS + Python 3.12 下余量约 1%（已知波动，非本次改动） | 3 | 1（同机对照诊断） | - | 0 |
| 03:46 | 收到 A 的 worker_done（93fb6c9，delivery_fe0a80aacf4e）。中断二：协调者不 ack、不入账，写最小接手材料 docs/validation/2026-10-07-orca-closing-takeover.md（只有路径与标识），派一个没看过对话的新 Claude worker 只读恢复现场并记录操作数 | - | 2 | 0 | 待接手者记录 | 0 |
| 03:51 | 中断二接手者（新 Claude worker，task_038b466ea0dd / ctx_a87907b778d8，只读）只凭最小接手材料恢复：两任务身份 pass（首次即通过）、恢复门禁 pass（resume_handlers not_run，正确解释为需宿主处理器）；正确找出未入账的 A 报告（路径、sha256、合同摘要与固定包一致）与等待中的 A worker_done；正确识别 B 已入账、不得重复；给出与规程一致的下一步。报告 close-takeover/.context-reports/CLOSE-TAKEOVER/ctx_a87907b778d8.json | 9 条（见下方「接手者记录的遗漏上下文」） | 23（接手者；其中 19 条 shell 命令、3 次被拦或失败） | 2（接手者） | 否 | 0 |
| 03:52 | 协调者按接手结论恢复：check 取得 A 的 worker_done 批次后入账 A（摘要与接手者核对一致，1 主条目、0 建议），release A，ack；派 CLOSE-A 审核者（task_4eab36e878a2 / ctx_7479e68dbb99） | - | 3 | 0 | - | 0 |
| 03:54 | 接手 worker 发 worker_done；release、ack。按接手者提示，CLOSE-B 的 Orca 任务在 worker-stop 后仍为 blocked，task-update 为 failed（附原因） | 接手材料与 CLOSE-B 检查点都没写「worker-stop 后需 task-update」（接手者第 8 条） | 3 | 0 | - | 0 |
| 04:00 | A 审核者（task_4eab36e878a2）PASS；入账、release、ack。集成：从 main 建 wei0210-bit/closing-validation，cherry-pick A（9ce750f），追加 R-023，提交收尾文档（d72c709），推送 | - | 4 | 0 | - | 0 |
| 04:09 | 协调者在集成提交 d72c709 上按封印命令复跑（test_resume_gate、全量、test_distribution，均 exit 0），组装 worker-report，用 worker_report_handlers 调 record_acceptance：appended、decision=pass、reproducible=true（AR-3c3b129f0c439f57）。**首次在真实任务库得到完成门 pass**（试点两任务均 unknown）。固定包状态命令第 6 段 still_valid（记录提交是 HEAD 祖先、合同一致、证据副本完整、验收后账本前进 0 条），退出码 0；用仓库源码运行状态命令时身份为 RUNTIME_PATH_MISMATCH（预期：绑定的是固定包） | 状态命令须用固定包内的脚本运行（文档未强调） | 3 | 0 | - | 0 |
| 04:15 | 冷读者（Codex，task_a028f3207f5e / ctx_a1f579740000，只读，未读 docs/validation）六问全部作答且逐条引用文件或命令输出；release、ack；按其提示补 CLOSE-A 检查点（accepted） | 冷读者记 8 条输入限制（见下） | 3 | 0 | - | 0 |

## 事件记录
（逐条追加）

## 汇总（2026-10-07 04:20 UTC）

### 两次中断的通过判定（与试点同一判定项）
| 中断 | 判定项 | 收尾 | 试点 |
|---|---|---|---|
| 一（B 发 worker_done 前被 worker-stop） | 报告不靠人转述即可入账 | 通过（按派工说明的路径模板找到报告，核对合同与固定包摘要） | 通过 |
| 一 | 去重 | 通过（复跑判定已入账，账本行数 4→4） | 通过 |
| 一 | Orca 任务按恢复流程处置 | 通过（task-update failed 附原因；此步由接手者指出） | 部分 |
| 二（收到 A 的 worker_done 后协调者暂停，新会话接手） | 身份恢复 | **首次即通过**（发布后立即 init-binding） | 首次失败（BINDING_MISSING） |
| 二 | 只凭最小接手材料找出未入账报告与待处理消息 | 通过 | 通过 |
| 二 | 去重、无重派 | 通过（接手者明确列出不得重复的动作） | 通过 |
| 二 | 能说出下一步 | 通过（与规程一致，含「只用 check 返回的批次 id 去 ack」） | 通过 |

### 验收结果（Strict 侧）
| 任务 | 协调者核验 | 审核者（Codex，只读） | completion gate |
|---|---|---|---|
| CLOSE-A | 集成提交 d72c709 上按封印命令复跑三项均 exit 0 | PASS | **pass**（worker-report 证据，record_acceptance AR-3c3b129f0c439f57，reproducible=true；状态命令 still_valid） |
| CLOSE-B | AC-01 pass；AC-02 未过（正整数 version 校验使 4 个现有测试报错，范围不允许改测试） | 未派（执行方已 failed） | 未运行；never_accepted |

试点两个任务的完成门都只能给 unknown（缺 verifier）；本次首次在真实任务库得到 pass，且「当时通过」与「现在仍成立」分开呈现。

### 冷读六问（没看过对话的 Codex worker，只凭派工说明与任务库，未读 docs/validation）
六问全部作答，逐条引用合同字段或只读入口输出：目标、范围与归属（含越界项）、验收原文（附合同路径与封印摘要）、过期/冲突/阻塞（正式为 0，并指出检查点行动指针已落后——协调者随后补检查点）、最近验收与是否需重新验收（AR-3c3b129f0c439f57、pass、d72c709、still_valid）、已结束与已验收的区别（A 有仍有效的验收记录；B 只有结束的执行与部分结果，never_accepted；worker_done、worker-stop、报告入账都不等于 Strict 接受）。报告：close-cold/.context-reports/CLOSE-COLD/ctx_a1f579740000.json。

### 五项度量（全日志 13 条事件合计）
| 度量 | 收尾 | 试点 | 说明 |
|---|---|---|---|
| 遗漏的上下文 | 7 条事件 | 11 条事件 | 收尾的 7 条中 3 条源于协调者撰写合同时未核对现有断言或测试依赖（A 目标措辞、B 的 version 依赖、状态命令须用固定包脚本运行），其余为接手者与冷读者记录的输入缺口 |
| 协调者手工操作次数 | 53（其中接手者 23） | 46（其中接手者 30） | 接手部分下降；非接手部分 30 对 16 上升，原因是本次多做了试点没做的环节（协调者在集成提交上复跑取证、record_acceptance、冷读派单）与 3 次临场裁决、1 次性能波动诊断。按同一口径不能判为下降 |
| 证据收集步骤数 | 5（其中接手者 2） | 16（其中接手者 14） | 状态命令与报告路径模板使接手者无需逐个翻找 |
| 恢复是否失败 | 0 | 2 | 派工前自动升级 Codex；发布后立即 init-binding |
| 人传话次数 | 0 | 1 | |

### 接手者记录的遗漏上下文（9 条，原文见接手报告 missing_context）
接手材料未给派单 id；未写状态命令的参数；报告目录辅助文件多，需按命名规则挑主报告；Orca 没有给协调者的只读收件箱命令（`inbox --terminal` 为空，需查未限定的 inbox）；Orca 哪些命令只读未写明；是否需要 run-use 不明确；恢复门禁的 resume_handlers 为 not_run 时如何提供宿主处理器未写；worker-stop 后需 task-update 未记录；未独立复核 A 报告中的性能诊断字段。

### 冷读者记录的输入限制（8 条，原文见冷读报告 input_gaps）
主要是：未提供原始证据而无法独立复验红绿与性能结论；检查点行动指针落后；没有机器可读的 owned_paths 清单；只读入口不带 worker-report 处理器，diagnostic pass 与原始 resume_gate.passed=false 并存、须看具体检查；B 的失败用例名未入库；验收记录按分支存在；固定包为 0.13.0 而合同交付 0.13.1。

### 结论
- 第 5 步的两项要求：六问——**通过**；与试点同构的小任务重测五项度量——**已完成**，其中遗漏上下文、证据收集、恢复失败、人传话四项下降，手工操作总数未下降（原因见上表），如实记录，不判为改善。
- 新机制在真实任务库上端到端可用：发布后 init-binding、恢复门禁、状态命令、合同历史（STEP6-46C、STEP7-47 改版时自动留存）、worker-report 完成门 pass、验收记录与 still_valid 判定。
- CLOSE-B 未合入，是否授权改 4 个测试的构造方式（保留全部断言）待 David 决定。

### 留给后续（本次新增）
- 接手材料模板补派单 id、状态命令完整调用、worker-stop 后 task-update；Orca 侧需要协调者可用的只读收件箱命令。
- 状态命令与只读入口可选接收宿主 worker-report 处理器，避免 diagnostic pass 与 resume_gate.passed=false 并存造成误读。
- PreflightPerformanceTests 的 64 MiB 阈值在 macOS + Python 3.12 下余量约 1%，在 Codex 进程环境中多次越线（基线同样接近上限）；改为相对基线或调整阈值属于质量底线测试变更，需 David 授权。
- 合同撰写前先检索现有测试对被改接口的依赖（本次两次因此临场裁决）。
