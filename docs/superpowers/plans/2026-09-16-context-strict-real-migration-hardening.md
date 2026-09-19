---
status: phase-1-implementation-complete-t5-partial
spec_type: context-migration-operational-hardening
verified_at: 2026-09-17T03:22:23Z
verified_head: 8e86db6cb058ff931790483941320228aa9ff9fb
status_reconciled_at: 2026-09-19T09:34:27Z
scope_decision: phase-1-reduced
current_phase: migration-truth-and-preflight
deferred_phase: trusted-host-v2-receipts
implementation_authorized: true
implementation_status: t1-t4-complete-t5-partial
remote_ci: pass
natural_validation: not_run
agent_behavior_eval: not_run
issue_filing_authorized: false
agent_spawn_authorized: false
semantic_review: clean
redaction_scan: clean
engineering_review_issues_folded: 15
engineering_review_unresolved: 0
quality_gate_score: not-rescored
quality_gate_scope: prior-spec-review-only
outside_voice: skipped-under-codex
---

# Context Strict 真实迁移闭环与权威状态治理

## Context

第一次真实长会话迁移证明：短交接文件可以帮助新会话恢复核心任务，但此次成功依赖人工文档、路径提示和新会话重新核验，没有真正走完 Context Strict 的合同、接管、回执和归档闭环。

受影响对象包括：

- 用户：可能看到“迁移成功”，但无法分辨信息恢复、控制权转移和旧会话退出分别是否成功。
- 主会话：可能因为收到 `clientThreadId` 就过早停止或归档。
- 新会话：可能从过期 `CONTEXT.md`、旧 checkpoint 或错误工作区恢复。
- 子任务与宿主适配器：可能在控制权未确定时继续写入或重复执行。
- 后续实施者：可能复用旧版本通过的校验结果，而没有验证当前 HEAD。

以下 Context、基线、Root Cause 与 Proposed Change 记录 `2026-09-16` 工程评审阶段的决策输入；它们是历史基线，不覆盖 frontmatter、D16/D17 与文末状态摘要所记录的后续实施事实。该评审阶段只定义后续优化，不授权修改 Skill、运行时代码、会话状态，不授权归档旧会话，不授权创建实施代理、合并、发布或部署。

本轮工程评审已确认缩减当前实施范围：第一阶段只修复迁移真实性、权威入口、只读预检和事故回归；可信宿主接口尚不存在时，不提前实现 v2 receipt、source-retirement receipt、运行时 authority state 或经济性实验。

## 2026-09-16 Verified Baseline（HISTORICAL_ONLY）

核验日期：2026-09-16。当时仓库 HEAD 为 `097c952`，已包含原短会话接管候选实现。此节只描述实施前基线；当前实施与合并状态以 frontmatter、D16/D17 和文末状态摘要为准。

| 组件 | 已有能力 | 实际应用结果 | 缺口 |
|---|---|---|---|
| `src/managing_long_task_context/handoff.py` | 已提供 `prepare_handoff`、`validate_handoff`、`activate_handoff`、`cancel_handoff`、`handoff_status` | 本次真实迁移未调用 | Skill 没有强制选择 Strict 或人工降级模式 |
| Strict 合同与账本 | sealed contract、追加事件、checkpoint、brief、gate | 9 个正式账本结构审计通过 | 多个 brief 内容已经过期，但仍显示 `usable=true` |
| 人工交接 | 25 行交接文件成功引导冷恢复 | 信息恢复成功 | 文件未封存、未绑定任务合同、没有目标会话回执 |
| 控制权转移 | 运行时支持代次和激活事件 | 实际只拿到 `clientThreadId` | 无可信 successor receipt，控制权状态仍是 UNKNOWN |
| 原生 Codex 适配器 | 明确拒绝伪造宿主能力 | 正确保持 `NOT_RUN/unknown` | 当前宿主没有可信身份、排他写入和跨父会话接管证明 |
| `CONTEXT.md` | 短恢复入口 | 能导航到候选工作区 | `observed_head` 指实施提交，不是当前合并 HEAD |
| 主方案校验器 | 检查来源、结构、版本和引用 | 合并后的干净工作区立即失败 | 依赖未进入 Git 的 `方案对话内容.txt`；后续授权断言也已过期 |
| 旧会话归档 | 原设计要求接管成功后归档 | 旧会话正确保留 | 新会话成功后没有回写和后续归档机制 |
| 收益评估 | 已有合成冷恢复案例 | 证明可恢复 | 没有 No-Skill 对照、token、费用或自然项目证据 |

### 当时的代码证据

- `src/managing_long_task_context/handoff.py:692` 已有只读验证入口。
- `src/managing_long_task_context/handoff.py:739` 会区分当前校验结果与历史提交事实。
- `src/managing_long_task_context/handoff.py:786` 已有准备阶段的合同、包、工作区绑定。
- `src/managing_long_task_context/handoff.py:1112` 已有带代次推进的激活入口。
- `src/managing_long_task_context/host_codex_native.py:18` 正确标记真实宿主验证为 `NOT_RUN`。
- `src/managing_long_task_context/host_codex_native.py:59` 在缺少可信桥接时拒绝授予控制权。
- `docs/superpowers/plans/short-session-handoff.md:986` 的校验器依赖本机未跟踪文件。
- `CONTEXT.md:8` 的提交字段没有表达合并、实施、文档和已验证提交之间的区别。
- `tests/test_context_lite_handoff.py:255` 已断言冷恢复材料不能自动授予归档资格。

## Root Cause

1. 项目同时在开发 Skill 和使用 Skill，真实迁移发生时采用了“Strict 原则 + 人工文件”的混合路径。
2. 没有强制声明迁移模式，人工降级路径被口头描述成了 Skill 迁移。
3. “信息恢复成功”“控制权转移成功”“旧会话退出成功”被压缩成一个“迁移成功”。
4. 主方案持续追加历史阶段，但内置校验器和末尾评审没有随当前状态同步。
5. `brief_diagnostics()` 能证明结构可用，不能证明事实仍然新鲜；旧任务也没有统一的 superseded 标记。
6. 宿主创建任务只返回准备中的客户端 ID 时，没有持久化的等待、确认和回写闭环。
7. 当前恢复入口使用单一 `observed_head`，无法准确表达基线、实施、文档、合并和已验证提交。

## What already exists

| 已有能力 | 复用方式 | 本阶段不重建的原因 |
|---|---|---|
| `handoff.py` 的 v1 prepare/validate/activate/status、三事件投影与 controller generation | Strict 路径直接复用既有公开入口和返回语义 | 当前事故不是缺少状态机，而是 Skill 没有真实调用并错误概括结果 |
| `__init__.py` 的进程锁、`fsync`、原子替换和请求幂等 | 新预检保持只读，不建立第二套控制写入 | 新的控制存储只会扩大并发与恢复风险 |
| `runtime_identity.py` 的包、工作区和任务绑定 | Strict 模式继续使用；manual 模式只做非控制性文件绑定 | 不允许 manual 证据越权成为运行时身份 |
| 原生 Codex/Claude 适配器的 fail-closed 行为 | 没有可信宿主证明时继续返回 UNKNOWN | 本阶段不伪造宿主能力 |
| 根维护源到 Strict/Lite 包的同步器、`test_distribution.py` 和完整包 CI | 用于证明生成物与发布包确实包含修复 | 不新增第二套打包或发布流水线 |
| Lite 冷恢复对 `archive_allowed=false` 的既有测试 | 作为 manual fallback 边界回归基准 | 信息恢复不能自动授予控制权或归档资格 |

## Proposed Change

### P0：强制迁移模式

每次迁移必须在任何新会话创建前选择并记录：

```text
migration_mode:
  strict_protocol
  manual_fallback
```

不允许省略，也不允许使用模糊的 `automatic`、`skill` 或 `normal`。

`strict_protocol` 必须按顺序满足：

1. 当前安装包完整验证通过。
2. 存在包含 `short-session-handoff/v1` 的 sealed contract。
3. 工作区、包、任务和当前 controller generation 绑定成功。
4. `prepare_handoff` 返回已确认提交。
5. 目标会话读取并核验交接内容。
6. 可信宿主验证器确认目标身份、授权和内容。
7. `activate_handoff` 返回已确认提交。
8. `handoff_status` 回读激活事件和新代次。

任何一项缺失，必须停在 UNKNOWN，不得自动改成 `manual_fallback`。

第一阶段复用现有 `short-session-handoff/v1` 三事件协议、公开函数、请求幂等、原子写入和 controller generation，不扩展事件集合，不新增控制账本。Strict 路径只有在当前宿主确实提供可信 verifier 时才可进入；当前原生适配器能力不足时必须报告 UNKNOWN。

Manual 路径不写 Strict 控制事件，只生成受当前 plan SHA、工作区和 Git revisions 约束的只读预检结果；不持久化新的控制事实，也不包含 controller generation 或归档许可。

`manual_fallback` 允许通过短交接文件恢复信息，但必须固定输出：

```text
information_recovery: pass | fail | unknown
control_transfer: unknown
source_retirement: not_allowed
archive_allowed: false
```

### P0：拆分三类成功

所有 CLI、示例、Skill 回复模板和验证报告统一输出：

```json
{
  "information_recovery": {
    "status": "pass|fail|unknown",
    "evidence_refs": []
  },
  "control_transfer": {
    "status": "pass|fail|unknown",
    "commit_status": "confirmed_committed|confirmed_not_committed|unknown|not_attempted",
    "controller_generation": null
  },
  "source_retirement": {
    "status": "pass|fail|unknown|not_allowed",
    "archive_allowed": false,
    "evidence_refs": []
  }
}
```

禁止再使用没有三个子结论的单一 `migration_success=true`。

### P0：信息恢复效果证明

文件存在、SHA 匹配和路径绑定只产生 `material_integrity=pass`，不得直接产生 `information_recovery=pass`。Manual 与 Strict 两种模式都使用相同的五类关键事实回读：

```text
objective
current_state
constraints
next_action
unresolved_risks
```

来源会话从交接材料生成受 `task_id`、handoff 文件 SHA 和 plan SHA 绑定的 `recovery-checklist/v1`；每个条目包含稳定 `fact_id`、类别、规范化值和来源引用。目标会话读取交接材料后生成 `recovery-readback/v1`，逐项返回同一 `fact_id`、类别和规范化值。

`handoff_preflight.py` 只做确定性比较：字段集合必须精确相等，五类不得缺失，重复或未知 `fact_id` 拒绝，规范化值和来源绑定任一不一致即 fail。全部匹配才允许 `information_recovery=pass`；缺少 checklist/readback、无法读取或无法完成确定性比较时为 unknown。

该 readback 是非控制性恢复证据：它不证明目标会话身份、排他控制权、controller generation 或归档执行结果，永远不能改变 `control_transfer`、`source_retirement` 或 `archive_allowed`。

#### Readback 规范化

- checklist/readback 顶层字段集合必须精确匹配，未知字段拒绝。
- facts 使用数组承载，最多 64 项；每项必须且只能包含 `fact_id`、`category`、`value`、`source_ref`。
- `fact_id` 唯一；五类 category 每类至少一项。比较前按 `fact_id` 排序，原文件顺序不影响结果。
- `value` 与 `source_ref` 只允许 UTF-8 字符串；要求 NFC Unicode 和 LF 换行，不进行静默 trim、大小写折叠或语义改写。非规范输入直接 fail，避免两个实现产生不同“等价”结果。
- 对规范化后的 JSON 使用 `ensure_ascii=false`、键排序和紧凑分隔符计算 SHA-256；hash 与解析必须来自同一次读取的 bytes。
- `information_recovery=pass` 只表示这 64 项以内的显式关键事实没有丢失或改写，不表示完整旧会话逐字等价；报告必须展示覆盖的 fact 数与五类分布。

### Deferred Phase 2：可信宿主接口出现后再设计 v2 回执

第一阶段不实现或冻结 `short-session-handoff/v2`、successor receipt、source-retirement receipt、新控制事件、归档资格投影或运行时 authority state。它们不是当前实施的隐藏可选项，也不得以“先放 Schema”方式提前落地。

只有宿主同时提供下列可实测能力，才能新开设计评审并进入 Phase 2：

1. 返回可回读的真实 `threadId`，而不是只有准备态 `clientThreadId`。
2. 宿主侧可独立证明目标会话身份、工作区、任务和 handoff 绑定。
3. 宿主侧可证明排他控制权或 controller generation 接管结果。
4. 归档操作返回稳定 action ID、明确状态和可再次读取的结果。
5. 创建、接管和归档均有文档化幂等语义，能够区分未执行、已执行和执行结果未知。

Phase 2 启动时必须重新核验宿主接口并单独评审以下设计，不得直接复用本文件旧稿中的字段：

- v2 capability 与 v1 兼容边界；
- successor 与 source-retirement receipt Schema；
- 宿主 verifier 的主体分离和绑定字段；
- 归档资格投影、幂等、冲突和过期语义；
- 真实宿主迁移、归档回读与回滚测试。

在触发条件满足前，`control_transfer` 只能使用现有 v1 可信验证结果；`source_retirement` 保持 `unknown|not_allowed`，`archive_allowed=false`。

### P0：当前版本校验

现有方案内嵌 Node 校验器退出权威校验链，改为仓库内可测试的 Strict 专属确定性校验程序；共享 `context_doctor.py` 和 Lite 包保持不变。

目标入口：

```text
python skills/context-strict/scripts/handoff_preflight.py ...
```

必须检查：

- 实时读取当前 Git HEAD，确认 `verified_head` 是其祖先；两者之间只能修改声明过的方案、`CONTEXT.md` 和验收记录路径。
- 基线、实施、文档、合并提交分别记录。
- plan SHA 与恢复入口一致。
- 当前授权阶段只有一处权威定义。
- 历史评审不能冒充当前结论。
- 所有相对链接存在。
- 不依赖未跟踪、本机专属或不会进入发布包的文件。
- Strict 模式下合同、包、任务和 handoff 状态完整。
- Manual 模式下强制关闭控制权和归档结论。
- 当前校验失败时以非零退出，不修改任何文件。

CLI 完整参数固定为：

```text
handoff_preflight.py
  --mode strict_protocol|manual_fallback
  --stage prepare|activate|status|recovery
  --package-root ABSOLUTE_PATH
  --context-root ABSOLUTE_PATH
  --workspace-root ABSOLUTE_PATH
  --task-id ID
  --handoff-id ID
  --plan PATH
  --expected-plan-sha256 SHA256
  --expected-verified-head GIT_SHA_OR_NONE
  --handoff-file ABSOLUTE_PATH
  --expected-handoff-sha256 SHA256
  --recovery-checklist ABSOLUTE_PATH
  --expected-checklist-sha256 SHA256
  --recovery-readback ABSOLUTE_PATH
```

阶段矩阵固定为：

| Mode | Stage | 必需事实 | 通过后允许的下一步 |
|---|---|---|---|
| `strict_protocol` | `prepare` | plan/context/package/contract、来源材料和 Git 范围有效；尚不要求 handoff record | 调用既有 `prepare_handoff` |
| `strict_protocol` | `activate` | 当前 prepared record、目标 readback、可信 handoff verifier、generation 与所有绑定匹配 | 调用既有 `activate_handoff` |
| `strict_protocol` | `status` | 已有 v1 控制事件可读，重新执行当前验证并区分历史提交事实 | 只读报告三轴结果，不授予归档 |
| `manual_fallback` | `recovery` | handoff/checklist/readback 绑定和五类事实匹配 | 只报告信息恢复；不得调用 v1 写入口 |

Mode/stage 的其他组合是 `PREFLIGHT_INPUT_INVALID`。Strict `prepare` 不读取尚不存在的 handoff record；`activate` 和 `status` 才从 `<context-root>/<task-id>/handoffs/<handoff-id>.json` 与事件账本发现控制输入。Manual 不写 context ledger，通过显式 handoff、checklist 和 readback 绝对路径读取非控制性材料。三个文件都必须匹配命令行期望 SHA、task/plan/handoff 绑定，并以 `resolve(strict=True)` 规范化；符号链接、规范化后逃出 workspace 或字段集合不精确时返回 fail。

所有外部文件使用同一受限读取器：每个文件上限 1 MiB；打开时使用 `O_NOFOLLOW`（平台支持时），`fstat` 确认普通文件；解析和 SHA 必须来自同一次读取的相同 bytes；读取前后设备号、inode、size、mtime 任一变化即 unknown。平台不支持 `O_NOFOLLOW` 时执行打开前后 `lstat/fstat` 一致性检查，不得因兼容性回退而忽略符号链接或读写竞态。

Git 校验不得要求跟踪文件保存包含其自身的当前提交 SHA。`handoff_preflight.py` 实时取得 `current_head`，验证 `verified_head` 是祖先，并检查 `verified_head..current_head` 的文件列表只包含本方案、`CONTEXT.md` 和 `docs/superpowers/evidence/context-strict-migration/<run-id>/`；出现 Skill、脚本、源码、测试、包声明或其他生成产物变化时返回 stale，必须在新 HEAD 重跑完整验证。相关路径存在未提交修改或影响 preflight 的未跟踪文件时返回 unknown。

CLI 输出固定包含 `schema=migration-preflight/v1`、`migration_mode`、`material_integrity`、`preflight_status`、`migration_outcome`、`archive_allowed`、`checks`、`blocking_reasons` 和 `next_readonly_action`。

`preflight_status` 只回答当前模式的必需输入是否安全、完整且一致：任一必需检查 fail 则 fail；没有 fail 但存在 unknown、stale 或 not_run 则 unknown；当前模式全部必需检查 pass 才是 pass。退出码 0、1、2 分别对应 preflight pass、fail、unknown。

`migration_outcome` 只包含 `information_recovery`、`control_transfer` 和 `source_retirement` 三个独立维度，不生成或暗示单一迁移成功布尔值。第一阶段允许 `preflight_status=pass` 与 `source_retirement=not_allowed` 同时成立；退出码 0 表示可以按所选模式继续，不表示迁移、接管或归档已经完成。

#### 代码组织与稳定错误语义

`scripts/handoff_preflight.py` 保持单脚本、无新服务类，内部按纯函数边界组织：

```text
main
  -> parse_args
  -> verify_loaded_package_identity
  -> read_bounded_file
  -> validate_plan_and_git_scope
  -> validate_recovery_pair
  -> evaluate_selected_mode
  -> emit_report
```

先使用现有 `context_identity_core` 与 Strict runtime identity 证明脚本、加载模块和 `skill-manifest.json` 属于同一完整包，再导入或读取 handoff 运行时状态；混合源码树/安装包、manifest 在导入前后变化或运行时路径逃出 package root 时为 unknown，不继续执行下游检查。

错误分类固定为：

| 类型 | `preflight_status` | 示例稳定错误码 |
|---|---|---|
| 明确无效或绑定冲突 | fail | `PREFLIGHT_INPUT_INVALID`、`PREFLIGHT_DIGEST_MISMATCH`、`PREFLIGHT_BINDING_MISMATCH`、`PREFLIGHT_PATH_ESCAPE`、`PREFLIGHT_SYMLINK_REJECTED`、`PREFLIGHT_OVERSIZE`、`PREFLIGHT_READBACK_MISMATCH` |
| 无法获得可信事实 | unknown | `PREFLIGHT_FILE_UNAVAILABLE`、`PREFLIGHT_READ_RACE`、`PREFLIGHT_GIT_UNAVAILABLE`、`PREFLIGHT_PACKAGE_IDENTITY_UNKNOWN`、`PREFLIGHT_VERIFIER_UNAVAILABLE` |
| 前置门禁未通过而未执行 | not_run | `PREFLIGHT_DEPENDENCY_NOT_RUN` |
| 已验证事实被后续变化取代 | unknown，check 标为 stale | `PREFLIGHT_REVISION_STALE`、`PREFLIGHT_PLAN_STALE`、`PREFLIGHT_PACKAGE_STALE` |

每个 check 固定输出 `status`、`code`、`message` 和证据引用；顶层 `blocking_reasons` 按检查顺序稳定排序，`next_readonly_action` 只能有一项。不得把异常类型、绝对秘密路径、文件正文或模型生成解释直接暴露进稳定输出。

#### 性能与资源边界

预检是短生命周期只读 CLI，不引入缓存、守护进程或数据库。正确性优先于跨调用复用；每次运行重新读取 package manifest、所选阶段的输入文件和当前 Git 元数据，避免缓存把 stale 证据伪装成 current。

所有 Git 调用必须使用固定参数数组和 `shell=False`，设置 `GIT_OPTIONAL_LOCKS=0`、`GIT_PAGER=cat`、`LC_ALL=C`，并满足以下硬边界：

- 单次子进程超时 5 秒，完整 preflight 的 Git 子进程累计预算 15 秒；超时终止子进程并返回 `PREFLIGHT_GIT_TIMEOUT`/unknown，不无限重试。
- stdout 与 stderr 分别最多读取 1 MiB；超限返回 `PREFLIGHT_GIT_OUTPUT_LIMIT`/unknown，不把截断内容写入报告。
- 只运行 `rev-parse --verify`、`merge-base --is-ancestor`、`diff --name-only -z` 和 `status --porcelain=v1 -z --untracked-files=all` 这类元数据命令；不得读取 blob 内容或执行用户 Git alias/hook。
- `-z` 输出按 bytes 解析，最多 10,000 个路径；超限为 unknown。路径分类完成后只保留逻辑类别和相对路径摘要，不在稳定报告中暴露本机绝对路径。
- 同一运行内每个 Git 事实只采集一次并传递不可变结果；禁止按每个文件重复启动 Git，避免 N+1 子进程。

文件输入仍遵守单文件 1 MiB、最多 64 个事实的边界；JSON 解码只对已经受限的同一 bytes 执行一次。验收 fixture 中，普通干净小仓库的 preflight 本地中位数目标小于 2 秒、峰值 RSS 目标小于 64 MiB；这些是性能回归阈值而非迁移真实性证据。跨平台波动或 CI 噪声导致性能阈值不满足时单独报告，不得降级、跳过安全检查或缓存旧结论。

### P1：文档权威状态与历史状态分离

所有恢复资料使用下列标签：

```text
AUTHORITATIVE_NOW
HISTORICAL_ONLY
STALE
SUPERSEDED
UNKNOWN
```

要求：

- `CONTEXT.md` 只保存一个 `AUTHORITATIVE_NOW` 入口。
- 旧方案评审、旧候选清单和旧 checkpoint 标为历史或已替代。
- `brief_diagnostics().usable=true` 不得直接解释成 current。
- 被后续任务取代的账本在第一阶段只记录为 `HISTORICAL_ONLY` 或 `UNKNOWN`；不新增跨任务控制事实。
- 历史文件保留，不删除或重写追加事件。
- `BLOCKED` 只用于存在具体外部阻塞；尚未运行用 `NOT_RUN`；无法证明用 `UNKNOWN`。

状态判定不采用任意天数阈值，只比较当前恢复入口已有且可独立读取的事实：

- `STALE`：plan SHA、package manifest、受引用文件摘要不一致，或 `verified_head` 之后出现非允许列表代码/包变化。
- `SUPERSEDED`：第一阶段只用于人工维护的文档标签；没有可信双向事实时，运行时不得自动推断 superseded。
- `UNKNOWN`：缺少完成上述比较所需的原件或可信解析器。
- `AUTHORITATIVE_NOW`：`CONTEXT.md` 唯一入口中的 plan 路径、plan SHA、verified HEAD 和 package SHA 全部通过只读 preflight。

第一阶段不修改 `brief_diagnostics()`，不新增 `authority-state/v1`。如果后续真实使用表明文档 preflight 无法稳定治理多任务权威关系，再单独设计运行时 authority state；不得让方案 frontmatter 或自由文本授予运行时权限。

### P1：Git 身份字段拆分

废弃含义模糊的单一 `observed_head`。恢复入口保存已经发生且不会自引用的 Git 事实：

```yaml
baseline_head:
implementation_head:
verified_head:
verified_at:
```

`current_head` 由预检实时读取，不写入跟踪文件。`verified_head` 必须是最后一次完整校验实际运行的提交，不自动等于当前 HEAD；预检按祖先关系和允许列表差异判断验证是否仍适用。

`documentation_head` 与 `merge_head` 只允许出现在提交完成后由外部 Git/CI 回读生成的验收记录中，可以为 null，不作为 `CONTEXT.md` 自身的相等门禁。没有外部回读时保持 UNKNOWN，不通过再提交一次跟踪文件制造“一提交滞后”。

### P1：第一阶段会话迁移边界

Strict v1 流程固定为：

```text
preflight
  -> prepare
  -> create target
  -> obtain real thread ID
  -> target validates through existing trusted verifier
  -> activate
  -> status readback
  -> report three dimensions
```

任一步为 UNKNOWN：

- 保留旧会话；
- 禁止旧会话继续派发新的主控工作；
- 允许只读核验；
- 不盲重试创建、接管或归档；
- 输出唯一的下一项只读操作。

第一阶段任何模式都固定 `archive_allowed=false`，不执行旧会话归档。Manual 路径只证明信息恢复，不进入 v1 控制事件；Strict 路径即使控制权已确认，也要等待 Phase 2 的可信归档接口和单独授权。

### Deferred：经济性测量

No Skill、Context Lite、Context Strict 的 token、费用和自然效率对照是独立实验，不进入第一阶段实施。只有宿主提供同任务、同输入指纹、同条件的可读数据并另行授权时才启动；拿不到时保持 `NOT_RUN/UNKNOWN`，不得用文档字符数、事件数量、进程 RSS 或主观体验替代。

## Work Packages

| 子项 | 优先级 | 交付物 | 依赖 |
|---|---:|---|---|
| WP1 权威入口与预检 | Critical | 当前 plan、旧方案历史标记、CONTEXT Git 字段、只读 preflight | 无 |
| WP2 Skill 迁移真实性 | Critical | Strict/manual 明示分流、三轴结果、失败停止和归档禁止 | WP1 |
| WP3 测试与分发一致性 | Critical | 事故回归、生成物逐字节一致、完整包构建与源码树外 doctor | WP1、WP2 |
| WP4 受控验证 | Medium | manual fallback 确定性重放；真实宿主路径保持 NOT_RUN/UNKNOWN，除非另行授权 | WP3 |

依赖关系：

```text
WP1 ──> WP2 ──> WP3 ──> WP4
```

WP1 先执行，因为当前权威资料和校验器本身不可靠。WP3 必须在 WP1–WP2 后执行，否则只能证明旧行为仍通过。WP4 的 manual 重放可以验收第一阶段真实性边界，但不能替代未来 Phase 2 的可信宿主闭环。

### 第一阶段数据流与状态边界

```text
AUTHORITATIVE_NOW plan + CONTEXT
              |
              v
   Strict-only handoff_preflight.py --stage ...
      |       |          |
      |       |          +--> Git ancestry + allowlisted diff
      |       +-------------> bounded file/SHA/binding checks
      +---------------------> recovery checklist/readback comparison
              |
              v
       preflight_status
        pass|fail|unknown
              |
       +------+------+
       |             |
       v             v
 strict_protocol   manual_fallback
 prepare gate      recovery gate only
   -> prepare      no control events
 activate gate    material + semantic
   -> activate    recovery only
 status gate
   -> readback
       |             |
       +------+------+
              v
       migration_outcome
   information_recovery: pass|fail|unknown
   control_transfer:     pass|fail|unknown
   source_retirement:    not_allowed|unknown
   archive_allowed:      false
```

实现时在 `scripts/handoff_preflight.py` 顶部保留同一简化图，说明预检退出码与迁移结果不是同一状态机；若数据流变化，代码注释、本文和测试图必须同批更新。

### Worktree 并行化策略

| Step | Modules touched | Depends on |
|---|---|---|
| A 权威入口与历史标记 | `docs/`、根上下文文档 | — |
| B Strict 只读预检 | `scripts/` | A 的字段与状态定义 |
| C Skill 迁移流程 | 根 Skill、`references/`、`examples/` | A 的模式与三轴定义 |
| D 测试、同步和完整包证明 | `tests/`、`skills/context-strict/`、CI 包装流程 | B、C |
| E 受控验收与证据包 | `docs/superpowers/evidence/`、外部宿主回读 | D；自然验证另需授权 |

- Lane A：Step A（先串行冻结权威字段）。
- Lane B：Step B（A 后独立实现预检）。
- Lane C：Step C（A 后与 B 并行，不编辑 `scripts/` 或生成包）。
- Lane D：Step D → Step E（B、C 合并后串行运行同步、测试和验收）。

执行顺序固定为：A → 并行启动 B + C → 合并 B/C → D → E。B 与 C 不得各自运行并提交 Strict 生成物；`skills/context-strict/` 只由 D 的单一集成工作区生成，否则两条 lane 会对同一生成目录产生不可审计冲突。若无法使用独立 worktree，则按 A → B → C → D → E 顺序串行执行。

## Implementation Tasks

由工程评审问题直接合成。D16 已授权 T1–T4 与 T5 的本地证据生成；每完成一项才勾选。

- [x] **T1 (P1, human: ~3h / Codex: ~30min)** — 权威入口 — 建立唯一当前方案并拆分不可自引用的 Git 身份字段
  - Surfaced by: Architecture 1/5 — 多份资料可同时声称 current，且跟踪文件不能可靠保存包含自身的 HEAD。
  - Files: `CONTEXT.md`、`docs/superpowers/plans/short-session-handoff.md`、本方案文件。
  - Verify: 在临时 clone 中运行 prepare preflight；断言唯一 `AUTHORITATIVE_NOW`、祖先关系和允许列表差异。
- [x] **T2 (P1, human: ~5h / Codex: ~60min)** — Strict preflight — 实现分阶段、受限读取、包身份与有界 Git 检查
  - Surfaced by: Architecture 2/4/6/7、Code Quality 1/2、Performance 1 — 共享 doctor 不应扩张，退出码不能代表整体成功，输入和子进程必须 fail-closed。
  - Files: `scripts/handoff_preflight.py`。
  - Verify: `python3.12 -m unittest -v tests.test_handoff_preflight`；覆盖 UNIT、INT、CLI、PERF 编号且无 ResourceWarning。
- [x] **T3 (P1, human: ~3h / Codex: ~45min)** — Strict Skill — 固定 mode/stage、五类 readback、三轴结果和归档禁止
  - Surfaced by: Architecture 3/4、Code Quality 1 — 材料完整不能冒充信息恢复，信息恢复不能冒充控制迁移。
  - Files: `SKILL.md`、`references/handoff.md`、`examples/short_session_handoff.py`。
  - Verify: REG-07..13、SCN-01..06；确定性文档检查和合成输出都不得产生单一“迁移成功”。
- [x] **T4 (P1, human: ~6h / Codex: ~90min)** — 回归与分发 — 建立唯一测试清单并证明根源、Strict 生成物和 Lite 边界
  - Surfaced by: Architecture 1/2、Code Quality 3、Test Review 1–4 — 修复可能只落在根文件，测试也可能重复计数或遗漏静默失败。
  - Files: `tests/test_handoff_preflight.py`、`tests/test_real_migration_regression.py`、`tests/test_distribution.py`、`scripts/sync_context_strict_skill.py`、`skills/context-strict/` 生成物。
  - Verify: 全量 unittest；两次同步第二次零 diff；Strict/Lite check-source；源码树外 build/verify/full doctor/包内测试；`test-inventory.json` 无重复或空洞。
- [ ] **T5 (P2, human: ~2h / Codex: ~30min)** — 验收证据 — 生成可复核证据包并做受控 manual replay
  - Surfaced by: 用户风险要求与 Test Review 4 — 代码/配置通过不能替代实际落实证明，未获授权的自然路径必须保持 NOT_RUN。
  - Files: `docs/superpowers/evidence/context-strict-migration/<run-id>/`。
  - Verify: `evidence-manifest.sha256` 与所有产物匹配；`verification-report.json` 逐项引用 AC、测试 ID、命令回执和三轴结果；没有自然授权时明确 `NAT-01=NOT_RUN`、`EVAL-01=NOT_RUN`。
  - Status（2026-09-19 校正）：本地证据包 `RUN-20260917-phase1-0f9fdd1/` 与当前验证头证据包 `RUN-20260917-ci-herestring-8e86db6/` 已生成，远程 CI 已通过；NAT-01 与 EVAL-01 均为 NOT_RUN，因此 T5 保持未勾选。

本轮没有 P3 实施任务。可信宿主 v2 不是“有空再做”的普通 backlog，而是由五项外部能力共同触发的新设计阶段；在触发前把它写进 `TODOS.md` 会造成可立即实施的错觉，因此只保留本方案中的阻塞条件和 D2 决策记录。

## Acceptance Criteria

1. 干净 clone 中不需要 `方案对话内容.txt` 即可执行当前方案校验。
2. 预检发现旧 HEAD、失效 plan SHA、缺失 package SHA、多处当前入口或不存在的相对链接时必须非零退出。
3. 每次迁移必须明确记录 `strict_protocol` 或 `manual_fallback`，不得静默切换模式。
4. 文件、路径和 SHA 全部通过只能得到 `material_integrity=pass`；没有五类关键事实 readback 时，`information_recovery` 必须为 unknown。
5. Manual 模式只有 checklist 与 readback 精确匹配时才可输出 `information_recovery=pass`，同时仍输出 `control_transfer=unknown`、`source_retirement=not_allowed`、`archive_allowed=false`。
6. Strict 模式缺少 sealed contract、完整包身份、可信 verifier 或 handoff 激活事实时不得通过。
7. 只有 `clientThreadId`、任务标题、模型自报或普通聊天回复时不得报告控制权成功。
8. 三个成功维度必须分别报告，不得生成会隐藏 UNKNOWN 或 `not_allowed` 的单一迁移成功状态。
9. 当前 `CONTEXT.md` 不再使用含义不明的单一 `observed_head`，并只保留一个 `AUTHORITATIVE_NOW` 入口。
10. 历史 checkpoint 即使结构可用，也不会被默认列为当前事实；`usable=true` 不等于 current。
11. `BLOCKED`、`NOT_RUN`、`UNKNOWN`、`STALE`、`SUPERSEDED` 含义在 Skill、预检和测试中一致。
12. 原生 Codex/Claude 适配器在没有新宿主证据时继续拒绝控制权，现有 v1 三事件协议、返回键和幂等性不退化。
13. 方案明确区分唯一维护源与生成产物；重新运行同步器后无新增 diff，生成物逐字节一致测试通过。
14. 根仓库完整测试、Strict/Lite `check-source`、完整包 build/verify、源码树外 full doctor 和包内测试全部通过且零 skip、零 ResourceWarning。
15. 测试必须包含当前真实事故回归：过期 context、失效校验器、仅 client ID、材料完整但 readback 错误、人工恢复成功但控制权未知、归档始终禁止。
16. 第一阶段任何模式均不得归档旧会话，不新增 v2 receipt、归档回执或控制事件。
17. 没有宿主 token/费用数据时，收益结论必须保持 `NOT_RUN/UNKNOWN`。
18. `handoff_preflight.py` 的 `preflight_status` 对 pass、fail、unknown 分别返回 0、1、2；退出码 0 不得解释成迁移完成。
19. Phase 2 只有在五项可信宿主能力均有当前证据且重新完成设计评审后才可开始。
20. `verified_head` 必须是实时 current HEAD 的祖先；其后出现任何非允许列表代码、测试、包或生成物变更时返回 stale。
21. handoff、checklist 和 readback 必须由同一受限读取器完成大小限制、拒绝符号链接、同 bytes 解析/哈希和读前后文件身份检查。
22. 跟踪文件不得要求保存包含其自身的 current/documentation/merge HEAD；这些值只能实时读取或由提交后的外部回读记录。
23. checklist/readback 必须拒绝非 NFC、非 LF、未知字段、重复 fact ID、缺失类别、超过 64 项和超过文件大小上限；不得静默修正后继续。
24. preflight 必须先证明加载脚本、模块与 manifest 属于同一完整包；混合安装或导入前后 manifest 变化保持 unknown。
25. fail、unknown、not_run、stale 使用固定错误码和确定性排序；异常文本、材料正文和秘密路径不得进入稳定 JSON 输出。
26. Strict 的 `prepare`、`activate`、`status` 与 Manual 的 `recovery` 必须使用阶段专属必需项；尚未创建的 handoff record 不得阻塞 prepare，错误 mode/stage 组合必须 fail。
27. Git 子进程必须受 5 秒单次/15 秒累计、1 MiB 双流和 10,000 路径上限约束；超时、超量和非零异常均映射到稳定 unknown，不泄露原始输出。
28. 同一 preflight 不得按文件 N+1 调用 Git 或重复解析同一输入；性能 fixture 必须记录 wall time、峰值 RSS、Git 调用次数和输入规模。
29. `test-inventory.json` 必须证明每个新增测试方法只有一个主分类，覆盖图中的所有失败模式均有测试绑定；Skill 指令存在性与 `EVAL-01` 行为结果必须分开报告。

## Testing Plan

本仓库没有在 `CLAUDE.md` 中另设 Testing 约定，`pyproject.toml` 也未配置 pytest；现有套件以标准库 `unittest`、`subTest` 和独立进程 fixture 为基准。本阶段继续使用该框架，不引入新测试依赖。所有“新增数量”只按唯一的 `unittest.TestCase` 方法计数；同一方法不得同时计入 Unit、CLI、Integration 或 Scenario，`subTest` 只扩展输入矩阵，不增加方法数。

### 覆盖路径图

```text
维护源编辑
   |
   +-- sync_context_strict_skill.py -------------------- [DIST-01..04]
   |       +-- Strict 生成物逐字节一致
   |       +-- 新脚本恰好一次
   |       +-- Lite 不含新脚本
   |       +-- 第二次同步零 diff
   |
   +-- handoff_preflight.py
           |
           +-- package identity ------------------------- [UNIT-01..04]
           +-- bounded read / TOCTOU / symlink ---------- [UNIT-05..10]
           +-- plan + Git ancestry + allowlist ---------- [UNIT-11..16]
           +-- checklist/readback canonical compare ----- [UNIT-17..24]
           +-- stable error projection ------------------ [UNIT-25..28]
           |
           +-- strict_protocol
           |      +-- prepare ---------------------------- [INT-01..03]
           |      +-- activate --------------------------- [INT-04..06]
           |      +-- status ----------------------------- [INT-07..09]
           |      +-- existing v1 compatibility ---------- [REG-01..06]
           |
           +-- manual_fallback
                  +-- recovery only ---------------------- [INT-10..12]
                  +-- no control/archive claims ---------- [REG-07..10]

用户入口
   +-- CLI pass/fail/unknown + stable JSON/exit codes ----- [CLI-01..12]
   +-- clean clone / built package / source-tree-outside -- [CLI-13..18]
   +-- real-incident deterministic replay ---------------- [SCN-01..06]
   +-- Git budget / call count / wall time / RSS ---------- [PERF-01..04]
   +-- authorized cold manual replay ---------------------- [NAT-01, manual]
   +-- real trusted-host takeover ------------------------- [DEFERRED, Phase 2]

Skill/提示行为
   +-- exact required directives present ------------------ [REG-11..13]
   +-- agent actually follows directives ------------------ [EVAL-01, manual]
```

`EVAL-01` 只验证代理在一个隔离、无业务副作用的合成迁移中是否明确选择模式、分别报告三轴结果并拒绝归档。仓库当前没有稳定的 LLM eval harness，因此它必须记录模型、宿主版本、输入 fixture、原始输出和判定器版本；未运行时为 `NOT_RUN`。确定性文档断言可以证明指令存在，但不得替代该行为验证，也不得让 `EVAL-01` 阻塞第一阶段本地代码验收。

| 层级 | 内容 | 最低新增数量 |
|---|---|---:|
| Unit | 模式枚举、三轴状态、五类 readback、Unicode/JSON 规范化、受限文件读取、包身份、Git 祖先/允许列表、错误投影 | 28 |
| Integration | 三个 Strict 阶段门禁、现有 v1 prepare/validate/activate/status、Manual recovery 和 readback 绑定 | 12 |
| CLI | Strict 专属 `handoff_preflight.py` 的干净 clone、缺文件、旧状态、错误 SHA、readback 缺失/错配、混合包、符号链接、读取竞态和脱敏输出 | 18 |
| Distribution | Strict/Lite 包外导入、manifest、full doctor | 4 |
| Regression/Scenario | v1 返回形状与事件兼容、Skill 指令、控制/归档禁止及本次真实事故的确定性重放 | 19 |
| Performance | Git 超时/输出/路径预算、调用次数、wall time 与峰值 RSS | 4 |
| Natural | 经单独授权的一次 manual fallback 冷恢复；真实宿主闭环不在第一阶段 | 1 |

自然验证未获授权时必须报告 `NOT_RUN/UNKNOWN`，不能阻塞本地实现验收；真实宿主闭环未满足 Phase 2 触发条件时继续禁止自动接管和归档。

### 测试映射

| 验收标准 | 测试位置 |
|---|---|
| AC1–5、AC9、AC18、AC20–26 | `tests/test_handoff_preflight.py` |
| AC3–8、AC11、AC15–16 | `tests/test_real_migration_regression.py` |
| AC6、AC12 | `tests/test_handoff_protocol.py`、`tests/test_handoff_activation.py`、`tests/test_handoff_migration.py` |
| AC7、AC12 | `tests/test_handoff_codex_native.py`、`tests/test_handoff_claude_native.py` |
| AC13–14 | `tests/test_distribution.py`、`tests/test_handoff_distribution.py`、`.github/workflows/ci.yml` |
| AC17、AC19 | 验收报告字段与 Phase 2 触发条件的确定性文档检查 |
| AC27–28 | `tests/test_handoff_preflight.py` 的 `PERF-01..04` 独立进程 fixture |
| AC29 | `test-inventory.json` 验证器、`tests/test_real_migration_regression.py` 与单独的 `EVAL-01` 记录 |

### 生产失败模式与可见性

| 新路径 | 真实故障 | 自动化证明 | 对用户可见结果 |
|---|---|---|---|
| 包身份加载 | 从源码树运行脚本，却导入另一全局安装 | 替换 `PYTHONPATH`、manifest 和脚本根，覆盖导入前后变化 | `preflight_status=unknown`，码 `PACKAGE_IDENTITY_UNKNOWN`，只给一项只读修复动作 |
| 受限文件读取 | symlink 替换、FIFO/目录、读中换 inode、超 1 MiB | 独立进程竞态 fixture；断言 FD 全部关闭 | `unknown`，不输出材料正文或绝对秘密路径，不重试读取 |
| Git 验证 | `verified_head` 不存在、不是祖先、Git 超时、输出过大 | 临时仓库 DAG、假 Git wrapper、超时与输出上限 | stale 或 unknown，绝不把异常字符串直接投影到稳定 JSON |
| 允许列表 | 验证后代码/测试/包有变化，或相关 untracked 文件存在 | 每类路径各一个真实 Git diff；计划/CONTEXT/验收记录为正例 | 非允许变化为 stale；无法分类为 unknown |
| checklist/readback | Unicode 分解、CRLF、重复 ID、未知字段、缺类、同 ID 异值 | 原始 bytes fixture 与 canonical hash 断言 | `information_recovery=fail|unknown`，控制权仍 unknown |
| Strict prepare | 尚未创建 handoff record | 空任务状态 fixture | 只检查 prepare 前置项，不误报缺 handoff record |
| Strict activate | 只有 client ID、自报成功、目标证据在调用中变化 | 复用现有 host verifier 与变更中证据 fixture | activate 不执行；旧会话保留，唯一下一步为只读核验 |
| Strict status | 历史 committed 但当前验证器或包已失效 | committed 事件 + 当前证据漂移 | 历史事实仍可见，当前结论 unknown；二者不得互相覆盖 |
| Manual recovery | 材料 SHA 正确但五类事实错配 | checklist/readback 对照 fixture | material pass、information fail、control unknown、archive false |
| 分发 | 根脚本已修复但 Strict 副本未同步，或误进 Lite | 独立复制清单、二次同步、完整包外执行 | 分发测试 fail；不得以根测试通过宣称落实 |
| 稳定输出 | Python/Git 错误包含材料正文、用户名或临时路径 | canary 字符串与路径脱敏断言 | 只返回固定错误码、相对逻辑位置和安全说明 |
| Skill 行为 | 指令存在但代理仍报告“整体成功”或试图归档 | REG 确认指令；EVAL-01 合成会话观察真实输出 | eval fail/NOT_RUN 单独记录，不反向伪造代码失败 |

任何上表中的路径如果没有对应测试 ID、稳定错误码和用户可见结果，均视为 Critical 缺口；实施不得以总测试通过掩盖该缺口。

### 固定验证命令

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3.12 -W always::ResourceWarning -m unittest discover -s tests -v
python3.12 scripts/skill_package.py check-source --source skills/context-strict
python3.12 scripts/skill_package.py check-source --source skills/context-lite
```

随后必须按 `.github/workflows/ci.yml` 中名称为 `Tests and skill packages` 的 job，在新的临时目录中分别 build、verify 两个完整包，从源码树外运行各包的 full doctor 和全部包内测试。验收记录必须包含命令、Python 版本、平台、实际测试方法数、失败数、skip 数、ResourceWarning 数、包 manifest SHA 和 source revision；“最低新增数量”按独立 `unittest.TestCase` 测试方法计数，参数化子案例和 `subTest` 不重复计数。只有所有现有测试及新增测试均执行、失败 0、skip 0、ResourceWarning 0 才满足本地 AC15。

实施前先生成机器可读的 `test-inventory.json`，每个测试方法只登记一个主分类和一组覆盖的 AC/失败模式；验收脚本必须拒绝重复 test ID、缺号、同一方法多分类以及表中失败模式没有测试绑定。该清单与 `verification-report.json`、完整命令 stdout/stderr 摘要和 manifest SHA 一并列入最终产物，便于审查“测试是否真的跑到对应修复”。

远程 CI 只在另行获得 push/PR 授权后触发；通过 `gh run list --workflow CI --commit <SHA>` 获取唯一 run，再以 `gh run view <RUN_ID> --json status,conclusion,headSha,url` 回读。没有远程授权或没有唯一回执时记录 `NOT_RUN/UNKNOWN`，不得拿本地命令替代远程 CI。

## Files Reference

### 唯一维护源

| 文件 | 计划变更 |
|---|---|
| `docs/superpowers/plans/2026-09-16-context-strict-real-migration-hardening.md` | 第一阶段唯一优化实施规格与 Phase 2 触发条件 |
| `docs/superpowers/plans/short-session-handoff.md` | 标记为历史阶段，移除对当前状态的重复声明 |
| `CONTEXT.md` | 切换权威入口并拆分 Git 身份字段 |
| `SKILL.md` | 强制模式选择、三轴报告和归档禁止；由同步器生成 Strict 包版本 |
| `references/handoff.md` | 固定 Strict v1 与 manual fallback 两条流程 |
| `scripts/handoff_preflight.py` | 新增 Strict 专属只读预检入口；不进入 Lite 包 |
| `examples/short_session_handoff.py` | 演示 Strict v1 与 manual fallback，不包含 v2 receipt |
| `tests/test_handoff_preflight.py` | 预检 CLI、路径、SHA、状态和退出码测试 |
| `tests/test_distribution.py` | 维护源与生成产物逐字节一致、同步清单唯一性 |
| `tests/test_real_migration_regression.py` | 本次真实事故的确定性回归套件 |

### 生成产物与落实证明

| 维护源 | 生成产物 | 生成方式 | 必须通过的证明 |
|---|---|---|---|
| `SKILL.md` | `skills/context-strict/SKILL.md` | `python scripts/sync_context_strict_skill.py` | `tests/test_distribution.py::test_distribution_matches_maintained_sources` |
| `references/handoff.md` | `skills/context-strict/references/handoff.md` | 同上 | 根文件与包内文件逐字节一致 |
| `scripts/handoff_preflight.py` | `skills/context-strict/scripts/handoff_preflight.py` | `python scripts/sync_context_strict_skill.py`，只加入 Strict `COPIED_FILES` | 根文件与 Strict 包内文件逐字节一致；Lite 包中不存在该脚本 |
| `examples/short_session_handoff.py` | `skills/context-strict/examples/short_session_handoff.py` | `python scripts/sync_context_strict_skill.py` | 完整包示例从源码树外执行成功 |

### 可审查产物清单

| 阶段 | 产物 | 状态/生成者 | 审查用途 |
|---|---|---|---|
| 本轮工程评审 | `docs/superpowers/plans/2026-09-16-context-strict-real-migration-hardening.md` | 本轮已更新；唯一方案源 | 范围、架构、任务、验收和最终 review report |
| 本轮工程评审 | `~/.gstack/projects/wei0210-bit-managing-long-task-context/zhaowei-HEAD-eng-review-test-plan-20260916-085317.md` | 本轮 `/plan-eng-review` 生成 | `/qa`、`/qa-only` 的主测试输入 |
| 本轮工程评审 | `~/.gstack/projects/wei0210-bit-managing-long-task-context/tasks-eng-review-20260916-085317.jsonl` | 本轮 `/plan-eng-review` 用 `jq` 生成 | `/autoplan` 聚合 T1–T5；一行一任务 |
| 后续实施 | `docs/superpowers/evidence/context-strict-migration/<run-id>/test-inventory.json` | WP3 生成 | 唯一测试 ID、主分类、AC 与失败模式绑定 |
| 后续实施 | `docs/superpowers/evidence/context-strict-migration/<run-id>/verification-report.json` | WP4 汇总 | 命令、环境、测试计数、三轴结果、NOT_RUN 项 |
| 后续实施 | `docs/superpowers/evidence/context-strict-migration/<run-id>/commands.jsonl` | WP4 每条命令后追加 | 命令、退出码、时间、stdout/stderr SHA 与安全摘要 |
| 后续实施 | `docs/superpowers/evidence/context-strict-migration/<run-id>/manual-replay.json` | 获得自然验证授权后生成；否则不创建 | NAT-01 输入指纹、readback、三轴结果与无归档证明 |
| 后续实施 | `docs/superpowers/evidence/context-strict-migration/<run-id>/eval-01.json` | 获得隔离行为验证条件后生成；否则不创建 | 模型/宿主/fixture/原始输出摘要/判定器版本 |
| 后续实施 | `docs/superpowers/evidence/context-strict-migration/<run-id>/evidence-manifest.sha256` | 最后生成 | 对本 run 所有已生成产物做完整性封口；不列自身 |
| 合并后校正 | `docs/superpowers/evidence/context-strict-migration/RUN-20260919-status-correction/` | 只读 GitHub/Git 回读 | 证明 PR #25/#26 已合并、required check 成功及 T5 仍为 partial |

`verification-report.json` 必须显式列出预期产物，并将每项标记为 `present`、`not_run` 或 `not_applicable`；缺文件不能静默忽略。`manual-replay.json` 与 `eval-01.json` 未获授权时以报告中的 `NOT_RUN` 条目替代，禁止生成伪回执。`evidence-manifest.sha256`、Git 树和报告三者任一不一致，修复落实状态为 unknown，不得宣称完成。

本轮外部评审产物已校验：测试计划 SHA-256 为 `0cca575b6086857eb4a66620f27eb1dbbcd092937e66a6c2ffe6580051c0681d`；任务 JSONL SHA-256 为 `2b42b40ccc1c8f9b865a9579354f652a9d6a683bd0b95485d555687b14b7266c`，共 5 行且 T1–T5 唯一。

实施顺序固定为：只编辑维护源 → 运行同步器 → 运行逐字节一致测试 → 再运行同步器 → `git diff` 不新增变化 → `check-source` → 源码树外 build/verify/full doctor。`check-source` 单独通过不能证明生成物来自最新维护源。

同步清单必须同时更新 `scripts/sync_context_strict_skill.py::COPIED_FILES` 与 `tests/test_distribution.py::COPIED_FILES`，并保留“两份清单完全相等、新脚本恰好出现一次、Lite 中不存在该脚本”的独立断言；测试不得直接复用同步器返回值生成期望集合。

## Do Not Touch

- append-only 事件的已有历史和审计能力。
- 旧合同默认不启用新能力的兼容策略。
- `handoff_status` 对历史提交事实和当前验证结果的区分。
- 原生宿主缺少可信桥接时的 fail-closed 行为。
- `src/managing_long_task_context/handoff.py` 的 v1 三事件协议、原子写入、请求幂等和 controller generation。
- `src/managing_long_task_context/runtime_identity.py` 及两个原生宿主适配器的现有信任边界。
- 未跟踪原始对话和用户现有冲突副本。
- 用户对合并、部署、生产修改和付费验证的人工授权边界。

## NOT in scope（工程评审与 Phase 1 边界）

- `2026-09-16` 工程评审阶段直接修改 Skill 或运行时代码；后续 D16 已单独授权并完成 T1–T4，不能反向解释为评审阶段已有实施权限。
- Phase 1 与本次状态校正均不归档旧会话；归档仍需可信宿主接口与新的明确授权。
- 实现 Codex 或 Claude 的新宿主原生接口。
- 在可信宿主接口出现前设计或实现 `short-session-handoff/v2`、successor receipt、source-retirement receipt、新控制事件或归档资格投影。
- 第一阶段新增运行时 `authority-state/v1` 或修改 `brief_diagnostics()`。
- D16 所授权的 Phase 1 实施不包含合并、部署、发布新版本或修改全局安装；任何后续动作继续逐次授权，本次状态校正的推送/合并授权不扩大为部署或发布权限。
- 批量重写所有历史账本。
- 运行 No Skill/Lite/Strict 经济性实验，或在没有宿主数据时宣称 token、费用、模型稳定性收益。

## Rollback Plan

- 方案文件本身可通过单一提交回退。
- 后续实现按 WP 独立提交；任何 WP 失败只回退该 WP，不删除历史事件。
- 第一阶段不新增 capability 或控制事件；回退只涉及文档、Skill 流程、预检和测试。
- 已有追加事件保持原样，不重写、不截断。
- 新预检失败时退回只读/manual fallback，不能绕过检查继续自动接管。

## Effort Estimate

| 工作 | 人工团队估算 | Codex + 测试估算 |
|---|---:|---:|
| WP1 权威入口与预检 | 1 天 | 2–3 小时 |
| WP2 Skill 迁移真实性 | 1 天 | 2–3 小时 |
| WP3 测试与分发一致性 | 1.5–2 天 | 4–6 小时 |
| WP4 受控 manual 重放 | 0.5 天 | 1–2 小时，另受授权约束 |

总计：人工约 4–4.5 天；Codex 实施与验证约 9–14 小时，不包含外部授权和远程 CI 等待时间。

## Retrospective Learning

最近相关提交显示三个必须保留的教训：`a0a1f91` 一次性引入 230 个文件和大批验证材料，说明“验证资料很多”仍可能掩盖权威入口与真实宿主证据不足；`3e954eb` 将 runtime identity 与共享 doctor 同时分发给 Strict/Lite，说明本阶段新迁移预检若继续扩张共享入口会扩大回归面；`c99404b` 已建立根维护源、同步器和包验证，说明生成物一致性应复用现有分发架构而不是再造发布路径。

因此本方案把当前实施压缩为 Phase 1、复用 v1、采用 Strict-only preflight，并要求小而封口的证据 bundle。历史验证资料只作回归输入，不自动升级为 current proof；任何“文件存在”“进程退出 0”或“包构建成功”都不能单独证明信息恢复、控制迁移或旧源退役。

## 工程评审阶段 Definition of Done（历史）

1. 本文件进入工程评审，已按用户选择缩减为第一阶段；前一版 8/10 质量门禁只属于缩减前草稿，不冒充当前评审结论。
2. 本文件落盘后没有修改任何计划外文件。
3. 该评审阶段没有启动实施代理、创建 GitHub Issue、修改 Skill、归档会话或执行部署。
4. 后续实施须另行授权；该授权后来由 D16 记录，不能反向解释为评审阶段已经实施。

## 后续实施 Definition of Done

1. AC1–29 均有对应自动化或明确的确定性文档证据；本地、完整包和 CI 结果分别记录，不互相冒充。
2. v1 兼容基准保持不变；第一阶段不出现任何 v2 capability、Schema、事件或公开入口。
3. 新方案成为唯一 `AUTHORITATIVE_NOW` 入口；旧方案和旧 checkpoint 保留但明确标为历史或已替代。
4. 至少完成一次 manual fallback 事故回归，证明信息恢复通过时仍不会错误授予控制权或归档资格。
5. 真实宿主验证只有在用户另行授权且宿主暴露可信证据时执行；否则生产自动接管保持关闭。
6. v1 兼容基准固定为提交 `097c952` 上 `tests/test_handoff_protocol.py`、`tests/test_handoff_activation.py`、`tests/test_handoff_migration.py` 的 JSON key 集合、事件类型集合和返回状态；新增测试必须先捕获该基准，再证明第一阶段没有改变 v1 输出。

## Decision Record

- D1：用户确认采用完整方案并写入新的方案文件；该确认只改变方案交付状态，不改变 `implementation_authorized=false`。
- D1 边界：只落盘方案，不创建 GitHub Issue，不启动实施代理，不实施任何 WP。
- D2：工程范围缩减为第一阶段；只处理迁移真实性、权威入口、只读预检和事故回归。
- D2 延后项：只有可信宿主五项能力均有当前证据后，才重新设计 v2 回执；不得沿用缩减前草稿的字段或提前实现。
- D3：采用根维护源与生成产物分离；生成物必须列入审查，并通过同步幂等、逐字节一致、完整包验证和证据记录证明修复已落实。
- D4：采用 Strict 专属 `handoff_preflight.py`；共享 `context_doctor.py` 与 Lite 包接口保持不变。
- D5：材料完整性与信息恢复分离；只有五类关键事实 checklist/readback 精确匹配才允许信息恢复为 pass，该证据不授予控制权或归档资格。
- D6：拆分 `preflight_status` 与三轴 `migration_outcome`；CLI 退出码只表达当前预检是否可继续，不表达整体迁移成功。
- D7：`verified_head` 使用“验证祖先 + 允许列表差异”；current HEAD 实时读取，跟踪文件不保存包含其自身的提交 SHA。
- D8：预检采用 1 MiB 受限单次读取、符号链接拒绝与读前后文件身份检查，避免 TOCTOU 和无界内存读取。
- D9：readback 使用严格 UTF-8/NFC/LF 与 canonical JSON，不做静默文本归一化；最多 64 项且五类必须覆盖。
- D10：preflight 先验证完整包身份，再加载 Strict 状态；错误分类和稳定码固定，输出不泄露正文或秘密路径。
- D11：Strict 新脚本同时进入同步清单和独立期望清单，测试断言恰好一次且 Lite 中不存在。
- D12：Strict 使用 `prepare`、`activate`、`status` 三个只读门禁，Manual 只允许 `recovery`；每个写入口前重新核验当前阶段事实。
- D13：Git 子进程采用固定命令、超时、双流、路径和调用次数硬边界；性能异常保持 unknown，不以缓存或跳过安全检查换速度。
- D14：测试以唯一 ID 和失败模式绑定计数；确定性 Skill 文档断言与真实代理行为 `EVAL-01` 分开，未运行不冒充通过。
- D15：后续落实只有在证据 bundle 的产物清单、manifest、Git 树和报告一致时才可确认；缺失自然验证必须明确 `NOT_RUN`。
- D16（2026-09-17）：用户授权实施 T1–T4 与 T5 的本地证据生成，`implementation_authorized` 改为 `true`；该授权不包含 v2 回执、归档旧会话、修改共享 `context_doctor.py` 或 Lite 接口、`NAT-01`、`EVAL-01`、真实宿主迁移、合并、推送和部署。
- D17（2026-09-19 状态校正）：GitHub 实时回读确认 Phase 1 实现 PR #25 已于 2026-09-17T02:56:52Z 合并为 `f5b5fc1`，CI 修复 PR #26 已于 2026-09-17T03:51:50Z 合并为 `59604f5`；两条 PR 的 required check 均为 SUCCESS。该事实更新不扩大 NAT-01、EVAL-01、真实宿主迁移、归档或 v2 权限。

## Engineering Review and Phase 1 Status Summary

- Step 0 Scope Challenge：按建议缩减为 Phase 1；v2 等待五项可信宿主能力后重新设计。
- Architecture Review：7 个问题，全部折入方案。
- Code Quality Review：3 个问题，全部折入方案。
- Test Review：覆盖图已生成，4 个缺口（计数口径、失败模式、行为 eval 边界、落实证据）全部补齐。
- Performance Review：1 个问题，已加入 Git 超时、输出、路径和调用次数硬边界。
- What already exists / NOT in scope：已写明。
- TODOS.md：评估 1 个候选（Phase 2 v2），按建议不新增普通 TODO；触发条件保留在 D2。
- Failure modes：12 条路径已列出，未留无测试、无错误处理且静默的 Critical gap。
- Outside voice：当前运行于 Codex，按 skill 规则跳过嵌套 Codex；没有冒充独立复核。
- Parallelization：4 条 lane；B/C 两条可并行，A/D 两条顺序门禁。
- Lake Score：15/15 条建议采用并写入方案。
- 评审产物：方案、80 行测试计划、5 行唯一任务 JSONL；两份外部产物 SHA-256 已记录。
- Phase 1 实施：T1–T4 已完成并经 PR #25 合并；CI here-string 修复经 PR #26 合并。
- 验证结果：完整零 skip 套件 671 项通过；Strict 包 496 项、Lite 包 64 项通过；PR #25、#26 required check 均为 SUCCESS。
- T5 状态：本地证据与远程 CI 回执已生成；NAT-01、EVAL-01、真实宿主迁移仍为 NOT_RUN，旧会话未归档。
- 权限边界：不因合并事实自动授权 v2、归档、NAT-01、EVAL-01、真实宿主迁移或后续新的推送/合并/部署。

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | 本轮范围在工程评审中缩减，未另跑 CEO review |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | SKIPPED | 当前在 Codex 宿主内，按规则不嵌套同模型 |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | CLEAR (PLAN) | 15 issues，0 critical gaps，0 unresolved |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | N/A | 后端、CLI 与文档方案，无 UI 变更 |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | 未运行 |

**VERDICT:** ENG CLEARED；PHASE 1 T1–T4 LANDED — T5 仍因 NAT-01 与 EVAL-01 未运行而部分完成；不授权 v2、归档、真实宿主迁移或后续新的推送/合并/部署。

NO UNRESOLVED DECISIONS
