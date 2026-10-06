# Orca 试点：协调者接手材料（中断二）

本文件由原协调者（Claude Code 会话，终端 term_1cce21fa-a872-4144-afd0-9a82d17bb3c4）在退出前写下。接手者按下面顺序做，不要凭本文件复述验收标准，一切以封印合同为准。

## 固定事实（绝对路径）
- 协调者工作区：/Users/zhaowei/orca/workspaces/managing-long-task-context/context-skill-for-Orca（main @ 2d9444a；工作区里有未跟踪的 .gitattributes、.githooks/、.prime/、docs/validation/ 两个草稿，都不要删，也不要 git add -A）
- 任务库：<协调者工作区>/.prime/context/PILOT-A/、PILOT-B/，合同已封印：PILOT-A seal sha256:22cc81feba82e97d3119f112b17a1285a788f6c0d5aa9c8bf2bc16f671f6a191；PILOT-B seal sha256:481a695453461557667216a0bc4a6d4873499a8eb0ab8048f533bcd0c47b025a
- 固定包：/Users/zhaowei/orca/workspaces/managing-long-task-context/.pinned-packages/context-strict-00ec012（manifest 9c74752b2d0bc446be4586ac28a8a2be0ab4b0dbfa6fa372728585f1ef1fc913）。所有 Python 调用用 PYTHONPATH=<固定包>/src；不用全局安装的 context-strict。
- 协作规程：<协调者工作区>/references/orca.md；派工模板：docs/agents/orca-pilot/；试点日志（继续往里记）：docs/validation/2026-10-06-orca-pilot.md
- Orca Run：run_0c67c912bb84。派单：PILOT-A = task_78642917f9ac / ctx_765c5986e9d3，工作树 /Users/zhaowei/orca/workspaces/managing-long-task-context/pilot-a-regression-r008；PILOT-B = task_0855b6dccb9f / ctx_6cf322a82957（已 stop 并 release，工作树 /Users/zhaowei/orca/workspaces/managing-long-task-context/pilot-b-skill-api-table，提交 e360fc9）
- 执行者模型规则：Codex gpt-6.1-sol high（David 指定）；审核者也用 Codex gpt-6.1-sol high（David 已定）。派 Codex 前先比对 `codex --version` 与 `npm view @openai/codex version`，有新版直接 `npm install -g @openai/codex`（David 已授权）。

## 已完成
- PILOT-B：报告 /Users/zhaowei/orca/workspaces/managing-long-task-context/pilot-b-skill-api-table/.context-reports/PILOT-B/ctx_6cf322a82957.json 已入账（主条目 C-81f915d326，建议条目 C-31d3e3d9b8），checkpoint 已写。尚未集成、尚未按 AC 核验。
- PILOT-A：执行者已发 worker_done（提交 e810fd7c6640e3b6360e4ffedb1082e7fc66b274，outcome succeeded，报告路径见「接手者要做的」第 3 步），投递批次 delivery_883c859feddd，原协调者**没有 ack、没有入账**。这就是中断二。A 的派单 ctx_765c5986e9d3 终端仍 live（root_completion），接手者决定 release 后再 ack。

## 接手者要做的
1. `orca orchestration run-use --id run_0c67c912bb84 --json`（确切参数看 `--help`），把 Run 绑到你的终端。
2. 用固定包对 PILOT-A、PILOT-B 各做一次 checked_resume（package_root=固定包，workspace_root=协调者工作区，base_dir=<协调者工作区>/.prime/context）。把返回的 diagnostic.status 和 context 是否可用记进日志。
3. `orca orchestration check --json` 读取收件箱：A 的 worker_done 应在重放批次里（原协调者未 ack）。按 references/orca.md「Coordinator: ingest and deduplicate」入账 A 的报告（先查快照里有无同 dispatch id 的主条目，没有才记）。路径按回执推：/Users/zhaowei/orca/workspaces/managing-long-task-context/pilot-a-regression-r008/.context-reports/PILOT-A/ctx_765c5986e9d3.json。
4. 再对 B 的报告跑一遍去重：应发现主条目已存在、建议条目数等于报告条数，于是什么都不写。把结果记进日志（这是「只入账一次」的通过判定）。
5. 在协调者工作区从 main 新建分支 wei0210-bit/pilot-integration，依次 cherry-pick B（e360fc9）和 A 的提交；跑 `python3 -m unittest discover -s tests`、`python3 scripts/sync_context_strict_skill.py && git status --short`；按两份合同的 AC 逐条核验（AC 原文在 task-contract.json）。
6. 用 docs/agents/orca-pilot/dispatch-spec-reviewer.md 派审核者（`--worktree current --agent codex --model gpt-6.1-sol --effort high`），输入：两份合同路径与摘要、基线 2d9444a、集成分支、两份执行者报告路径、你的检查日志。审核者只读；它的报告按同一契约写在 <协调者工作区>/.context-reports/PILOT-REVIEW/<dispatch-id>.json。
7. 入账审核报告；对两个任务各跑一次 completion gate（证据用 file / test-report；若因缺 verifier 得 unknown，如实记为已知缺陷）。
8. 完成试点日志：五项度量汇总、已知缺陷与新发现分栏、Codex 验证范围（执行者与审核者均为 Codex）。把日志和接手文件一起放进集成分支提交，推送并开 PR（标题含 #42）。在 issue #42 评论证据并关闭。
9. Orca 收尾：每个派单 reuse/retain/release 决定后再 ack；PILOT-B 的 Task 当前是 stopped，工作已有报告，用 `task-update --help` 看能否标记结果，不能就在日志里写明。

## 原协调者遗留
- 与 Orca 的三个旧工作树 issue-37/38/39 一样，pilot-a、pilot-b 工作树都不要删（删除要 David 审核）。
