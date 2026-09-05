# Context Skills：运行身份、工作区绑定与分层自检

## Context

为在多个项目中使用 Context Lite/Strict 的用户及 Agent 提供预防性运行自检，减少错版本、错工作区和重复排查的风险。目前没有已确认的串项目事故。本轮不预设 token 节省比例。

原则：保持有效的前提下尽量经济，不能因为经济而失效。

用户已确认：完整自检在安装更新后或主动诊断时运行；恢复任务只做轻量身份核对；默认工作区独立，绑定后允许切换目录，跨项目共享留待后续。

## Current State

核实来源为本规格编写时的仓库 main；行号仅辅助定位，实施前重新核实。

| 组件 | 已有能力 | 本轮缺口 |
|---|---|---|
| scripts/skill_package.py:334 verify_package | manifest、文件哈希、声明和文档接口校验 | 统一诊断入口、实际执行进程身份 |
| src/managing_long_task_context/__init__.py:4052 bind | 固定绝对存储目录 | 任务与工作区明确绑定 |
| tests/test_production_feedback.py:528 | 绑定后 chdir 仍访问原任务 | 保留语义并增加错工作区负例 |
| skills/context-lite/scripts/context_lite.py:118 | NOW 确定性校验 | 包身份与任务绑定诊断 |
| scripts/sync_context_strict_skill.py | 从根源码生成 Strict 分发副本 | 新工具与测试必须进入独立分发包 |

当前 Strict 0.5.0，Lite 1.1.0。manifest 验证不能证明其他进程已加载新实现。包校验、任务门禁和自然运行效果属于不同证据。

## Proposed Change

### 1. 两种模式与统一结果

提供 full 和 identity 两种诊断模式。full 复用完整包校验，在临时目录运行正常及阻断场景；identity 只核对绑定与当前调用进程身份，不扫描全包，不读历史和证据原文，不重新初始化。

报告字段固定为 schema=1、mode、status、checked_at、identity、binding、checks、codes、next_action。checks 为逐项结果数组，每项有 name、status、code、message；未执行的 full 项在 identity 报告中标为 not_run，不参与 identity 总状态，报告同时声明 full_verification=not_run。checked_at 使用 UTC RFC3339。

status=pass/fail/unknown，对应退出码 0/1/2。任一已确认不匹配为 fail，否则任一必需检查无法验证为 unknown，否则 pass。不得把 fail/unknown 映射为可恢复。

错误码至少包括 BINDING_MISSING、BINDING_INVALID、BINDING_CONFLICT、WORKSPACE_MISMATCH、STORAGE_MISMATCH、RUNTIME_PATH_MISMATCH、PACKAGE_IDENTITY_MISMATCH、RUNTIME_UNVERIFIED、READ_FAILED、SMOKE_FAILED。既有包错误码保留在逐项结果中。

### 2. 绑定记录

每个任务使用独立 context-binding.json，置于已有任务目录；不修改 task-contract.json、events.jsonl 或 NOW.md。字段为 schema=1、task_id、skill_name、expected_manifest_sha256、workspace_root、context_root、created_at。

workspace_root、context_root 规范化为真实绝对路径。Git 项目用明确传入的 worktree 根目录；非 Git 项目允许明确指定存在的目录。分支与 HEAD 只作观测字段，不是身份键。不同 worktree 即使共享 Git common-dir 也不是同一个工作区。

初始化需显式指定期望 manifest 哈希、工作区、上下文目录和任务 ID；先验证期望包身份再原子创建。检查不得从实际环境自行生成期望值。重复相同语义字段（不含 created_at）无操作且保留原字节；不同绑定拒绝覆盖，原文件不变。并发创建必须实现仅一个不同绑定成功，不能使用覆盖式 replace 破坏已存在记录。

初始化不创建真实任务、合同或检查点；任务目录须已存在。旧任务缺少绑定时为 unknown，提示显式绑定。更换版本/移动工作区须显式迁移，自动迁移或重绑定命令不在本轮；诊断给出所需新身份并停止，不能静默更新。

### 3. 运行身份与恢复

Strict 在实际调用进程报告模块 __file__ 和包来源；Lite 报告当前执行 validator 的 __file__。路径按 realpath 比较，合法全局安装目录符号链接可解析通过，不以字符串前缀判定归属。

期望身份来自绑定中的哈希，实际身份来自指定完整包的 manifest。报告保留进程身份与磁盘包身份的不同来源。单独 CLI 只证明自己，其他进程没有进程内观测即 RUNTIME_UNVERIFIED。

安装更新后旧进程须重启并重新核对。不得依据当前磁盘文件正确推断旧进程已加载新代码；实现必须提供进程内加载身份基线，在发现加载后包身份变化时停止受检恢复。这不是恶意进程防篡改认证，也不证明模型阅读了正确 SKILL.md。

新增受检恢复入口，先 identity，再调用现有 Strict brief 或读取经 Lite validator 校验的 NOW。身份失败/未知时不得返回恢复正文。Strict 现有 audit/gate 与 brief 的阻断照常生效，不以身份通过替代；旧底层接口不改变签名或强制新门禁，文档明确其不受新入口保护。

绑定客户端捕获显式 workspace_root 和 context_root，后续 chdir 不改变二者。针对新任务的恢复入口需显式接收工作区身份，不能从共享 context_root 推断工作区。跨项目共享不是本轮支持能力。

### 4. 分发与代码复用

不重新实现证据解析器、Lite 正文校验或完整包校验算法。必要时提取现有包检查代码到标准库共享模块，原 scripts/skill_package.py CLI 保持兼容；通过同步脚本生成两个独立包所需副本，增加逐文件一致性测试，禁止手工维护三份实现。

Strict 新运行接口归入 src/managing_long_task_context/，Lite 仍通过 scripts/context_lite.py 调用其配套标准库工具。更新两个 skill-package.json 的 payload_roots、required_paths 和能力声明。开发源码无 manifest 时报告包未验证，指引 build，不能伪造安装包身份。

文档只增加触发时机、命令和限制的简短入口，详细说明放 references。不在每次恢复注入完整诊断手册。

## Acceptance Criteria

1. 正确包、进程与绑定通过；任一身份不符不能报告 pass。
2. 不同工作区/存储中同名任务可检出错误绑定；同仓库不同 worktree 不混淆。
3. 相同绑定重复初始化不改文件；不同绑定及并发冲突保留原文件，失败返回稳定错误码。
4. 绑定后 chdir、正常提交、同一工作区切换分支仍能访问原任务。
5. 缺失、损坏、不可读取的绑定返回 unknown，无自动重建。
6. full 检出包文件修改；identity 明示不证明全包完整性。
7. 实际加载路径与期望包不符、只有另一进程诊断结果、进程加载后版本变化均不得误报运行身份通过。
8. full 在临时目录验证 Lite 合法/非法检查点以及 Strict 正常恢复/缺证据阻断；预期阻断应作为冒烟测试通过，不能反转含义。
9. 所有自检不修改真实任务文件；前后字节哈希一致。full 临时目录正常退出时清理；清理失败明确报告，不宣称清理完成。
10. identity 读取历史事件与证据原文次数为 0，调用完整包扫描和冒烟测试次数为 0；后续正常恢复的 brief 读取不计入身份检查本身。
11. 原有 unknown/conflict、证据时效、完成门禁、切目录绑定测试全部通过。
12. 两个完整分发包在开发源码不在搜索路径时独立运行自检成功；新增接口、文件与 manifest 一致。
13. 未通过身份检查的受检恢复不返回正文；旧 API 保持兼容，保护范围如实记录。

## Testing Plan

| 层级 | 必测内容 | 最少场景数 |
|---|---|---|
| 单元 | 三态聚合、错误码、绑定解析、路径规范化、期望身份、运行观测来源 | 10 |
| 集成 | 双工作区、双 worktree、chdir、分支变化、同名任务、旧任务、并发绑定、错导入路径、加载后升级 | 9 |
| 分发端到端 | Lite/Strict 各正常与失败诊断、受检恢复拒绝、真实文件不变 | 6 |

数目是最低独立场景数，不要求机械地一场景一测试。验证需提供命令、退出码、实际断言和对应测试路径；不能只贴执行 Agent 的成功说明。

记录 full/identity 耗时、读取文件数与输出字符数，不预设无法证明的速度或 token 降幅。identity 的零历史读取通过 I/O spy 验证。独立 Eval 的自然效果不属于本任务完成证据。

实施时先运行新增针对性测试，再运行 python3 -m unittest discover -s tests，以及 Strict 同步、两个包 build/verify 和独立包端到端测试。临时产物必须在临时目录，不读写用户其他项目。

## Execution Order and Effort

1. 身份与绑定约定及测试：人类工程师约 1–1.5 日。
2. 进程内检查、分层诊断和受检恢复：约 1–2 日。
3. 独立分发、回归与短文档：约 1 日。

总计约 3–5 工程日，属于初步估计；Agent 用时在接口冻结和测试基线确认后再估算。先建立身份约定才能正确组合诊断；打包验证最后保证实际交付能力一致。

委派前每项任务必须写明拥有文件、输入规格、验收编号、验证命令、失败条件及证据。执行 Agent 使用用户指定的 Terra-high；主控独立集成审核。实施不包含全局安装、合并、远程推送或业务 Eval。

## Files Reference

| 文件 | 变更 |
|---|---|
| scripts/skill_package.py | 保留 CLI，复用/提取现有包检查 |
| scripts/sync_context_strict_skill.py | 同步新增 Strict 工具和测试 |
| src/managing_long_task_context/__init__.py | 暴露受检接口，保留原 API |
| src/managing_long_task_context/runtime_identity.py（新增） | Strict 进程身份与受检恢复 |
| scripts/context_doctor.py（新增） | 统一诊断 CLI |
| scripts/context_identity_core.py（新增） | 标准库共享绑定/报告逻辑，由同步生成分发副本 |
| skills/context-lite/scripts/context_lite.py | 接入身份与受检恢复 |
| skill-package.json、skills/context-lite/skill-package.json | 版本包声明 |
| SKILL.md、skills/context-lite/SKILL.md、README.md | 简短入口和兼容边界 |
| references/runtime-identity.md（新增） | 完整使用指引与证明限制 |
| tests/test_runtime_identity.py、tests/test_context_doctor.py（新增） | 单元/集成/回归 |
| tests/test_skill_packages.py、tests/test_distribution.py | 分发与单一来源检查 |

以下补充冻结新增接口；它们是待开发接口，不是现有能力。

## Frozen Interface Addendum

### CLI 与 Python

每个分发包包含 scripts/context_doctor.py，命令如下。所有路径参数必须为绝对路径；PACKAGE 为包根目录，CONTEXT 为已有上下文存储根目录，实际任务目录为 CONTEXT/TASK。TASK 只允许 [A-Za-z0-9][A-Za-z0-9._-]{0,127}，禁止 . 和 ..，不做有损重命名。

```sh
python3 PACKAGE/scripts/context_doctor.py check --mode full --package-root PACKAGE
python3 PACKAGE/scripts/context_doctor.py check --mode identity --package-root PACKAGE --context-root CONTEXT --workspace-root WORKSPACE --task-id TASK
python3 PACKAGE/scripts/context_doctor.py init-binding --package-root PACKAGE --expected-manifest-sha256 HASH --context-root CONTEXT --workspace-root WORKSPACE --task-id TASK
python3 PACKAGE/scripts/context_doctor.py resume --package-root PACKAGE --context-root CONTEXT --workspace-root WORKSPACE --task-id TASK
```

Strict 独立包运行时，操作者显式设置 PYTHONPATH，以下命令同时作为独立包验收启动方式（PACKAGE 替换为真实绝对路径）：

```sh
PYTHONPATH=PACKAGE/src python3 PACKAGE/scripts/context_doctor.py check --mode full --package-root PACKAGE
PYTHONPATH=PACKAGE/src python3 PACKAGE/scripts/context_doctor.py resume --package-root PACKAGE --context-root CONTEXT --workspace-root WORKSPACE --task-id TASK
```

Lite 不需要该环境变量。测试另外覆盖错误 PYTHONPATH 被检出；缺模块映射为 unknown/RUNTIME_UNVERIFIED，不能依赖开发环境偶然可导入。

check full 可选带完整任务参数三元组，不能只带部分；不带时只证明包与本诊断进程、临时冒烟任务，不证明任何真实任务。此时 binding=null、真实 binding 检查 not_run，scope=package；带三元组时 scope=task 且绑定检查必须参与总状态。identity/resume/init-binding 必须带完整三元组。参数使用错误归入 fail/INPUT_INVALID、退出 1；帮助命令退出 0。

Strict 暴露以下关键字接口，路径支持 str 或 Path，结果均为 dict：

```python
runtime_identity(*, package_root)
checked_resume(task_id, *, package_root, workspace_root, base_dir)
```

runtime_identity 返回同一报告格式（scope=runtime，mode=identity，binding=null）；它只验证本进程，不需要任务绑定。checked_resume 返回 {"diagnostic": report, "context": brief_or_null}；所有诊断未通过时 context=null。brief 的原始 ContextError 仍向 Python 调用者传播，CLI 转换成 fail/RESUME_BLOCKED 且 context=null，不绕过原规则。

扩展 bind(base_dir, *, workspace_root=None, package_root=None)，两个新参数必须同时提供才能调用 bound.checked_resume(task_id)。两者均缺省保留全部旧语义；仅提供一个报 ValueError。新绑定客户端在创建时捕获真实路径，之后不读 cwd 推断工作区，也不允许 bound.checked_resume 覆盖捕获参数。未提供新参数调用 bound.checked_resume 返回 unknown/BINDING_MISSING。

Lite 在现有 scripts/context_lite.py 增加 resume 子命令，参数与 doctor resume 相同。doctor 的 Lite resume 必须通过该 validator 实际执行，返回相同 diagnostic/context 包装；context 为校验通过的 NOW 文本，失败 null。已核实 _write 使用旧 --base-dir/.context-lite/TASK/NOW.md；新 --context-root 明确指向 .context-lite 本身，故 CONTEXT/TASK/NOW.md 与旧布局相同，禁止再重复拼接 .context-lite。复用 validate_text，不改变旧 write 参数语义。

### 报告类型

所有报告字段均存在，无值用 null；未知额外字段仅允许未来提升 schema 后添加：

```text
schema: 1
mode: "full" | "identity" | "init"
scope: "package" | "task" | "runtime"
status: "pass" | "fail" | "unknown"
checked_at: UTC RFC3339 string
full_verification: "pass" | "fail" | "unknown" | "not_run"
identity: null | {
  skill_name: string|null, skill_version: string|null,
  package_root: string|null, runtime_path: string|null,
  process_id: integer, observation_source: "current_process",
  expected_manifest_sha256: string|null,
  actual_manifest_sha256: string|null, loaded_manifest_sha256: string|null,
  capabilities: string[]
}
binding: null | {schema: 1, task_id: string, skill_name: string,
  expected_manifest_sha256: string, workspace_root: string,
  context_root: string, created_at: UTC RFC3339 string}
checks: {name: string, status: "pass"|"fail"|"unknown"|"not_run",
  code: string|null, message: string}[]
codes: string[] (unique, sorted)
next_action: string|null
```

BINDING_MISSING、BINDING_INVALID、RUNTIME_UNVERIFIED、READ_FAILED 属 unknown；确认的路径/存储/包身份不匹配、BINDING_CONFLICT、INPUT_INVALID、SMOKE_FAILED、RESUME_BLOCKED 属 fail。full 清理失败新增 CLEANUP_FAILED，属 fail，报告保留临时目录路径供定位。包缺 manifest 属 unknown，存在但校验不匹配属 fail。异常只输出类型和必要路径，不输出原文或环境变量。

### 进程基线与边界

Strict 包导入时捕获 __init__.py、evidence.py、truth_sources.py、runtime_identity.py 及生成的 _identity_core.py 的真实路径，并捕获所属 manifest 的摘要；基线只保存在当前进程内。在这些受控模块加载前后各读取 manifest 摘要，缺失、读取失败或前后不一致使基线未知，拒绝受检恢复直到重启。禁止首次调用 checked_resume 时才补造加载基线。

Lite 在 validator 启动并加载共享模块时执行同样的前后 manifest 核对，保存两个脚本的真实路径；不从另一 CLI 的报告导入基线。doctor 对 Strict 调用实际 Python 导入解析，不在探测前修改 sys.path 来强制加载期望包；发现错误路径必须报告，不自行修复。运行者可显式配置 PYTHONPATH 后重试，但工具不代做。

identity 每次重新读取绑定与 manifest 摘要，并比较进程基线和期望摘要；不逐文件算哈希。manifest 不变而代码被替换不在轻量检查保证范围，由 full 检出。完整性诊断不认证恶意运行时、不保证原子安装以外的并发替换；这些限制必须出现在文档中。重启后且任务仍绑定旧 manifest 时仍拒绝，不能把重启当作重绑定。

初始化/恢复的 workspace_root 若位于 Git 中，必须与 git rev-parse --show-toplevel 的真实路径相同；非 Git 时使用明确目录。检查以显式传入或客户端捕获的 WORKSPACE 对比绑定，cwd 不是身份输入。context_root 可以在工作区外，但 TASK 目录及其绑定文件不能通过 symlink 逃离指定真实 CONTEXT；同一任务目录不同 WORKSPACE 初始化必然冲突。

### 确定的分发映射

| 开发单一来源 | Strict 包目标 | Lite 包目标 |
|---|---|---|
| scripts/context_doctor.py | scripts/context_doctor.py | scripts/context_doctor.py |
| scripts/context_identity_core.py | scripts/context_identity_core.py 及 src/managing_long_task_context/_identity_core.py | scripts/context_identity_core.py |
| scripts/skill_package.py | scripts/skill_package.py | scripts/skill_package.py |
| src/managing_long_task_context/runtime_identity.py | src/managing_long_task_context/runtime_identity.py | 不需要 |

采用复制现有标准库包校验脚本，保持 verify_package 算法单一来源，本轮不提取新包校验框架。doctor 从自己的 scripts 目录导入共享模块及 skill_package，Strict runtime 从包内相对导入 _identity_core，禁止 cwd-based 导入。共享模块不得依赖 scripts 包名、开发根目录或 gstack。

新增 scripts/sync_context_tools.py 生成上表的工具副本，现有 sync_context_strict_skill.py 调用它，保持现有同步入口可用。对每个映射做字节一致性检查。Strict payload 增加 scripts；Lite 已有 scripts。版本提升 Strict/root 到 0.6.0、Lite 到 1.2.0，新能力名 runtime-identity/v1、workspace-binding/v1、context-doctor/v1、checked-resume/v1；Strict 声明新增公开 Python 接口，Lite 保持 CLI 能力声明。全部是本轮版本规划，不代表已发布。

### 无副作用定义

check 与 resume 的诊断阶段均只读真实任务；full 仅在临时目录进行样例写入。init-binding 是唯一允许在真实任务目录新增绑定的命令，不属于只读自检，其并发/原子性单独验证。预期阻断样例通过必须核对具体错误码，而非任意异常都视为通过。

## Rollback Plan

回退代码和文档即可停用新入口；保留新增 context-binding.json，不删除任务材料。原合同、事件和 NOW 保持字节不变，旧 API 可继续使用但不享有新身份保证。全局安装、合并、推送单独交付，不在本规格执行中自动进行。

## Out of Scope

gbrain/数据库接入、远程同步、增量语义检索、跨项目共享、自动修复、自动重绑定、自动选择 Skill；改变现有 unknown/conflict/时效/完成门禁；证明模型实际阅读内容；证明恶意运行时可信；在线 Eval 或 token 节省结论。

## Related

来源为本项目 /setup-gbrain 借鉴讨论及用户确认的 /spec 草案；Issue 搜索 doctor identity workspace 未发现未关闭重复项。

