# Truth Source Contract 设计规格

状态：用户已于 2026-08-31 书面批准；已进入实现计划阶段。

日期：2026-08-31

分支：`codex/truth-source-contract`

能力标识：`truth-sources/v1`

## 1. 决策与原则

Context Strict 增加一个**任务合同级、可选**的 Truth Source Contract。它声明哪些工作区原件承担任务决策，谁负责重新观测，以及哪些变化会使既有观测失效。

总原则是：**保持有效的前提下尽量经济，但不能因为经济而失效。**

由此得到五条不可放宽的约束：

1. 层间只传稳定路径和控制元数据，不传原文或自动摘要。
2. 执行者或指定 owner 重新读取原件；brief 和上游转述不能替代原件。
3. 未观测、过期、dirty、字节失配、不可读或 unknown 都不能通过相关质量门。
4. 合同只保存稳定规则；运行时状态只写追加事件，并投影到可重建快照。
5. 没有声明 `truth_sources` 的既有任务保持原来的行为、输出和成本路径。

Truth source 控制的是“任务依赖的上下文是否仍可信”，不是“验收标准是否已满足”。它不能替代 completion evidence，也不能证明 owner 对原件语义的理解正确。

## 2. 目标

- 为承重原件提供稳定、可审计的任务级声明。
- 用显式 dirty generation 防止实现变化后继续依赖旧观测。
- 用现场文件指纹发现未申报的字节变化。
- 用 owner、合同摘要、generation、指纹和可信时间绑定每次观测。
- 在 release、resume、handoff、completion 中统一 fail closed。
- 让 brief 只携带继续工作所需的最小控制面信息。
- 保持根包、可安装 `context-strict` 分发包和全局安装更新路径的一致性。

## 3. 非目标

- 不修改 Context Lite。
- 不增加项目级 truth source 注册表；每个项目无需预先安装配置文件。
- 不自动推断 change kind，不增加文件 watcher、后台进程或自动 dirty 清除。
- 首版不支持 URL、远程 Git、浏览器、凭据、目录、glob 或 symlink。
- 不保存原文、摘录、自动摘要、向量索引、RAG 数据或内容缓存。
- 不实现多主机锁、分布式事务或可靠消息队列。
- 不认证 actor 的真实身份；身份认证仍需外部签名或受信存储。
- 不宣称 SHA-256 指纹证明语义正确或 owner 实际完成了指定阅读方法。

## 4. 合同扩展

### 4.1 完整示例

`truth_sources` 缺省时不启用任何新路径。存在时，合同必须同时声明能力，并提供既有的绝对 `workspace_root` 作为相对路径锚点。

```json
{
  "schema": 1,
  "task_id": "TASK-001",
  "version": 1,
  "issued_by": "task-publisher",
  "issued_at": "2026-08-31T03:00:00Z",
  "authorized_approvers": [],
  "workspace_root": "/absolute/workspace",
  "required_capabilities": [
    "truth-sources/v1"
  ],
  "objective": "重构认证模块且不依赖过期状态说明",
  "scope": [
    "认证模块"
  ],
  "out_of_scope": [],
  "constraints": [],
  "acceptance_criteria": [
    {
      "id": "AC-01",
      "criterion": "现有认证回归测试通过",
      "required_evidence_types": [
        "test-report"
      ]
    }
  ],
  "truth_sources": {
    "schema": "truth-sources/v1",
    "items": [
      {
        "id": "TS-STATUS",
        "purpose": "项目当前状态的正式原件",
        "source_ref": {
          "kind": "file",
          "locator": "STATUS.md"
        },
        "owner": "project-lead",
        "max_age_seconds": 86400,
        "validation_method": "owner-readback",
        "invalidate_on_change_kinds": [
          "implementation-change",
          "configuration-change"
        ]
      }
    ]
  }
}
```

### 4.2 能力协商

- 新运行时公开 `SUPPORTED_CAPABILITIES = {"truth-sources/v1"}`。
- `required_capabilities` 存在时必须是唯一、非空字符串列表。
- 任一 required capability 不受支持时，发布和所有 gate 均 fail closed。
- `truth_sources` 存在但未要求 `truth-sources/v1` 时，合同无效。
- 要求 `truth-sources/v1` 却没有 `truth_sources` 时，合同也无效，避免能力声明与实际控制不一致。
- 旧运行时目前会忽略未知字段，因此 capability 标识不能让旧版本追溯性 fail closed。启用该能力前，参与同一任务的所有运行时必须先升级；这是部署前置条件，不是代码可以消除的保证。

### 4.3 Schema 规则

`truth_sources` 只允许 `schema`、`items` 两个字段；item 只允许示例中的七个字段；`source_ref` 只允许 `kind`、`locator`。未知字段直接拒绝，避免拼写错误被静默忽略。

- `truth_sources.schema` 必须精确等于 `truth-sources/v1`。
- `items` 必须是非空列表。
- `id` 必须匹配 `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`，并在合同内唯一。
- `purpose` 必须是最长 160 个字符的非空单行发布者标签；brief 以 JSON 字符串转义后渲染。
- `owner` 必须是最长 128 个字符的非空单行 actor ID。
- 首版 `validation_method` 必须精确等于 `owner-readback`。它要求 owner 声明已回读原件，不是运行时可以证明的语义事实。
- `source_ref.kind` 首版只能是 `file`。
- `source_ref.locator` 必须是工作区相对文件路径，详细安全规则见第 8 节。
- `max_age_seconds` 必须是大于零的整数。
- `invalidate_on_change_kinds` 必须是非空、唯一、非空单行字符串列表。
- 启用该能力时，`workspace_root` 必须是存在的绝对目录，且目录本身不能是 symlink。

合同摘要继续覆盖完整合同。`truth_sources` 的任何修改都使 seal 失效；合法修改必须提高合同版本并重新确认。

## 5. 运行时状态模型

### 5.1 合同与事件分工

合同只保存声明。以下数据禁止写回合同：

- `observed_at`
- fingerprint
- dirty 状态或原因
- generation
- verification refs

这些状态进入 `events.jsonl`，再投影到 `snapshot.json`。事件不保存原件正文。

### 5.2 Generation

快照中的 truth source 控制面包含一个任务级单调递增 `generation`，以及每个 source 的 `required_generation` 和最近一次 `observed_generation`。

- 首次发布带 truth sources 的合同时，generation 从 0 增至 1；所有 source 的 `required_generation` 为 1，状态为 `unobserved`。
- 每次 `truth-sources-dirtied` 事件只增加一次任务 generation，并把本次受影响 source 的 `required_generation` 更新为新值。
- 未受影响 source 保持原 `required_generation`，不会被无关变化连带失效。
- 观测只有在 `observed_generation == required_generation` 时才可能有效。
- 一旦任务历史上启用过 truth sources，此后**每个**合同版本的发布事件都追加 reset 并增加 generation，即使新旧相邻版本都不再声明该能力。启用版本中的 source 全部重新成为 `unobserved`；未启用版本使用 `source_ids: []`。被删除的 source 从当前投影移除，历史仍保留在事件流中。

### 5.3 `contract-published` 的兼容扩展

对从未启用 truth sources 的合同，`contract-published` 事件和快照保持原样。

新合同启用 truth sources，或任务历史上曾启用过该能力时，事件 payload 增加：

```json
{
  "truth_source_reset": {
    "schema": "truth-sources/v1",
    "generation": 3,
    "source_ids": [
      "TS-STATUS"
    ]
  }
}
```

`source_ids: []` 表示该版本没有启用该控制。此后即使连续发布多个未启用版本，每个版本仍带空 reset 并继续 generation；它不删除历史事件。只有从未启用过该能力的任务保持旧事件字节。

重放规则必须唯一：

- payload 含 `truth_source_reset` 时，以该 reset **原子替换**当前 `snapshot.truth_sources.sources`，不得在旧 source 状态上叠加。
- 每个 `source_ids` 成员初始化为 `required_generation=<reset generation>`、`observed_generation=null`、`observation=null`、`status=unobserved`。
- `source_ids: []` 清空当前 sources，但保留任务级 generation，供未来再次启用时继续单调递增。
- reset generation 必须是上一 truth generation 加一；source IDs 必须非空字符串且唯一。发布 reset 时，它们必须与该次新 sealed contract 的声明集合精确相等；能力移除时，新声明集合与 `source_ids` 都必须为空。
- payload 不含 reset 时不得创建 `snapshot.truth_sources`。对从未启用该能力的任务，snapshot 字节保持旧格式。
- 重放历史事件时可以验证 generation 和结构；由于旧版本合同正文不会保留，只对**最后一个 reset**额外验证其 digest、version、source IDs 与当前 sealed contract 精确一致。任一不匹配都使 audit 和 gate fail closed，不能沿用旧投影。

`truth-sources-dirtied` 重放时，contract digest 必须等于最近一次 contract event，generation 必须恰好加一，affected IDs 必须是当前 source 的非空子集。`truth-source-observed` 重放时，contract digest 必须匹配、source 必须已声明、observed generation 必须等于该 source 的 required generation。重复观测同一 generation 且 fingerprint 不变是合法的 freshness 刷新；其他未知 source、跳号、倒退或非法迁移均使事件读取失败并阻断 audit/gate。

三个 truth control event 都使用字段 allowlist；event actor 必须非空，`created_at` 必须是显式 UTC RFC3339，数组必须唯一，digest、generation、fingerprint 和 payload 类型必须精确合法。任一非法事件使整条事件流进入不可用状态：重建立即失败，既有 snapshot 不得作为降级依据，后续合法 observe 也不能覆盖或“治愈”该错误。修复只能由人工恢复受信事件工件。

## 6. 写入 API 与事件

只有 `publish_contract`、`mark_truth_sources_dirty` 和 `observe_truth_source` 会写 truth source 状态。`gate`、`brief`、`brief_diagnostics` 与 `audit` 保持只读。

所有写入 API 在同一任务锁内完成合同校验、文件解析、状态检查、追加事件和快照更新。调用者不能提供时间或 fingerprint。

带 truth source 的合同还必须支持本地崩溃恢复：

- 合同只有在 sealed `task-contract.json` 与事件流中**唯一且最新**的 `contract-published` 记录在 version、integrity digest 和 confirmed metadata 上一致时才算 committed。audit 和每个 gate 必须先检查该不变量，再决定是否启用或跳过 truth source；不一致一律 unknown 并阻断。
- 如果 `task-contract.json` 已原子写入，但相同 `(version, integrity_digest)` 的 `contract-published` 事件尚未写入，调用者用相同 publisher 字段、相同 version 和相同 `confirmed_by` 重试时，只补写缺失事件及确定性 reset；不得重新封印或改变确认时间。
- 若该 `(version, integrity_digest)` 已有且仅有一个发布事件，既有同版本拒绝规则不变；若存在不匹配或重复发布事件，返回明确恢复错误并 fail closed。
- 如果事件已经追加但 snapshot 更新失败，truth-enabled 任务在下一次读取时比较 snapshot event count 与成功解析的事件数；不一致就从事件流重建后再继续。
- 这些恢复分支在任务历史上曾启用 truth source 时持续生效；从未启用的 legacy 任务不增加恢复扫描或改变同版本发布行为。

### 6.1 标记变化

```python
context.mark_truth_sources_dirty(
    "TASK-001",
    change_kind="implementation-change",
    actor="executor-01",
    reason="认证模块行为已变化",
)
```

行为：

1. 读取并验证当前 sealed contract。
2. 找出 `invalidate_on_change_kinds` 包含该 `change_kind` 的 source。
3. 没有匹配项时拒绝调用且不写事件。
4. generation 增加一次；所有匹配项更新 `required_generation`。
5. 追加 `truth-sources-dirtied` 事件，返回 event ID、generation 和受影响 source IDs。

事件 payload：

```json
{
  "contract_digest": "sha256:...",
  "generation": 2,
  "change_kind": "implementation-change",
  "reason": "认证模块行为已变化",
  "affected_source_ids": [
    "TS-STATUS"
  ]
}
```

`actor` 与可信 UTC `created_at` 使用事件公共字段。`actor`、`change_kind`、`reason` 必须非空。重复标记代表新的变化，仍会产生新的 generation。

### 6.2 重新观测

```python
context.observe_truth_source(
    "TASK-001",
    source_id="TS-STATUS",
    actor="project-lead",
    verification_refs=["test:auth-regression-018"],
)
```

行为：

1. 验证 sealed contract、source ID 和 actor。
2. `actor` 必须与声明的 `owner` 精确相等；这是一项可审计声明，不是身份认证。
3. `verification_refs` 必须是非空、唯一、稳定引用列表；每项必须匹配 `^[A-Za-z0-9][A-Za-z0-9._:/#@+-]{0,255}$`，不接受原文或多行内容。
4. 用第 8 节安全解析器现场读取原件并计算 SHA-256。
5. 首次观测或 source 已 dirty 时，接受当前指纹。
6. source 当前非 dirty，但现场指纹与最近观测不同，拒绝并返回 `TRUTH_SOURCE_UNDECLARED_CHANGE`；调用者必须先用真实 change kind 和 reason 标记 dirty，不能用新观测静默覆盖变化。
7. 追加 `truth-source-observed` 事件，绑定当前合同摘要和该 source 的 `required_generation`。

事件 payload：

```json
{
  "source_id": "TS-STATUS",
  "contract_digest": "sha256:...",
  "observed_generation": 2,
  "fingerprint": "sha256:...",
  "verification_refs": [
    "test:auth-regression-018"
  ]
}
```

观测时间取事件公共字段 `created_at`。事件和快照不保存文件大小或其他内容性元数据；首版只需要指纹完成控制。

`validation_method` 是合同给 owner 的核验要求。运行时能够验证 owner 字符串、引用、时间和文件字节，但不能证明 owner 实际理解了语义；文档和报告必须保留这项限制。

## 7. 状态判定与质量门

### 7.1 单个 source 的有效条件

每个 gate 验证阶段各采样一次自身观测到的可信 UTC，并对每个声明的 source 现场解析。release、resume、handoff 只有一个验证阶段；completion 的入口与尾部是两个阶段，必须分别采样时间。只有下列条件全部满足才是 `pass`：

- 存在最近观测。
- 观测的 `contract_digest` 等于当前 sealed contract digest。
- 观测 actor 等于当前 owner。
- `observed_generation == required_generation`。
- `observed_at` 是显式 UTC RFC3339，未超出 300 秒未来时钟偏差，并且年龄不大于 `max_age_seconds`。
- 现场文件解析成功。
- 现场 SHA-256 等于观测 fingerprint。

状态优先级为 `fail > unknown > pass`。任何 `fail` 或 `unknown` 都使 gate 的 `passed` 为 false。

`audit()` 只校验合同/event/snapshot 的结构、committed contract 不变量与 reducer 一致性，不现场打开 source 文件。公开 `brief()` 和 `brief_diagnostics()` 对已声明 source 使用同一只读 evaluator 取得现场状态，不能把缓存状态渲染为 pass；没有声明时不调用 evaluator。release/resume/handoff gate 在一次调用内复用第一次 truth-source 解析结果完成 brief preflight，不为同一 gate 重复读取文件；completion 仅因第 7.2 节的尾部一致性要求执行第二次解析。

每个读取操作都有明确线性化点：release、resume、handoff、brief 和 diagnostics 在同一个已存在 lock 的 shared-lock 临界区内读取 committed control、解析文件并固化返回状态；completion 的入口和尾部分别使用这样的临界区。mark/observe/publish 使用 exclusive lock，不能插入同一临界区。外部 writer 不受任务锁约束，因此文件状态以最终 `fstat` 成功的瞬间为该次解析线性化点。

### 7.2 Gate 矩阵

| 状态 | release | resume | handoff | completion |
|---|---:|---:|---:|---:|
| 首次未观测 | 阻断 | 阻断 | 阻断 | 阻断 |
| dirty / generation 失配 | 阻断 | 阻断 | 阻断 | 阻断 |
| stale | 阻断 | 阻断 | 阻断 | 阻断 |
| fingerprint changed | 阻断 | 阻断 | 阻断 | 阻断 |
| missing / unsafe / symlink / too large | 阻断 | 阻断 | 阻断 | 阻断 |
| permission / transient I/O / malformed event | 阻断（unknown） | 阻断（unknown） | 阻断（unknown） | 阻断（unknown） |
| 全部 pass | 继续现有 gate | 继续现有 gate | 继续现有 gate | 继续现有 gate |

发布顺序固定为：`publish_contract` → 对所有 source 执行首次 `observe_truth_source` → `gate(..., stage="release")`。

completion 先完成合同和 truth source 检查，再运行 criterion evidence。truth source 无效时：

- 不调用 evidence resolver 或 verifier 回调。
- `stats.evidence_attempts == 0`。
- 不得仅凭 evidence_map 通过 completion。

其他 gate 继续执行现有廉价结构检查并汇总错误，但不会因为有多个错误而放宽 truth source 阻断。

completion 采用两阶段一致性检查：

1. 入口捕获 committed contract digest、事件尾部/event count、每个 required generation，并完成第一次现场解析。
2. 执行既有 criterion evidence resolver/verifier。
3. 仅在准备返回 pass 时，重新采样可信 UTC，并在同一个 shared-lock 临界区内再次核对 committed contract、事件尾部和 generation、检查 freshness、现场解析所有 truth source，然后固化 verdict。
4. evidence 运行期间发生合同更新、dirty、事件追加或文件变化时，最终结果必须失败。

若入口已经无效，evidence callback 调用数必须为 0；若入口有效但 callback 期间才失效，已发生的 callback 无法撤销，但 gate 必须在尾部重检后失败。用 barrier 测试分别覆盖并发 mark、合同更新和文件变化。

`gate()`、`audit()`、`brief()` 和 `brief_diagnostics()` 对任务目录及临时目录执行零写入。现有写入式 bad-sample probe 必须改为纯内存检查，同时保持 probe ID、统计字段和判定语义；读取操作必须 shared-open 已存在的 lock，缺失、不可读或平台不能提供 shared lock 时返回 unknown，不能创建目录或 `.lock`。测试必须拦截文件写入与目录创建，证明四个读取 API 没有副作用。

### 7.3 报告代码

至少提供以下稳定代码；用户可据此修复后重跑，不进行 blind retry：

- `TRUTH_SOURCE_UNOBSERVED`
- `TRUTH_SOURCE_DIRTY`
- `TRUTH_SOURCE_STALE`
- `TRUTH_SOURCE_CHANGED`
- `TRUTH_SOURCE_UNDECLARED_CHANGE`
- `TRUTH_SOURCE_CONTRACT_MISMATCH`
- `TRUTH_SOURCE_OWNER_MISMATCH`
- `TRUTH_SOURCE_GENERATION_MISMATCH`
- `TRUTH_SOURCE_NOT_FOUND`
- `TRUTH_SOURCE_PERMISSION_DENIED`
- `TRUTH_SOURCE_TRANSIENT_IO`
- `TRUTH_SOURCE_UNSAFE_PATH`
- `TRUTH_SOURCE_SYMLINK`
- `TRUTH_SOURCE_NOT_REGULAR_FILE`
- `TRUTH_SOURCE_TOO_LARGE`
- `TRUTH_SOURCE_CHANGED_DURING_READ`
- `TRUTH_SOURCE_RESOLVER_UNKNOWN`

合同 schema 错误由 `publish_contract` 抛出 `ContextError`，并包含字段路径；运行中的失败进入 gate/report 的结构化 truth source results。

## 8. 文件解析安全

首版只解析 `workspace_root` 内的普通文件：

- locator 不能为空，不得含 NUL、`#`、`~`、绝对路径或 glob 元字符 `*?[]{}`；每个路径段都不得为空、等于 `.`/`..`，也不得带首尾空白。
- `workspace_root` 必须是绝对普通目录且自身不是 symlink。
- 从 workspace root 的目录文件描述符开始，逐段使用 `openat`/`dir_fd` 与 `O_NOFOLLOW` 打开；中间段必须是目录，最终段必须是普通文件。平台不能提供等价安全语义时返回 unknown，不能降级为不安全读取。
- 绝对 `workspace_root` 从稳定的文件系统根 FD 开始逐段打开；每一段都使用 `O_NOFOLLOW|O_DIRECTORY|O_CLOEXEC`，最终取得的 workspace root FD 是后续相对解析的唯一 authority。不能先 `resolve()` 后按字符串重新打开。
- 最终文件从同一个文件描述符完成 `fstat`、分块 SHA-256 和再次 `fstat`，避免路径替换后读取另一对象。
- 读取前后比较 device、inode、size、mtime_ns 和 ctime_ns；变化时返回 `TRUTH_SOURCE_CHANGED_DURING_READ`。
- `st_size` 预检和实际累计读取都执行 16 MiB 上限；恰好 16 MiB 允许，超过即拒绝。
- 解析器只返回状态、代码和 SHA-256，不返回 bytes、文本、摘录或自动摘要。
- root、中间目录和最终文件 FD 都必须有唯一 ownership，并在成功、失败和异常路径的 `finally` 中关闭；重复失败不能造成 FD 数增长。

单文件描述符和前后元数据检查消除了常见路径替换竞态，并检测正常的并发写入；它不宣称能对恶意、原地修改且伪造全部元数据的 writer 提供文件系统快照级原子性。

## 9. Brief 与可观测性

有 truth sources 时，brief 增加一个 mandatory 的紧凑控制块。每项只允许：

```json
{
  "id": "TS-STATUS",
  "purpose": "项目当前状态的正式原件",
  "source_ref": {
    "kind": "file",
    "locator": "STATUS.md"
  },
  "owner": "project-lead",
  "status": "pass",
  "required_generation": 2,
  "observed_generation": 2,
  "observed_at": "2026-08-31T03:15:00Z",
  "fingerprint": "sha256:..."
}
```

- 不包含正文、摘录、摘要或 verification refs。
- 该控制块属于固定承重上下文，不能被 `max_items` 过滤。
- 它计入 `fixed_prompt_chars`、CJK 加权 token 启发估算和 overflow 诊断。
- 装不下时继续返回 `BRIEF_REQUIRED_OVERFLOW`；不得为了省 token 删除 source 或隐藏非 pass 状态。
- 没有 `truth_sources` 时，brief、diagnostics 和 gate report 不增加空字段，保持旧输出兼容。

有声明时，gate report 增加 `truth_source_results`，stats 增加 `truth_sources_checked` 和 `truth_source_resolution_attempts`。报告只含控制元数据和代码。

“不泄漏原件”严格指 resolver 从文件读取的 bytes 不进入合同、事件、快照、brief、report 或异常消息。`purpose`、actor、reason 和 verification refs 是调用者主动提供的控制元数据；运行时只能限制其格式和长度，不能证明调用者未把敏感内容手工填入这些字段。泄漏测试的 canary 必须只存在于文件 bytes 中。

## 10. 组件边界

实现保持小而可独立测试：

- `src/managing_long_task_context/truth_sources.py`
  - schema 校验
  - 安全文件解析与指纹
  - 单 source 状态评估
  - 不写事件，不依赖 brief 渲染
- `src/managing_long_task_context/__init__.py`
  - 公共 API
  - 锁、事件追加、快照投影
  - gate 顺序与 brief 集成
- `tests/test_truth_sources.py`
  - 新能力的单元、状态机、安全和 gate 测试
- `scripts/sync_context_strict_skill.py`
  - 把新增模块、测试、示例和文档同步到 `skills/context-strict/`

根源码仍是单一维护源；`skills/context-strict/` 是生成并由 parity test 约束的安装单元。不得手工维护两份实现。

同步清单必须显式更新：

- `scripts/sync_context_strict_skill.py` 与 `tests/test_distribution.py` 的 `COPIED_FILES` 同时加入 `src/managing_long_task_context/truth_sources.py` 和 `tests/test_truth_sources.py`。
- 如创建 `examples/truth_source_contract.py` 或运行所需 asset，也必须同时进入两处清单，并由分发测试实际执行或读取。
- 根 `SKILL.md` 继续是 `skills/context-strict/SKILL.md` 的唯一文档源；本设计规格只保留在根仓库作为审计记录，不创建手工维护的分发副本。
- 分发测试必须导入新模块、执行 truth source 示例，并继续逐字节验证清单文件。

## 11. 兼容性与部署

### 11.1 Legacy 黄金路径

在固定时钟和 UUID 下，对不含 `truth_sources` 和 `required_capabilities` 的既有合同锁定：

- 发布后的 `task-contract.json`、`events.jsonl`、`snapshot.json` 字节一致。
- seal digest 一致。
- `brief()`、`brief_diagnostics()` 和四种 gate 的公开结构与内容一致。
- 不调用 truth source adapter，不扫描 workspace source 文件。
- 不向合同或快照 `setdefault` 新字段。

这里的“零额外文件读取”指不增加 truth source adapter 或 workspace source I/O；既有合同、事件、快照和 evidence 路径保持原样。

### 11.2 Rollout 顺序

1. 完成根包实现与测试。
2. 同步并验证 `skills/context-strict/` 分发包。
3. 在本仓库完成自然试用和独立审核。
4. 用户批准后才合并、推送和更新全局安装。
5. 使用该能力的所有 Codex/Claude/其他 host runtime 先升级，再发布含 `truth-sources/v1` 的任务合同。

旧运行时忽略未知字段是已知硬边界；部署检查必须记录参与 runtime 的版本或 commit，不能把 capability 字段本身当作旧运行时保护证明。

## 12. 验证合同

### 12.1 自动化测试

1. Legacy 黄金测试：旧合同的文件、digest、brief、diagnostics、gate 和 I/O 路径不变。
2. Schema 表格测试：capability、未知字段、类型、重复 ID、owner、age、change kind、workspace root 和 locator。
3. 事件/重建测试：首次发布、dirty、重复 dirty、选择性失效、重复同指纹 observe、非法字段/乱序/跳号/未知 source、合同更新、能力移除、发布事件缺失恢复和 snapshot rebuild；poisoned event 不得被后续事件治愈。
4. 观测绑定测试：owner、合同摘要、generation、fingerprint、可信时间和 verification refs。
5. 静默变化测试：非 dirty 状态下文件变化后，gate 阻断；observe 也拒绝覆盖，必须先 mark。
6. Gate 表格测试：四阶段对 unobserved、dirty、stale、changed、missing、permission、unknown 全部 fail closed。
7. completion 顺序测试：truth source 入口无效时 resolver/verifier spy 调用数为 0，`evidence_attempts == 0`；用 barrier 验证 callback 期间 mark、合同更新、文件变化或跨过 freshness 截止时间会在尾部阻断，并验证 mark 不能插入尾部 control-read/file-read 临界区。
8. 文件安全测试：绝对路径、逃逸、目录、glob、workspace root/最终/中间 symlink、root swap、替换竞态、读取中变化、所有异常路径 FD 平衡和 16 MiB 边界。
9. 泄漏测试：用独特 canary 原文验证 brief、events、snapshot、gate report 与异常消息均不含正文片段。
10. 分发测试：同步脚本无漂移，根包与安装包测试均通过，示例可执行。
11. 崩溃注入测试：合同临时文件写入、原子替换、事件追加和 snapshot 替换各切点分别中断；添加、修改和移除 capability 后均只能恢复或 fail closed，不能绕过控制。
12. 只读副作用测试：gate、audit、brief 与 diagnostics 不写任务目录、lock 或临时 probe 文件，且保留既有 probe 统计语义。

所有失败分支都要断言稳定错误代码、写入副作用边界和事件计数；不能只断言异常类型。

### 12.2 本仓库自然试用

使用公开 API 和真实工作区文件，不使用 monkeypatch 或伪 resolver：

1. 在忽略的 `.prime/context/` 发布一个 pilot 合同，以本文档为 truth source。
2. owner 首次读取原件并调用 `observe_truth_source`；release 通过。
3. 写入 handoff 所需 checkpoint。
4. 在真实实现变化后调用 `mark_truth_sources_dirty(change_kind="implementation-change", ...)`。
5. handoff 必须因 `TRUTH_SOURCE_DIRTY` 阻断。
6. owner 再次读取原件并调用 `observe_truth_source`。
7. handoff 必须通过。
8. 检查 brief、events、snapshot 和 gate report，不得出现本文档正文 canary；记录 event IDs、gate stats、fingerprint 和命令输出。
9. 由未参与实现的验证 Agent 按本节逐项复核，不得只接受执行 Agent 的总结。

另做一个隔离的真实文件试用：在仓库内的专用测试 fixture 上先完成有效观测，再实际改变文件 bytes 而不 mark。此时 observe 必须返回 `TRUTH_SOURCE_UNDECLARED_CHANGE`，handoff 必须因 changed 阻断；随后按真实 change kind 执行 mark、重新回读并 observe，handoff 才能恢复。fixture 最终恢复到受控内容；completion callback 次数仍由自动化 barrier/spy 测试证明，不用自然试用冒充精确调用证据。

自然试用证明公开路径可用，不替代自动化边界测试。

## 13. 残余风险

- 如果外部现实发生变化但文件字节未变，且 host 既不调用 `mark_truth_sources_dirty`，又未到 `max_age_seconds`，运行时无法自动发现语义过期。owner 重观测、较短 freshness window 和 host 集成只能降低风险，不能消除它。
- actor 字符串不等于经过认证的身份。seal 只能检测 sealed contract 的事后修改；owner 与事件只在协作式、受信本地存储假设下提供可追溯记录。首版没有事件 hash chain 或签名，协调删除、截断事件并重建 snapshot 的行为不可检测。
- 文件指纹只证明观测与现场字节一致，不证明内容真实、完整或被正确理解。
- 多运行时部署期间，旧运行时可能忽略 capability。所有参与方升级是启用前置条件。
- 单文件描述符读取不是恶意 writer 场景下的文件系统快照；首版明确限制在协作式本地工作区。
- 外部文件在某阶段最终 `fstat` 线性化点之后发生变化，或在两次解析之间变化后又恢复为相同 bytes，首版没有 watcher，不能归因或追踪这段历史；后续 gate 会按届时现场状态重新判断。

这些风险必须留在 SKILL 文档和发布说明中，不能用“已验证 truth source”这样的措辞掩盖。

## 14. 完成定义

只有同时满足以下条件，才能声称该能力完成：

- 本规格经用户书面审核批准。
- 实现计划在规格批准后另行编写并冻结验证步骤。
- 第 12.1 节所有自动测试通过，且有独立审核证据。
- 第 12.2 节自然试用通过，控制面没有原文泄漏。
- legacy 黄金路径证明未启用任务无功能和成本回归。
- 根包、分发包、示例与文档一致。
- 未解决问题和残余风险被明确报告。

合并、推送和全局安装更新不由本规格自动授权，仍需用户后续指示。
