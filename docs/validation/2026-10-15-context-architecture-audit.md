# Context Skill 运行架构审计（Strict + Lite）

- 日期：2026-10-15（Asia/Shanghai）
- 方法：
  - ECC `agent-architecture-audit`：只看上下文架构，不评价模型本身
  - ECC `context-budget`：安装时固定成本 + 运行时预算模型
- 审计基线：
  - 架构部分以 `851a7db`（Strict 1.0.0，PR #86）为基线
  - 预算部分在 `70f647e`（Strict 1.1.0，PR #87）上实测
  - PR #87 只新增 `scripts/context_search.py`，没有改 `src/`，所以 `brief` 和恢复相关结论对两个提交都成立
  - 基线之后合入的 #87、#88、#89 见「基线之后的变化」
- 性质：只读审计。没有改代码，没有跑测试套件。所有运行时测量都在临时目录里的账本副本上执行。结论是观察，不是验收；标注「推断」的条目未实测
- 2026-10-15 补注：
  - 新增「现状」「待办总表」「接手须知」三节，并在正文相关处加「补注」，供下一个会话接着做
  - 补注里的状态是当天用 `git`、`gh` 和账本读回的，那时 `origin/main` = `70f647e`
  - 审计原文的结论没有改动
- 判定规则：
  - 每个机制回答「没有它，会坏什么？」；答不出明确故障模式的，默认建议删除
  - 预算部分不追求「信息一个都不能丢」，只要求「下一步决策需要的信息不能丢」

## 结论

代码里没有隐藏的 LLM 调用、重试或修复循环，也没有「摘要的摘要」：`brief` 只读，从不把输出写回账本。

真正的问题有四处：

1. 验收重复。同一任务反复验收，Reviewer 重跑 Worker 已跑过的全量测试；返修轮次在账本里看得见。
2. 过期信息被当成当前。过期事实留在 `brief` 正文里，过期文档标着「当前权威」，search 返回已退役的内容时不加标记。
3. 没人用的机制。约 2,500 行代码（全仓约 9,400 行）在 42 个真实账本里从未使用过，或者在 `src/`、`scripts/` 里没有调用方。
4. 运行时给的上下文大多不是下一步需要的：
   - Strict 恢复（`checked_resume`）每次中位约 6,000 tokens，下一步决策真正需要的部分中位约 410 tokens，约占 7%
   - Lite 唯一的真实记录，用官方 `resume` 恢复时拿到 0 条可用上下文
   - Reviewer 实际在读全部日志（单个审核目录约 75,000 tokens）

## 现状（2026-10-15 核对）

`origin/main` = `70f647e`，main 上最新一次 CI（运行 38596387943）为 success。仍开着的 PR 只有 #29（`cursor/strict-0.8.7-global-install-3249`），2026-09-24 以后就没动过。

### 已完成

| 事项 | 结果 | 证据 |
|---|---|---|
| 减法设计与两轮工程评审 | 方案 B（三类清单真删）获批；第二次评审 R12–R23 已无未决项 | `docs/designs/context-skill-subtraction.md`、`docs/designs/context-skill-remaining-gaps-handoff.md`（都还没入库） |
| T1 + router 同步 | #88 合并为 `a801bc3`：修好 macOS 上的 truth source 示例；router 删掉 `frozen_acceptance`、`independent_validation`；新增 R-043、R-044 | 账本 `CI-COVERAGE`，`evidence/pr88/` |
| T3、T4、T5 + 合并常设授权 | #89 合并为 `6e2fb58`，内容如下：<br>• CI 跑回归清单，R-004 测试数下限设为 444<br>• macOS 上系统 `python3`（3.9）和 3.12 各跑一次全量<br>• 新增 `docs/agents/quality-floor.json`（`ci_coverage`）<br>• 重新设立 `docs/agents/standing-authorizations.json`（SA-MERGE-PR、SA-PUSH-DEFAULT）<br>• 新增 R-045 | 账本 `CI-COVERAGE`，`evidence/pr89-08ad63c/` |
| T6 全局规则 | `~/.claude/CLAUDE.md:49`、`~/.codex/AGENTS.md:47` 已改写：声明了 `ci_coverage` 的项目，执行方只跑定向命令，审核方跑定向测试并逐条判定人工回归条目，以 PR 头提交的 CI 为准，协调者不再本地复跑。`check_shared.py` 通过 | 账本 `CI-COVERAGE` C-12a0ad99a0；改前备份 `*.bak-20261014-ci-coverage` |
| T2 + #87 合并 | `70f647e`（Strict 1.1.0）带上了重建标记和非 UTF-8 两处修正及测试；经第三轮复审 PASS 后，由协调者按 SA-MERGE-PR 合并 | 账本 `CONTEXT-SEARCH` CP-08ed604c41 |
| T7 真实 CI 证据登记 | 验收记录 AR-5d71fc4f9fe6ae0c：`decision=pass`、`reproducible=true`，证据为 CI 运行 38592311987 和复审 `ctx_635241d419c2`（`code_revision` 是 PR 头提交 `4d63796`） | `.prime/context/CONTEXT-SEARCH/acceptance-records.jsonl` |
| Strict 1.1.0 全局重装 | 装在 `~/.codex/skills/context-strict`（`~/.claude/skills/context-strict` 是指向它的链接），manifest `a77b2092…`；两个入口的 verify 和 doctor full 均 pass；旧的 1.0.0 移到 `~/.codex/skills-backup-20261014T161654/` | 账本 `CI-COVERAGE` C-278db9ad85、CP-5ae20798b8 |
| 外部复核超时 | 根因是 PATH 上的旧版 Codex CLI 0.148.0 排在前面；已升级到 0.162.1 | 设计文档「Outside voice」一节 |

Lite 2.0.0 在仓库里和已安装的版本一致，这轮没有改。

### 未完成

- 设计文档的 T8（试点分组表）和 T9（检索里对私有函数 `context._rebuild_snapshot` 的调用、读事件时加锁）。
- 本审计的「修复顺序」1–8：只有第 1 项里的全局规则改写已由 T6 完成，其余都没开始。
- 上一会话留下的后续项和清理项。
- 以上全部按优先级列在「待办总表」。

## 实际用量（基线 `851a7db`，`.prime/context/` 共 42 个账本）

| 事件类型 | 次数 | 涉及任务数 |
|---|---|---|
| `item-recorded` | 240 | 42 |
| `checkpoint-recorded` | 107 | 42 |
| `contract-published` | 64 | 42 |
| `item-updated` | 17 | 9 |
| `truth-source-observed` / `truth-source-dirtied` | 0 | 0 |
| `item-externalized` | 0 | 0 |

- 18 个任务有验收记录，19 个任务有 `evidence/` 目录，`contract-history/` 共 21 份
- 经验库 `.prime/experience/records.json` 只有 1 条候选（`orca-takeover-binding-001`），从未审核
- 最大的账本 `W1-P1` 有 32 个事件、约 35 KB 的 `events.jsonl`
- `.context-reports/` 约 1.5 MB；Lite 只有一条记录 `.context-lite/ctx-subtraction-review/`

## 发现（按严重度）

### High 1：Worker → Reviewer 重复验证，形成返修循环

- 旧 Reviewer 模板 `docs/agents/orca-pilot/dispatch-spec-reviewer.md` 要求「重新核对执行方每一条关键声明」。留存报告里，`unittest discover -s tests` 全量出现 14 次；`PILOT-REVIEW` 的两份审核各跑一次全量，同时还读了集成日志。
- 返修轮次：
  - W1-P1：验收 `ACCEPT`、`ACCEPT-v2`、`ACCEPT-FINAL` 共 3 轮，10 个检查点
  - W3-FOLLOW：验收目录编到 `-v4`，合同改到 v4
  - W3-LEASE：两轮验收，10 条命令相同
  - IMP-INTEGRATION-V2：6 份协调者报告
  - 42 个任务里合同共发布 64 次
- 根源在执行规则，不在 Strict 代码：
  - `~/.claude/CLAUDE.md` 第 49 行「四层验收」（设计文档 G1）
  - `origin/main` 上重新设立的 `docs/agents/standing-authorizations.json` 中 SA-MERGE-PR 的条件：每个任务都要有审核 PASS 和 `decision=pass`、`reproducible=true` 的验收记录，且「头提交变化须重新审核与验收」
- 没有它会坏什么：Reviewer 不重跑，故障模式是执行方日志可能不实。但 CI 现在已在 PR 头提交上跑全量（见「基线之后的变化」），这个故障模式已经由 CI 兜底。重跑本身没有剩下的独有价值，建议删除，改为引用 CI 运行。
- 补注（2026-10-15）：
  - 上面说的全局规则「四层验收」已由 T6 改写。本项目声明了 `ci_coverage`：审核方只跑定向测试，逐条判定人工回归条目；协调者不再本地复跑。`CLAUDE.md:49` 里四层验收只剩「其他项目」那一支。
  - 规则层面剩下的返修来源有两处，都在 SA-MERGE-PR：「头提交变化须重新审核与验收」，以及每个任务都要有独立审核 PASS。
  - 实际情况：#87 在 T6 之后仍经过三轮复审才合并（`CONTEXT-SEARCH` CP-08ed604c41）。各轮是不是由真实缺陷引起的，没有逐轮核实。

### High 2：过期事实照样作为当前事实提供

- `brief()` 只过滤 `status == "superseded"`（`src/managing_long_task_context/__init__.py:1998-2000`）。
- 过期的可变事实仍然放在 `facts`、`decisions` 等正文分组里，只把 ID 另列在 `stale_items`（`__init__.py:2026-2037`，渲染在 `2628-2633`）。
- 故障模式：agent 按正文读事实时，会把过期事实当现行事实用。修法：过期条目移出正文，只列在需要重新观察的清单里。

### High 3：标着「当前权威」的文档其实已经过期

- 根 `CONTEXT.md` 标 `authority: AUTHORITATIVE_NOW`，但 `baseline_head: 5c7827f`，而基线 HEAD 是 `851a7db`，`origin/main` 是 `6e2fb58`。
- `docs/designs/context-skill-subtraction.md` 有 2,126 行。开头一节「剩余差距」声明以它为准，正文仍保留分阶段计划、30 条 Reviewer Concerns、Eng Review 和 R1–R11 决策台账。每个接手者都要通读并自己判断哪些失效，这就是「Coordinator 重复整理同一份资料」。
- Lite 记录 `ctx-subtraction-review` 停在「等协调会话确认收到」（RUN-01 pending），从未 finish，是跨会话残留的旧状态。
- `scripts/context_search.py`（PR #87）把已退役的内容当作有效结果返回，且不加标记：
  - 搜「协调者租约」（#86 已退役），前 10 条依次来自 `docs/regression-checklist.md` 的退役条目（4 条）、设计文档的历史段落（4 条）、W3-LEASE / W3-FOLLOW 的旧合同（2 条）
  - 结果字段只有 `path`、`line`、`snippet`、`score`、`index_built_at`、`index_stale`、`degraded`、`file_mtime`，没有「当前 / 历史」标记
  - 好的一面：search 返回的是「路径 + 行号 + 片段」，按引用而不是复制，方向是对的

### High 4：Coordinator → Worker 没有现行通道，旧模板复制而不是引用

- `docs/agents/orca-pilot/dispatch-spec-{executor,reviewer,cold-reader}.md` 和 `pinned-package.md` 都标了 HISTORICAL_ONLY，但仍指向已删除的 `references/orca.md`。`scripts/sync_context_strict_skill.py` 也还引用这个文件。
  - 补注（2026-10-15）更正：
    - 实际指向 `references/orca.md` 的只有 `dispatch-spec-executor.md`、`dispatch-spec-cold-reader.md`、`pinned-package.md` 三份，`dispatch-spec-reviewer.md` 没有。
    - `scripts/sync_context_strict_skill.py:71` 那处在 `REMOVED_FILES` 清单里，作用是重新生成包时清掉旧副本。这是有意保留的，不是悬空引用，不要删。
- 三份模板里「Task and acceptance」「Pinned runtime」「Durable report and settlement」三节逐字相同。每次派工都要：
  - 把验收标准逐字抄进派工正文，同时要求 Worker 打开原合同再读一遍，同一份信息走两条渠道
  - 每个 Worker 重新校验封印摘要
  - 每个 Worker 重新跑一遍运行时身份证明
- 现行指引 `references/agent-role-handoff.md` 与 `references/bot-pipeline-handoff.md` 字节相同，且只要求「传绝对路径」，和旧模板矛盾。

### Medium 5：`gate` 和证据解析是一整套死代码

- `gate()` 固定返回 `decision="unknown"`、`blocking=False`，每条验收标准固定为 `unknown` / `EVIDENCE_NOT_VERIFIED`（`__init__.py:3020-3030`、`3065-3067`）。
- 被接受但从不使用的参数：
  - `gate` 的 `resolvers`、`verifiers`、`**legacy_options`（`__init__.py:3020-3023`）
  - `evaluate_evidence` 的 `resolvers`、`verifiers`（`evidence.py:285-286`）
  - `record_acceptance` 的 `resolvers`、`verifiers`、`validation_resolver`、`rule_runtime`（`acceptance.py:418-419`）
  - `checked_resume` 的 `**legacy_options`（`runtime_identity.py:103`）
- 定义了但从未引用：`GATE_STAGES`（`__init__.py:90`）。
- 没有调用方：`worker_report_handlers()`（`worker_report.py:138`）和 `runtime_evidence_handler_errors()`（`evidence.py:204`）在 `src/`、`scripts/` 里都没人调用，只有测试用到。`scripts/coordinator_ops.py` 只 import，不调用。`evidence.py` 里约 640 行 `_resolve_*` 因此永远不会执行。
- `record_acceptance()` 没有传入 `acceptance_report` 时，会走 `gate`（`acceptance.py:436-437`），而 `gate` 永远给不出通过。SA-MERGE-PR 又要求 `decision=pass`，所以协调者只能手工构造 `acceptance_report`。
- 没有它会坏什么：没有明确故障模式。函数名 `gate` 反而让 agent 以为存在一道放行关口。建议删除。

### Medium 6：Strict 的恢复一次读两遍账本

- `checked_resume` 先调 `brief`，再调 `gate(stage="resume")`（`runtime_identity.py:109-125`）。真实账本从未启用 truth source 时，`brief` 走快照快路径；`gate` 仍要装载账本再做一次审计。
- 没有 `gate` 这一步会坏什么：没有故障。它不阻断，也只能给出 unknown。建议删除这一调用。

### Medium 7：Lite 的身份绑定让低风险恢复失败（已在真实记录上确认）

- Lite `resume` 在身份检查不通过时返回 `context: null`，`skills/context-lite/SKILL.md` 还写明「不要静默重新绑定」。
- 实测（2026-10-15，已安装的 Lite 2.0.0）：

  ```sh
  python3 ~/.claude/skills/context-lite/scripts/context_lite.py resume \
    --package-root ~/.claude/skills/context-lite \
    --context-root <repo>/.context-lite --workspace-root <repo> \
    --task-id ctx-subtraction-review
  ```

  - 退出码 2，`diagnostic.codes = ["BINDING_MISSING"]`，`context: null`
  - 约 350 tokens 全是诊断，530 tokens 的 `NOW.md` 一行都没给
- 按 `_identity_core.py:279-344` 推断（未实测）：绑定建立之后，Lite 包每次更新都会改变 manifest 哈希，恢复会报 `PACKAGE_IDENTITY_MISMATCH` 并返回空，直到有人手动 `init-binding`。
- 这个机制在低风险场景里制造了一个故障。建议改成只报告、不阻断。

### Low 8：小处的重复

- Lite `NOW.md` 模板的「Refresh On Resume」一节，和 `STATE-*`、`RUN-*` 条目里已有的 `refresh_ref` / `recovery_ref` 重复。
- 同一件事（减法改造）的状态同时存在五个地方：`STRICT-LEDGER` 账本、根 `CONTEXT.md`、设计文档、Lite `NOW.md`，以及 `~/.gstack/projects/wei0210-bit-managing-long-task-context/checkpoints/` 下 2026-10-14 的两份检查点。没有一处指明哪一处为准。

## 逐机制判定：没有它，会坏什么

### 1. 获取

| 机制 | 用量 | 没有它会坏什么 | 建议 |
|---|---|---|---|
| `record` / `update_item` | 257 次 | 账本不存在 | 保留 |
| `observe_truth_source` / `mark_truth_sources_dirty`（`truth_sources.py` 635 行及 `__init__.py` 相关代码） | 0 次 | 无观察到的故障 | 删除 |

### 2. 选择

| 机制 | 用量 | 没有它会坏什么 | 建议 |
|---|---|---|---|
| `brief` 的预算与省略清单 | 每次恢复都调用 | agent 要么读全历史，要么悄悄漏掉必读项 | 保留，修过期过滤（High 2） |
| `brief` 每次都带完整验收标准 | 每次调用 | 验收标准是固定开销，过长时一个条目都选不进（`__init__.py:2291-2310`） | 改为只带合同路径和摘要 |

### 3. 压缩

| 机制 | 用量 | 没有它会坏什么 | 建议 |
|---|---|---|---|
| `externalize_item` / `restore_externalization_controls` | 0 次 | 账本最大才 35 KB，没有故障 | 删除 |
| 检查点（只渲染最新一个） | 107 次 | 不知道下一步做什么 | 保留 |

### 4. 持久化

| 机制 | 用量 | 没有它会坏什么 | 建议 |
|---|---|---|---|
| `events.jsonl` | 全部任务 | 无法还原历史 | 保留 |
| `snapshot.json` | 全部任务，内容与事件日志近乎重复 | 最多 32 个事件，全量重放可以忽略 | 低优先级删除 |
| `contract-history/` | 21 份 | 看不到合同改了什么，`contract_diff` 失效 | 保留 |
| 证据内容寻址副本 `evidence/<sha256>` | 19 个任务 | 许多 ACCEPT 目录已从工作树删除，只剩这份副本 | 保留 |
| `usage_freshness.py`（232 行） | 只有测试和同步脚本引用 | 无故障 | 删除 |

### 5. 恢复

| 机制 | 用量 | 没有它会坏什么 | 建议 |
|---|---|---|---|
| Strict 运行时身份诊断 | 固定版本试点用过 | 加载到错误的包版本 | 保留在 `context_doctor.py` |
| `checked_resume` 中的 `gate` | 每次恢复 | 无故障 | 删除（Medium 6） |
| Lite 阻断式身份绑定 | 1 个 Lite 任务 | 防的是包版本错配，但包更新后自己会导致无法恢复 | 改为只报告、不阻断 |

### 6. 会话交接

| 机制 | 用量 | 没有它会坏什么 | 建议 |
|---|---|---|---|
| Lite `cold-check`（两次读取 + sha 比对） | 未见使用 | 只防单 agent 下少见的读写竞态 | 合并进 `resume --expected-now-sha256` |
| Lite `flush` | 未见使用 | 它就是 `write` 的别名 | 删除 |
| 两份相同的 handoff 文档 | — | — | 合并为一份 |

### 7. Coordinator → Worker

| 机制 | 用量 | 没有它会坏什么 | 建议 |
|---|---|---|---|
| 合同绝对路径 + 封印摘要 | 每次派工 | 拿到过期或错误版本的合同 | 保留 |
| 验收标准逐字抄进派工 | 每次派工 | 无故障，原合同是唯一真源 | 删除 |
| 每个 Worker 重证运行时身份 | 每次派工 | Coordinator 派工前证一次就够 | 改为派工前做一次 |

### 8. Worker → Reviewer

| 机制 | 用量 | 没有它会坏什么 | 建议 |
|---|---|---|---|
| 报告指针 + 摘要（`acceptance-records.jsonl`） | 18 个任务 | 报告被悄悄替换 | 保留 |
| Reviewer 重跑全量 | 留存报告中 14 次 | CI 已在 PR 头提交上跑全量 | 删除，改为引用 CI 运行 |
| 「头提交变化须重新审核与验收」（SA-MERGE-PR） | 每次 rebase | 审核结论绑定到具体提交，这个故障模式是真的 | 收窄：只有改动触及已审文件时才重审 |

### 其他

| 机制 | 用量 | 没有它会坏什么 | 建议 |
|---|---|---|---|
| 经验库（`experience.py` 175 行、`_experience_store.py` 819 行，CLI 复制 3 份） | 1 条候选 | 默认恢复路径不读它 | 删除 |
| `scripts/context_skill_router.py` | 只有测试 | 两份全局规则「Context skill 自动路由」写着「判定同 `…/context_skill_router.py`」，删掉后规则会指向不存在的文件 | 补注（2026-10-15）：改为保留。David 2026-10-14 刚要求同步它（#88）；若仍要删，须 David 决定，并同时改两份全局规则 |
| `publish_context` / `align_context` | 未核实 | 多个 checkout 无法共享账本 | 保留，待确认是否在用 |

## 上下文预算：安装时与运行时

估算口径：中日韩字符每字算 1 token，其余字符每 4 个算 1 token。运行时数据来自 42 个真实账本的副本，在 `70f647e` 的 `src/` 上调用 `brief`、`gate`、`checked_resume` 测得。

### 安装时（固定成本）

| 组件 | Token |
|---|---|
| Strict `SKILL.md`（1.1.0，与 `~/.claude/skills/context-strict/` 已安装副本一致） | 约 1,800 |
| Lite `SKILL.md`（2.0.0） | 约 3,000 |
| 项目 `CLAUDE.md` + `AGENTS.md` | 约 560 |
| Strict references（两份 handoff 文档字节相同，各约 220） | 约 820 |
| Lite `references/short-session.md` + `assets/NOW.template.md` | 约 590 |
| gstack 的 context-save / context-restore（调用时才加载） | 每份 11,000–14,000 |

- 全局规则（`~/.claude/CLAUDE.md`「Context skill 自动路由」）要求新会话的第一个实质任务就加载 Strict 或 Lite，所以几乎每个会话都固定付出 1,800 或 3,000 tokens。
- Lite 的说明文字（约 3,000）是它管理的真实状态（`NOW.md` 约 530）的 5.6 倍。
- 同一件事的上下文有三套保存机制：Strict 账本、Lite `NOW.md`、gstack 检查点。gstack 调用一次就是 Lite 的 4 倍成本，三套之间互不引用。

### 运行时实测

| 操作 | 中位 | 最大 |
|---|---|---|
| 原始 `events.jsonl` | 2,200 | 9,400 |
| 合同 `task-contract.json` | 1,500 | 4,500 |
| 验收标准完整对象 | 520 | 1,800 |
| 其中旧执行字段（`worker_report_claim`、`required_hops` 等） | 220 | 1,500 |
| `brief` 的 `prompt` 文本 | 2,300 | 3,500 |
| `brief` 完整返回值（`prompt` + 内容相同的结构化字段） | 5,500 | 8,200 |
| `gate(stage="resume")` 报告 | 430 | 610 |
| `checked_resume`（`brief` 完整返回值 + gate 报告 + 身份诊断） | 6,000 | 9,000 |
| 下一步决策核心（见下文定义） | 410 | 1,470 |
| 一次 search（20 条结果，每条约 80–200） | 1,600–2,000 | — |
| Worker 单个报告（`.context-reports/` 下 19 份） | 900 | 19,700 |
| Reviewer 能读到的日志（206 个文件合计约 102,000） | 33 | 22,700 |
| 其中 `PILOT-REVIEW`（38 个日志） | — | 约 75,000 |
| Lite 官方 `resume` | 350（全是诊断，见 Medium 7） | — |

「下一步决策核心」的定义：objective、验收标准的 id 和正文、当前阶段、最新检查点的下一步和阻塞项、未决问题和冲突、生效中的决策、过期条目 ID、最新检查点的证据指针。

### 预算上的浪费（按可省 token 排序）

1. 恢复时同一内容付三遍。`checked_resume` 同时返回渲染好的 `prompt`、内容相同的结构化字典和 gate 报告（`runtime_identity.py:109-125`）。模型只需要其中一份，结构化数据留给代码用。每次恢复约可省 5,500 tokens。
2. 「摘要」比原文还大。`brief` 完整返回值中位 5,500，它概括的事件日志中位才 2,200。账本这么小的时候，`brief` 起不到压缩作用。
3. 没法按「下一步需要什么」来选。42 个任务的最新检查点里，`related_item_ids` 全部为空。`brief` 只能按类型和时间排序（`__init__.py:1928-1952`），判断不了哪些事实与下一步有关。
4. 验收标准里夹着旧执行字段，每次 `brief` 都带着，体积和验收标准正文相当。约束字段还整段内嵌授权 JSON（例如 STRICT-LEDGER 的 `DAVID_AUTH`），放一个指针就够了。
5. Reviewer 读全部日志。正常情况下只需要验收标准、diff 指针、CI 运行结论和执行方声明表（命令、退出码、日志摘要），约 2,000 tokens。日志只在发现不一致时才需要读。
6. Lite 的上限按字符计，不按 token 计。`NOW.md` 上限 8,000 字符：纯英文约 2,000 tokens，纯中文可到约 8,000 tokens，同一条规则对中文宽了 4 倍。
7. search 默认 20 条且不分当前与历史（见 High 3）。

### 建议的运行时预算模型：以下一步决策为准

下一步决策包是给模型看的唯一恢复文本：

| 段 | 内容 | 上限（tokens） |
|---|---|---|
| 身份 | task id、合同路径、版本、摘要 | 约 40 |
| 目标 | objective，不超过 2 行 | 约 80 |
| 完成标准 | 验收标准的 id 和正文；超限时只给 id 和指针 | 600 |
| 现状 | 当前阶段，只给最近一次检查点的完成项 | 约 80 |
| 下一步 | 唯一的下一步、阻塞项 | 约 80 |
| 必须知道 | 未决问题、冲突、约束下一步的决策、需重新观察的过期项 | 300 |
| 指针 | 最新证据引用、被省略条目数、检索提示 | 约 60 |

- 目标约 800 tokens，硬上限 1,500。超限时先保住「完成标准」「下一步」「必须知道」三段，其余段压缩。
- 一律不进入决策包：
  - 与 `prompt` 内容重复的结构化字段
  - 验收标准里的旧执行字段
  - gate 报告
  - 身份检查通过时的诊断（只在失败时输出）
  - 已被取代的事实、旧检查点的叙述、原始日志

选入规则：某个条目只有满足下列之一才进入决策包，其余只保留 ID 和指针，需要时通过 search 拉取。

- 被下一步引用：下一步依赖某些事实时，检查点必须填 `related_item_ids`。
- 尚未解决：问题、冲突或阻塞。
- 生效中且约束下一步的决策。
- 已过期且被下一步引用：放进需要重新观察的清单，不放进正文（与 High 2 的修法一致）。

各角色上限：

| 角色 / 时机 | 预算 | 现状 |
|---|---|---|
| Coordinator 恢复 | 1,500 | 中位 6,000，最大 9,000 |
| Worker 开工 | 合同路径和摘要，加决策包里的范围、约束、验收标准切片，共 1,500；派工正文不再逐字抄验收标准 | 约 3,000–3,500（模板 + 抄写的验收标准 + 再读一遍合同） |
| Reviewer | 2,000；日志只在不一致时读 | 报告最大 19,700，单个审核目录日志约 75,000 |
| Lite 恢复 | `NOW.md` 不超过 2,000 tokens；身份检查失败只报告、不阻断 | 当前拿到 0 |
| search | 默认 10 条约 1,000；带「当前 / 历史」标记，当前优先 | 20 条约 2,000，无标记 |

可以丢的（下一步决策不需要）：旧检查点的叙述、已被取代的事实、失败验收轮次的日志正文（证据库里保留摘要即可）、验收标准里的旧执行字段、内嵌的授权 JSON 全文。

预期节省：

- `checked_resume` 只交决策包：每次恢复约省 5,500 tokens（约 90%）。若按每个检查点对应一次恢复粗算，42 个任务的 108 个检查点合计约省 600,000 tokens（这是假设，没有恢复次数的实测）。
- Reviewer 改为「声明表 + CI 结论」，日志按需读：单次审核省 10,000–75,000 tokens。
- Lite 身份检查不阻断、上限按 token 计：唯一的真实记录能用约 530 tokens 恢复（现在是 0）；中文记录的最坏情况从约 8,000 降到约 2,000。

## 基线之后的变化（`851a7db..70f647e`）

- #87（`70f647e`，Strict 1.1.0）：新增 `scripts/context_search.py`，在 `.prime/search/index.sqlite` 建可重建的全文索引；`SKILL.md` 增加 13 行用法。没有改 `src/`。预算与标记问题见上一节和 High 3。
- #88：修了 macOS 上的 truth source 示例，router 删掉 4 行已退役信号。
- #89：CI 在每个 PR 上跑：
  - Ubuntu：回归清单（含 R-004 全量），以及打包后 Strict、Lite 包的测试
  - macOS：系统 `python3`（3.9）和 Python 3.12 各跑一次全量
- 新增 `docs/agents/quality-floor.json`，声明 `full_suite: true`、`regression_checklist: true`。
- 重新设立 `docs/agents/standing-authorizations.json`（SA-MERGE-PR、SA-PUSH-DEFAULT）。

对本文的影响：

- High 1 的「CI 只跑一次全量」已经落地，所以 Reviewer 重跑可以直接删。但 SA-MERGE-PR 仍要求每个任务都有审核和验收记录，且头提交一变就全部重来。返修循环的来源从全局规则延伸到了这份文件。
- 每个 PR 上根测试套件跑 3 次（3 个解释器）。这有明确故障模式（macOS 系统 `python3` 上出过问题），保留。打包测试是另一条故障线（生成的包缺文件），也保留。
- 审计进行中，另一会话于 2026-10-15 00:14 把本工作树快进到 `70f647e`；之后的测量都在 `70f647e` 上完成。

## 修复顺序（先改代码，后改提示文字）

1. 停掉返修循环：Reviewer 引用 CI 运行，不再重跑全量；收窄 SA-MERGE-PR 的「头提交变化须重新审核与验收」；改写全局规则「四层验收」（G1）。改全局规则和常设授权须 David 直接授权。（补注：全局规则部分已由 T6 完成；SA-MERGE-PR 的收窄还没做，见待办 W1。）
2. 恢复只交下一步决策包：
   - `checked_resume` 给模型的文本只留决策包，不再附带重复的结构化字段和 gate 报告
   - `brief` 把过期的可变事实移出正文分组
   - 验收标准只带 id 和正文，不带旧执行字段
   - 检查点在下一步依赖具体事实时填 `related_item_ids`
   - 硬上限 1,500 tokens（见「建议的运行时预算模型」）
3. 派工改为只传合同路径和封印摘要；运行时身份由 Coordinator 在派工前证一次。删除或重写 `docs/agents/orca-pilot/`，修掉 `references/orca.md` 的悬空引用，两份 handoff 文档合并。Reviewer 只读声明表和 CI 结论，日志按需读。
4. 删除死代码：`_resolve_*` 解析器、`worker_report_handlers`、`runtime_evidence_handler_errors`、被忽略的参数、`GATE_STAGES`；`record_acceptance` 改为必须传入 `acceptance_report`；`checked_resume` 不再调 `gate`。
5. 删除零使用的功能：truth source、externalize / restore、`usage_freshness`、经验库、router。按仓库约束，相关回归条目只标 `Retired (#issue, reason)`，每项单独取得授权。（补注：router 改为保留，理由见「逐机制判定 · 其他」。）
6. Lite 精简：
   - 身份检查改为只报告、不阻断
   - `NOW.md` 上限改按 token 计（约 2,000）
   - `cold-check` 合并进 `resume`，删除 `flush`
   - 模板去掉「Refresh On Resume」
7. search 结果加「当前 / 历史」标记，当前优先，默认 10 条。
8. 清理过期文档：更新或去掉 `CONTEXT.md` 的 `baseline_head`；设计文档只留「剩余差距」，其余移入历史；`ctx-subtraction-review` 执行 finish 归档。同一任务的上下文只认一个真源（多 agent 用 Strict 账本，单 agent 用 Lite），gstack 检查点不再重复记录同一任务。最后再考虑去掉 `snapshot.json`。

## 待办总表（2026-10-15）

建议顺序：

1. 先向 David 申请需要授权的 W1、W5。
2. 同时做不需要授权的 W2 和 W7。W3 和 W2 改的是同一批文件，排在同一条执行线上，接在 W2 之后。
3. 然后做 W6、W4、W8。
4. 其余按需。W9 要排在 W6 之后：W6 的完成标准就是拿 `ctx-subtraction-review` 这条记录测恢复，先归档就没有测试对象了。

| 编号 | 事项 | 来源 | 须 David 直接授权 | 完成标准 |
|---|---|---|---|---|
| W1 | 收窄 SA-MERGE-PR 的「头提交变化须重新审核与验收」：只有改动触及已审文件时才重审。审核改为引用 CI 运行，不再重跑全量 | High 1、修复顺序 1 | 是（改常设授权） | R-045 会检查条件关键词，同步更新后通过；PR 上 CI 全绿 |
| W2 | 恢复只交下一步决策包：<br>• `checked_resume` 给模型的文本只留决策包<br>• `brief` 把过期的可变事实移出正文<br>• 验收标准不带旧执行字段<br>• 检查点填 `related_item_ids`<br>• 硬上限 1,500 tokens | High 2、修复顺序 2、预算模型 | 否 | 先写复现测试（过期事实不在正文分组，决策包不超上限），由红转绿；两个解释器全量通过；回归清单全过；Strict 升版本 |
| W3 | `checked_resume` 不再调 `gate`。删除死代码：`_resolve_*`、`worker_report_handlers`、`runtime_evidence_handler_errors`、被忽略的参数、`GATE_STAGES`。`record_acceptance` 改为必须传 `acceptance_report` | Medium 5、Medium 6、修复顺序 4 | 退役回归条目时是 | 同 W2 |
| W4 | 派工通道：<br>• `docs/agents/orca-pilot/` 下 `dispatch-spec-executor.md`、`dispatch-spec-cold-reader.md`、`pinned-package.md` 仍指向已删除的 `references/orca.md`，这几份删除或重写<br>• 两份字节相同的 handoff 文档合并为一份<br>• `scripts/sync_context_strict_skill.py:71` 的 `references/orca.md` 在 `REMOVED_FILES` 清理清单里，保留不动 | High 4、修复顺序 3 | 删除历史文档时是（属证据） | 打包的 check-source、build、verify 通过；`grep -rln 'references/orca.md' docs` 无结果 |
| W5 | 删除零使用功能：truth source、externalize / restore、`usage_freshness`、经验库。router 保留 | 修复顺序 5 | 是，每项单独授权 | 回归条目只标 `Retired (#issue, reason)`；全量测试和打包测试通过 |
| W6 | Lite 精简：<br>• 身份检查只报告、不阻断<br>• `NOW.md` 上限按 token 计（约 2,000）<br>• `cold-check` 并入 `resume`，删除 `flush`<br>• 模板去掉「Refresh On Resume」 | Medium 7、Low 8、修复顺序 6 | 否 | 对真实记录 `ctx-subtraction-review` 跑 `resume` 能拿到 `NOW.md` 内容（现在是 0 条）；Lite 升版本 |
| W7 | 检索结果加「当前 / 历史」标记，当前的排在前面，默认 10 条（现在 `scripts/context_search.py:320`、`:401` 默认 20 条）。顺带做 T9：不再调私有函数，读事件时加锁 | High 3、修复顺序 7、T9 | 否 | 搜「协调者租约」时，退役内容带历史标记并排在当前内容之后；`PYTHONPATH=src:tests python3 -m unittest tests.test_context_search` 通过 |
| W8 | 清理过期文档：<br>• `CONTEXT.md` 头部仍是 `baseline_head: 5c7827f`、`package_version: 1.0.0`<br>• 设计文档只留「剩余差距」，其余移入历史<br>• 同一任务只认一个真源 | High 3、Low 8、修复顺序 8 | 删除或移走历史段落时是 | `CONTEXT.md` 头部与 `origin/main` 一致 |
| W9 | Lite 记录 `ctx-subtraction-review` 还停在 RUN-01 pending。协调会话后来已按评审结果实施（#88、#89、#87），可以执行 finish 归档 | High 3 | 否 | 对这条记录跑 Lite `resume`，不再显示在途项 |
| W10 | `skills/context-lite/SKILL.md:53` 和根 `SKILL.md:21`（「Use Strict automatically for … frozen-acceptance …」）仍把 frozen acceptance、independent validation 当作 Strict 触发条件，与 router 和全局规则不一致 | 上一会话后续项 | 否 | 文字与 router 的 `STRICT_TRIGGERS` 一致，并用同步脚本重新生成包 |
| W11 | T8：建试点分组表，分基线组、#86 后组（含检索 PR）、G1 后组，口径按设计文档 D8、D12 | 设计 T8 | 否 | 表格入库 |
| W12 | 回归清单两处：<br>• R-004 失败时只打印最后 3 行，看不到失败原因，改为打印完整输出<br>• R-045 只做字符串检查，措辞一改就可能失效 | 上一会话后续项 | 是（改回归清单） | 回归清单全过 |
| W13 | `tests/test_experience_distribution.py:46` 的子进程超时只有 60 秒。2026-10-14 本地跑 R-004 时它超时失败过一次；换成内置盘 `TMPDIR` 重跑，444 个测试全部通过。疑与机器负载或外接盘 `TMPDIR` 有关，未证实 | 上一会话后续项 | 调大超时等于放宽测试，先问 | 全量连续两次通过 |
| W14 | 清理（都在本机，都是删除）：<br>• 旧 Codex 版本，约 750 MB<br>• Strict 1.0.0 的备份 `~/.codex/skills-backup-20261014T161654/`（1 MB）<br>• 重装用的临时目录 `/Volumes/DavidDisk/project/_agent-storage/tmp/strict-reinstall-20261015/`（5 MB）<br>• `git worktree list` 里 7 个 prunable 工作树，以及已合并分支的工作树（`claude-ci-coverage`、`claude-macos-router`、`context-search`、`context-search-review`）<br>• 本地和远端共 166 个分支<br>• 旧 PR #29 | 上一会话后续项 | 是（删除） | — |
| W15 | 主工作树里还没入库的文件：<br>• `docs/designs/` 和本报告：已开 PR 提交（分支 `claude/audit-handoff-docs`），由协调会话按 SA-MERGE-PR 合并。合并后主工作树里这几份未跟踪的同名文件会挡住同步 main，要先移到别处<br>• `.gitattributes`、`.githooks/pre-commit`、`.prime/scripts/merge-events.py`：只作用于被 `.gitignore` 排除的账本目录（`core.hooksPath=.githooks` 已生效，只允许 `publish_context` 提交 `.prime/context` 等路径），不影响开发，暂不提交 | 现状核对 | 入库走 PR；合并按 SA-MERGE-PR | PR 上 CI 全绿并已合并 |
| W16 | 仓库外：gstack 探测 Codex 模型的超时只有 30 秒 | 上一会话后续项 | 否（不在本仓库） | — |

## 接手须知（给下一个会话）

1. 先读：
   - 本报告的「现状」和「待办总表」
   - `~/.claude/CLAUDE.md`：全局规则，包括用中文回复、哪些事须 David 直接授权、任务合同与验收
   - 项目 `CLAUDE.md`、`AGENTS.md`，根 `SKILL.md`
   - `docs/regression-checklist.md`（下一个可用编号是 R-046）
   - `docs/agents/quality-floor.json`、`docs/agents/standing-authorizations.json`
   - 账本 `.prime/context/CI-COVERAGE/`、`.prime/context/CONTEXT-SEARCH/`
2. 角色：
   - 本工作树的 Orca 协调会话是 `context-skill-for-orca-c0`（协调者 `coordinator-opus-eb629ee5`），SA-MERGE-PR 只给协调者用。
   - 开工前先跑 `orca orchestration run-current`。Run 属于别的协调者时不要接手。
   - 如果协调会话也停用了，由 David 决定新会话是否用 `orca orchestration run-use` 接手协调。
3. 做法：
   - 每项待办从 `origin/main` 开新分支和新工作树，放在 `/Volumes/DavidDisk/project/managing-long-task-context/.worktrees/<名称>`。一个工作树同一时间只做一个任务。
   - 先写复现测试（由红转绿），只改这一项要改的内容。
   - 改了根目录的源文件后要重新生成包：Strict 跑 `python3 scripts/sync_context_strict_skill.py`，Lite 里由根生成的文件跑 `python3 scripts/sync_context_tools.py`。不要手改 `skills/context-strict/`。
   - 两个 PR 都会重新生成 `skills/context-strict/` 时，后合并的那个先变基，再重新生成。
   - 改动走 PR 进 main。不直接推默认分支，不强推。
4. 验证命令：
   - 定向测试：`PYTHONPATH=src:tests python3 -m unittest tests.<模块>`
   - 回归清单：`python3 scripts/regression_checklist.py`。只跑某几条用 `--only R-xxx`，可以写多次。
   - 全量：`python3 -m unittest discover -s tests`，本机约 700–940 秒。CI 在 PR 头提交上跑 Ubuntu 的 3.12，以及 macOS 的系统 `python3`（3.9）和 3.12。
   - 打包：照 `.github/workflows/ci.yml` 里「Verify complete skill packages outside the checkout」那一步。
5. 新版本合并后的全局重装。会覆盖已安装的目录，动手前先问 David：
   - 用 `git archive <合并提交>` 导出干净源码，在外接盘临时目录里依次跑 `skill_package.py check-source`、`build --source-revision git:<提交>`、`verify --expected-manifest-sha256 … --expected-source-revision …`
   - 把旧目录整个移到 `~/.codex/skills-backup-<UTC 时间>/`，再把新包复制到 `~/.codex/skills/<skill>`。`~/.claude/skills/context-strict` 和 `context-lite` 都是指向那里的链接
   - 装好后，对两个入口各跑一次 verify 和 `context_doctor.py check --mode full`
6. 记录：
   - 每项任务在 `.prime/context/<任务>/` 建账本，用已安装 Strict 的代码（`PYTHONPATH=~/.codex/skills/context-strict/src`）。
   - 写清原始约定、范围、验证命令、实际结果和证据指针。
   - 登记 CI 证据照 `CONTEXT-SEARCH` 的 AR-5d71fc4f9fe6ae0c 写。
7. 已知的坑：
   - 临时文件按全局规则放 `/Volumes/DavidDisk/project/_agent-storage/tmp/`。
   - 跑全量时可能遇到 W13 那个超时误报。
   - 在 Claude Code 沙箱里，写外接盘上的工作树、写 `~/.codex` 和 `~/.claude`、`gh` 的 TLS 连接都会失败。其他宿主是否一样，未核实。
   - stash 栈是所有工作树共用的，不要直接用 `git stash` / `git stash pop`。
   - 派 Codex 执行方之前，先确认 `codex --version` 不低于 0.162.1。

## 未核实的部分

- W1-P1、W3-LEASE、W3-FOLLOW 的执行方报告大多在其他工作树里。轮次一部分是从目录名和验收记录推断的。
- 当前 Orca 实际派工用的是哪套说明，从仓库里看不出来。
- Medium 7 里「绑定缺失时无法恢复」已实测；「绑定之后包更新导致无法恢复」仍是读代码推断的。
- 「约 2,500 行」按模块行数估算，没有逐函数统计。
- Token 数是按字符估算的，不是模型 tokenizer 的实测值。
- 「108 个检查点合计约省 600,000 tokens」假设每个检查点对应一次恢复；实际恢复次数没有记录。
- 决策包的各段上限是按 42 个账本的实测中位数和最大值定的建议值，还没有用真实恢复验证过「下一步决策不受影响」。
- 本文没有记入 `STRICT-LEDGER` 账本。补注也没有另记账本；补注引用的已完成事项，证据在 `CI-COVERAGE`、`CONTEXT-SEARCH` 两个账本里。
- 「现状」里的 PR 和 CI 状态是 2026-10-15 读回的，之后的变化没有跟进。
- 待办总表里的「须 David 直接授权」一栏，是按全局规则授权清单做的判断，没有逐项问过 David。
- W13 超时的原因只是推测（机器负载或外接盘 `TMPDIR`），没有复现。
