# 接手材料：后续设计与实施程序（2026-10-06）

写于原协调者会话（终端 term_1cce21fa-a872-4144-afd0-9a82d17bb3c4）上下文接近耗尽时。接手者是新的 Claude Code 协调者会话；执行者与审核者按 David 的规则用 Codex gpt-6.1-sol high。David 的常设授权：除删除文件等安全性操作外，决策按协调者的推荐直接执行；合并 PR 与放宽质量底线仍按全局 CLAUDE.md 的规则。全程用中文向 David 汇报。

## 固定事实
- 协调者工作区：/Users/zhaowei/orca/workspaces/managing-long-task-context/context-skill-for-Orca（main；工作区里有未跟踪的 .gitattributes、.githooks/、.prime/，是任务库写入的设计产物，不要删，不要 git add -A，用 `git status --short --untracked-files=no` 看已跟踪改动）。
- 设计文档（已批准，收窄版）：/Users/zhaowei/.gstack/projects/wei0210-bit-managing-long-task-context/zhaowei-wei0210-bit-context-skill-for-Orca-design-20261006-031205.md。文末「Reviewer Concerns」是三份后续设计必须逐条回答的输入。
- 试点报告：docs/validation/2026-10-06-orca-pilot.md（含五项度量基线、已知缺陷与新发现；#48 候选裁决在 issue #48）。
- 协作规程：references/orca.md（含 #59 增补的四条）；派工模板：docs/agents/orca-pilot/；回归清单：docs/regression-checklist.md（只增不删，退休需 David 审批）。
- 固定包（仅用于读 skill 文档与只读入口，代码改动用工作树 src）：/Users/zhaowei/orca/workspaces/managing-long-task-context/.pinned-packages/context-strict-00ec012（manifest 9c74752b2d0bc446be4586ac28a8a2be0ab4b0dbfa6fa372728585f1ef1fc913）。main 上 Strict 已是 0.8.9；下一次实施前可按 README 用 skill_package.py 从当前 main 构建新的固定包并换用。
- 任务库：<协调者工作区>/.prime/context/ 下已有 PILOT-A、PILOT-B、STEP3-43/44/51/52/59、STEP4-58/62 等任务，都是封印合同加入账记录；新任务另起 task_id。发布合同后立即 `context_doctor.py init-binding`（#59 规程）。
- 派 Codex 前比对 `codex --version` 与 `npm view @openai/codex version`，有新版直接 `npm install -g @openai/codex`（David 已授权）。
- 派工流程范例：本会话对 #43、#44、#51、#52、#59 的做法：封印合同 → 用模板填派工说明（AC 原文照抄 + 合同路径与摘要 + 报告路径模板 + 固定包与版本证明）→ `orca orchestration worker-start --spec … --worktree new-child --base-branch main --agent codex --model gpt-6.1-sol --effort high` → `check --wait` → 核对报告与原件（先红后绿自己复跑）→ 入账（主条目 + 建议条目，按 dispatch id 去重）→ worker-release → ack → 从 main 新建分支 cherry-pick → 全量测试、同步无漂移、仓库外 build+verify → 回归清单追加 → push、PR、issue 评论并关闭 → CI 过后合并。#58 合入后可用 scripts/dispatch_spec.py 生成派工说明。

## 还在进行中的（接手时先核对）
- #58、#62 已合入 main（PR #65、#64）。main 上有 scripts/dispatch_spec.py，派工说明可直接生成：`python3 scripts/dispatch_spec.py --store <协调者工作区>/.prime/context --task-id <id> --role executor --package-root <固定包> --expected-manifest <摘要> --coordinator-workspace <协调者工作区> --baseline-commit <sha> --owned-paths …`，再在末尾补提交规则与 worker_done 要求。
- #63 已由原协调者集成并合入 main（PR #66）。原协调者的 Run run_26b4e8c9d898 已无活动派单；接手者新建自己的 Run，不必 run-use 它。

## 要完成的程序（按顺序）
1. **#45 恢复门禁设计**：`checked_resume()` 调用 `gate(stage="resume")` 的方式；门禁不通过时接手者靠什么拿上下文（必答 R2-1）；命令行入口 `context_doctor.py resume` 在冻结文件里如何返回非零（R2-2，David 已授权解冻 runtime_identity.py，context_doctor.py 仍冻结）；只读角色能否调 brief()（R2-17）；吸收 #55（发布流程 init-binding、migrate_contract docstring）与「一条命令看清任务现状」（接手者入口；试点里接手者 30 次手工操作、14 步证据收集）。
2. **#46 验收记录落盘设计**：`gate-recorded` 的触发与幂等（显式参数才追加）、字段（合同摘要、账本游标、code_revision、证据摘要）、「需重新验收」的判定不能恒为真（R2-8）、code_revision 来源与各报告的关系（R2-9）、检查结果随任务库留存（R2-10）、旧版本读不了含新事件的任务库与全局安装同步前的防护（R2-11）；吸收 #53（实现合同声明的 project:file-claim/v1、project:test-report-claim/v1 verifier，试点里 completion gate 因此只能 unknown）与 #54（合同改版保留旧版全文）。
3. **#47 经验库去绝对路径设计**：必答 R2-5、R2-6、R2-7、R2-19；可能的结论是整项移到候选。改动会同步进 Lite，Lite 冻结与版本号变更需 David 另行授权。
4. 每份设计：写成短文档（建议放 ~/.gstack/projects/wei0210-bit-managing-long-task-context/ 下，或 docs/designs/），用独立审查代理（不是作者自己）审一到两轮，然后交 David 批准；批准后按上面的派工流程实施，每份一个或多个 PR，回归清单只增不删。
5. **收尾验证**：全部实施合入后，从 main 构建固定包，让一个没看过对话的新 Orca worker 只凭派工说明和任务库回答六问（目标、范围与归属、验收原文、过期或冲突的事实、最近验收结论与是否需重新验收、已结束与已验收的区别），并用与试点同构的小任务重测五项度量，结果写 docs/validation/<日期>-orca-closing.md。
6. **全局安装同步**：收尾验证通过后，先整目录备份 ~/.codex/skills/context-strict 与 context-lite（~/.claude/skills 下是指向它们的软链接），执行前向 David 单独确认，再替换；之后用 `scripts/context_doctor.py check --mode full` 核对。

## 留给后续（不要自行处理）
- 子工作树（issue-37/38/39、pilot-a/b、step3-43/51/44/52/59、step4-58/62）都未删，删除要 David 审核。
- 旧的接手会话 pilot-coordinator-2 可能仍开着、空闲。

## 进度（program-coordinator-3，2026-10-07 03:35 UTC 追加）
- 第 1 步：#63 已由原协调者合入（PR #66）。
- 第 2–4 步：三份设计经独立审查与 David 批准：#45（design-45-resume-gate.md r3）、#46（design-46-acceptance-records.md r4）、#47（design-47-experience-paths-full.md r4，完整版，含 David 对 Lite 的逐项授权）。实施全部合入 main：PR #67（#45、#55）、#68（#54）、#69（#53）、#70（#46）、#71（#47）；main @ 017aa63，Strict 0.13.0，Lite 1.5.0；回归清单至 R-022。
- 第 5 步进行中：收尾验证 `docs/validation/2026-10-07-orca-closing.md`（事件与度量逐条记录）。Run run_b7ed73396b54；固定包 .pinned-packages/context-strict-017aa63（manifest bf7688fe…86df）；任务 CLOSE-A（ctx_d41ef14f6047）、CLOSE-B（ctx_0a66a2766d6e，派工说明要求发 worker_done 前先 ask 一次——这是中断一：协调者不回复，改用 worker-stop）。
- 下一步：收 A 的 worker_done 后不入账，派新 Claude worker 做接手恢复（中断二）并计数；再入账、派一个 Codex 审核者审 A+B、集成、用 worker_report_handlers 在集成提交上复跑取证、record_acceptance、状态命令确认 still_valid；然后派 Codex 冷读者答六问；写度量对比；开 PR（含协调者在集成时追加的 R-023、R-024）。
- 第 6 步：收尾验证通过后，先整目录备份 ~/.codex/skills/context-strict 与 context-lite，执行前向 David 单独确认。
- 留给后续（已写入各 issue）：gate() 的 brief 预检不含验收小节；align_context 的事件 LOCAL_AHEAD 只查当前任务；PreflightPerformanceTests 峰值内存与 test_experience_rule_gate expired 夹具在 macOS 负载下偶发失败；秘密扫描只认 6 个固定标记；migrate_contract 沿用旧 confirmed_by；#47 F-03（目录名含 CR）；CI 作业 timeout-minutes=5 余量已很小（#71 首次 5m13s 被取消）。
- 待 David：原协调者会话里「14 个子工作树怎么处理」的卡片仍未回答；本程序新增的子工作树（step5-45-*、step6-46*-*、step7-47-*、close-*）也都保留未删。
