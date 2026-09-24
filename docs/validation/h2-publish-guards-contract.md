# H2 执行合同 v1：发布校验、三种内置证据、打包拒绝副本

发布者：调度会话。日期：2026-09-22。执行者：Grok 4.6。
本合同冻结。执行者不得修改目标、范围、禁止项、交付物或验证项。现场与合同冲突时停下，带证据汇报。

## 现场

- 仓库：`/Users/zhaowei/Desktop/David/project.nosync/managing-long-task-context`
- 分支：`codex/strict-0.8.2-usage-hardening`
- HEAD：`c9e9932`，未推送，基于 `origin/main`。
- 版本现在是 0.8.2。本任务升到 **0.8.3**。
- 本机验证用 `/opt/homebrew/bin/python3.12`。沙箱内 `git init` 会失败，测试在沙箱外跑。
- 不安装、不推送、不改 `~/.codex`、`~/.claude`。

## 为什么这样收口

8D 的合同把不存在的路径和自由文本写进 `workspace_root` / `required_evidence`。当前 `publish_contract` 不检查路径是否存在；未启用 `evidence-handlers/v1` 时，证据类型只要是非空字符串就通过。仓库测试依赖后一种宽松行为（`custom`、`synthetic`、`integration-test`、`fixture` 等）。因此：

- 不在 `publish_contract` 拒绝 `workspace_root`。`tests/test_independent_validation.py` 的 FR01 要求无效工作区仍能发布，并在 completion gate 返回 `MISSING_CONTRACT_WORKSPACE_ROOT` 或 `INVALID_CONTRACT_WORKSPACE_ROOT`。
- 缺失、非绝对、或不存在的 `workspace_root` 由只读 `contract_compat_report` 警告。
- 不在发布时拒绝未知证据类型。未知类型由同一报告指出。
- 新内置类型只在合同声明 `evidence-handlers/v1` 并使用对应 builtin capability 时参与机器判定。

## 修订 R2（2026-09-22）

执行方在修订后停下是对的。发布者已核对：

- `tests/test_context.py:294` 把缺失证据的报错钉成四种。这行来自 `sorted(BUILTIN_RESOLVER_CAPABILITIES)`，不是 `__init__.py` 里的手写列表。允许且仅允许把该字符串改成排序后的七种：`['command-output', 'evidence-manifest', 'file', 'git-commit', 'screenshot', 'test-report', 'url']`。
- `test_reg_06` 冻结了整个 `skills/context-lite` 以及 `src/managing_long_task_context/__init__.py`。`scripts/sync_context_tools.py` 会把 `skill_package.py` 抄进 Lite，所以打包拒绝副本必然会改 Lite 的那一个文件。
- `__init__.py` 不得改。`contract_compat_report` 放在 `evidence.py`，测试从 `managing_long_task_context.evidence` 导入。若工作树里的 `__init__.py` 已加入导出，先还原到 `c9e9932`。

R2 额外允许：

- `tests/test_context.py` 仅那一条 `built-in evidence types` 字符串。
- `tests/test_real_migration_regression.py` 的 `test_reg_06`：`skills/context-lite/scripts/skill_package.py` 可以相对 `097c952` 变化，且必须与根目录 `scripts/skill_package.py` 字节相同。该测试保护的其他路径仍必须无 diff。

## 目标

1. 增加只读 `contract_compat_report`，指出缺失、非绝对或不存在的工作区，以及未映射到内置或已声明 handler 的证据类型。`publish_contract` 的接受范围不变。
2. 增加三种内置证据：`command-output`、`screenshot`、`evidence-manifest`。只更新 R1 点名的那一条旧断言。
3. `check-source` 拒绝 payload 里 macOS 副本文件名（含 ` 2.` 或以 ` 2` 结尾）。
4. 全量现有测试仍通过。新行为有新测试。版本 0.8.3，一个新提交。不推送。

## 允许修改

- `src/managing_long_task_context/__init__.py`
- `src/managing_long_task_context/evidence.py`
- `scripts/skill_package.py`
- `SKILL.md`（只加下面规定的短节）
- `skill-package.json`、`pyproject.toml`：只改版本号到 `0.8.3`。禁止重排 `capabilities` 或其他字段。
- `scripts/sync_context_strict_skill.py` 的 `COPIED_FILES`：仅当新增了必须进包的文件时才加条目。本任务不新增必须进包的文件，因此不要改这个列表。
- `tests/test_distribution.py`：仅当 `COPIED_FILES` 真有新增时才同步那一行。预期是不改。
- 新文件只允许：`tests/test_publish_guards.py`
- R1：`tests/test_evidence.py` 里 `test_default_resolvers_exposes_only_the_four_builtin_kinds` 的集合断言，且只能把期望集合改为七种内置 kind。可以改测试函数名。不得改该文件其他断言。
- 由 sync 脚本生成的 `skills/context-strict/` 对应副本。

## 禁止

- 不实现 H3：不给 `audit`/`brief`/`gate` 加账本停更、checkpoint 间隔、合同版本上限。
- 不拒绝未启用 `evidence-handlers/v1` 的自由文本证据类型。
- 不拒绝临时目录。测试和工作树都合法地使用它们。
- 不要求 `workspace_root` 字段必填。
- 除 R1 点名的那一条集合断言外，不改既有测试断言。若其他旧测试变红，停下汇报。
- 不重排 `skill-package.json` 的 `capabilities`。
- 不改 8D 项目、不读改 `project.nosync/.prime`。
- 不推送、不安装、不改本合同。

## 行为

### 1. workspace_root

不要在 `publish_contract` 或 `_validate_contract_shape` 新增对 `workspace_root` 的拒绝。FR01 的无效值必须仍能发布。

### 2. contract_compat_report

在包内 `evidence.py` 提供 `contract_compat_report(contract) -> dict`。不要从 `__init__.py` 导入或写入 `__all__`。不抛异常，不写文件。返回：

```json
{"status": "pass|warn", "warnings": ["..."]}
```

`warnings` 包含：

- `workspace_root` 缺失、不是绝对路径，或 `Path(value).expanduser().is_dir()` 为假。数字等非字符串也算警告。
- 某条验收标准的证据类型既不在内置集合（含本节新增的三种），也没有出现在 `evidence_handlers.types`。

没有上述问题时 `status` 为 `pass`，`warnings` 为空。不要把它接进 `publish_contract` 的失败路径。

### 3. 三种内置 resolver

加入 `BUILTIN_RESOLVER_CAPABILITIES` 与 `default_resolvers()`：

| kind | capability |
|---|---|
| `command-output` | `builtin:command-output/v1` |
| `screenshot` | `builtin:screenshot/v1` |
| `evidence-manifest` | `builtin:evidence-manifest/v1` |

路径规则复用 `_local_path`：必须落在 `workspace_root` 或 `evidence_roots` 内，沿用现有大小上限。

- `command-output`：文件非空、UTF-8。可选 `must_contain` / `must_not_contain`（字符串列表）。缺内容为 `FAIL`，非法 UTF-8 为 `FAIL`。
- `screenshot`：后缀 `.png`、`.jpg` 或 `.jpeg`；PNG 以 `\x89PNG` 开头，JPEG 以 `\xff\xd8\xff` 开头；大小大于 0。若有 `artifact_digest`，按现有 `sha256:` 规则比对。不引入图像库。
- `evidence-manifest`：UTF-8 文本。每一非空行是 `shasum -a 256` 形式：64 位小写 hex、两个空格、相对路径。相对路径相对 manifest 所在目录，解析后仍须在允许根内。任一文件缺失或摘要不符为 `FAIL`。空 manifest 为 `FAIL`。

这三种在调用方未提供 verifier 时，使用内置 verifier：三个 resolver 层都是 `pass` 则 claim 为 `pass`，否则 claim 为 `unknown` 且代码 `CLAIM_NOT_VERIFIED`。不得改变 `file`、`git-commit`、`test-report`、`url` 在未提供 verifier 时的现有行为。

### 4. check-source

payload 文件名包含 ` 2.` 或以 ` 2` 结尾时，`check_source` 失败，code 为 `PACKAGE_DUPLICATE_COPY`。不要把 `.DS_Store` 算进本条。

### 5. SKILL.md

在 `## Hard stops` 之前加一节，标题 `## Publish guards`。写明：新合同应填写现存绝对目录 `workspace_root`，并启用 `evidence-handlers/v1`；自由文本证据类型不会被发布拒绝，用 `managing_long_task_context.evidence.contract_compat_report` 检查。不要删改 Session migration 或 Multi-bot 节。然后运行 sync，使 `skills/context-strict/SKILL.md` 只差 `name:`。

### 6. 版本与提交

`skill-package.json` 与 `pyproject.toml` 的版本改为 `0.8.3`。运行 `scripts/sync_context_strict_skill.py`。一个新提交，信息：

`feat: reject missing workspaces at publish and add builtin evidence kinds`

提交后工作树里已跟踪文件不得再有修改。`docs/validation/h2-*.md` 保持未跟踪，不要提交。

## 验证

`PY=/opt/homebrew/bin/python3.12`。每项单独 PASS/FAIL。

| ID | 通过标准 |
|---|---|
| V1 | 新测试覆盖 `contract_compat_report`：现存绝对目录且证据类型为 `file` 时 `status=pass`；缺失、相对路径、不存在路径、普通文件、数字各产生至少一条 warning 且不抛异常。这些无效值调用 `publish_contract` 仍成功（用临时目录，测完删除）。 |
| V2 | `contract_compat_report` 对示例合同中的 `file` 类型为 `pass` 或仅因示例 `workspace_root` 不存在而 warning；对证据类型 `合并提交号` 且无 handler 时 warning 非空且不抛异常。 |
| V3 | 三种 kind 各有正例与反例：空命令输出失败、PNG/JPEG 魔数通过、错误魔数失败、manifest 摘要不符失败、越出允许根失败。未提供 verifier 时正例 claim 为 `pass`。`file` 类型在未提供 verifier 时 claim 仍不是 `pass`。 |
| V4 | 在临时目录放一个名为 `experience 2.py` 的文件并让 `check-source` 扫到它，结果 `status=fail` 且 codes 含 `PACKAGE_DUPLICATE_COPY`。当前仓库 `check-source` 仍为 `pass`。 |
| V5 | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src $PY -m unittest discover -s tests` 末行 `OK` 或 `OK (skipped=N)`，0 failures，0 errors，`Ran` ≥ 665。 |
| V6 | 版本命令输出 `0.8.3 0.8.3`。`git diff c9e9932 -- skill-package.json` 除版本号外，若有 `required_paths` 以外的重排则 FAIL。预期 diff 只有版本号，以及 sync 带来的 skill 副本版本号。 |
| V7 | `git diff --name-only c9e9932..HEAD` 不得含 `tests/test_distribution.py`，除非 `COPIED_FILES` 实际新增了文件。`tests/test_evidence.py` 的 diff 只能是那一条集合断言（及可选的函数名）。`tests/test_context.py` 的 diff 只能是那一条 built-in evidence types 字符串。`src/managing_long_task_context/__init__.py` 相对 `c9e9932` 无 diff。不得含 `ledger_activity`、`ephemeral_workspace`。 |
| V8 | 未推送：`git branch -r --contains HEAD` 无输出。相对 `c9e9932` 恰好 1 个提交。 |
| V9 | 包外 `check-source`、`verify`、`context_doctor.py check --mode full` 对 context-strict 为 `"status": "pass"`，且 `skill_version` 为 `0.8.3`。 |

## 交付

报告写到 `docs/validation/h2-publish-guards-report.md`（不要提交）。逐项 V1–V9。任一 FAIL 不得声称完成。
