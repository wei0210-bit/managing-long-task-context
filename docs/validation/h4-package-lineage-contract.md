# H4 执行合同 v1：包血统只读报告

发布者：调度会话。日期：2026-09-22。执行者：Grok 4.6。
本合同冻结。执行者不得修改目标、范围、禁止项、交付物或验证项。现场与合同冲突时停下，带证据汇报。

原设计第五节：安装时核对 `source_revision` 是否为 `origin/main` 的祖先，并让 `context_doctor check` 增加 `package_lineage`。

## 现场

- 仓库：`/Users/zhaowei/Desktop/David/project.nosync/managing-long-task-context`
- 分支：`codex/strict-0.8.2-usage-hardening`
- HEAD：`190feaf`。该提交尚未推送。本任务的新提交也不得推送。
- 版本现在是 0.8.5。本任务升到 **0.8.6**。
- 本机验证用 `/opt/homebrew/bin/python3.12`。含 `git init` 的测试在沙箱外跑。
- 不安装、不推送、不改 `~/.codex`、`~/.claude`。不 amend `190feaf` 或更早提交。不改用户的全局 git config。

## 为什么这样收口

- `scripts/context_doctor.py` 与 `scripts/context_identity_core.py` 在 `test_reg_06` 的保护名单里，相对 `097c952` 不能有 diff。因此 doctor 的 `check` 不增加 `package_lineage`。
- `scripts/skill_package.py` 的 `build` 被现有测试用 `git:test-revision`、`candidate:`、`test:` 调用。这些不是可解析提交。在 `build` 里拒绝它们会打红现有测试。因此 `build` 与 `verify` 的接受条件不变。
- 维护者在构建或安装前单独运行只读报告。`git:` 加可解析提交且该提交是 `origin/main` 的祖先才是 pass。`local:` 必须显式确认。其余修订为 unknown，不阻断现有构建。

## 目标

1. 新增只读 `package_lineage_report`。
2. 可解析的 `git:` 提交：是 `origin/main` 的祖先则 pass，否则 fail。
3. `local:` 未确认则 warn，确认后 pass。
4. 无法解析的修订为 unknown，且 `skill_package.py build` 仍接受它们。
5. 全量现有测试仍通过。版本 0.8.6。一个新提交。不推送。

## 允许修改

- 新增 `scripts/package_lineage.py`
- 新增 `tests/test_package_lineage.py`
- `SKILL.md`：只在 “Usage freshness” 节后增加一节 “Package lineage”
- `scripts/sync_context_strict_skill.py`：在 `COPIED_FILES` 里紧接 `Path("scripts/handoff_preflight.py"),` 之后插入一行 `Path("scripts/package_lineage.py"),`
- `tests/test_distribution.py`：在其独立黄金元组的同一位置插入同一行。不改断言。
- `pyproject.toml`：只把 `version` 改为 `0.8.6`
- `skill-package.json`：只改 `skill_version` 与 `package_version` 为 `0.8.6`。不重排 `capabilities` 或其他键。
- 运行 `scripts/sync_context_strict_skill.py` 后，`skills/context-strict/` 里由同步生成的对应文件
- 新增本任务报告 `docs/validation/h4-package-lineage-report.md`（不提交）

## 禁止

- 不改 `scripts/context_doctor.py`、`scripts/context_identity_core.py`、`scripts/skill_package.py`
- 不改 `src/managing_long_task_context/__init__.py`、`evidence.py`、`handoff.py`
- 不改 `skills/context-lite/`，也不要把新脚本加入 `scripts/sync_context_tools.py`
- 不把新测试文件加入 `COPIED_FILES`
- 不改 `test_reg_06` 的保护名单
- 不在 `build` 或 `verify` 里拒绝 `candidate:`、`test:` 或不可解析的 `git:`
- 不安装、不推送
- 不提交 `.DS_Store`、`SESSION-HANDOFF-20260916.md`、`方案对话内容.txt`、`docs/validation/e4-e6-*`、`docs/validation/h3-*`、本合同或本报告
- 测试里的 `git config` 只作用于临时仓库，禁止 `--global`

## 函数

`package_lineage_report(repo, source_revision, *, confirmed_local=False) -> dict`

- 只读。不创建、不修改、不删除文件。git 失败不抛异常。
- 只用 `git -C <repo>`。默认分支引用固定为 `origin/main`。
- 返回：

```json
{"status": "pass", "codes": [], "source_revision": "git:abc", "default_ref": "origin/main"}
```

- `source_revision` 去掉首尾空白后为空：`status` 为 `fail`，`codes` 含 `PACKAGE_LINEAGE_MISSING`。
- 以 `local:` 开头：`confirmed_local` 为 false 时 `warn` + `PACKAGE_LINEAGE_LOCAL_UNCONFIRMED`；为 true 时 `pass`，`codes` 为空。
- 以 `git:` 开头且冒号后是 7 到 40 位十六进制：用 `git rev-parse --verify <sha>^{commit}` 解析。解析成功后用 `git merge-base --is-ancestor <full-sha> origin/main`。退出码 0 为 `pass`。退出码 1 为 `fail` + `PACKAGE_LINEAGE_NOT_ON_DEFAULT`。引用不存在或其他 git 失败为 `unknown` + `PACKAGE_LINEAGE_UNRESOLVED`。
- `git:test-revision`、`candidate:`、`test:` 以及其他形状：`unknown` + `PACKAGE_LINEAGE_UNRESOLVED`。
- CLI：`python3 scripts/package_lineage.py --repo <path> --source-revision <text> [--confirm-local]`。stdout 是上述 JSON。`pass`、`warn`、`unknown` 退出码 0；`fail` 退出码 1。

## SKILL.md

在 Usage freshness 之后增加：

```markdown
## Package lineage

构建或安装前运行 `scripts/package_lineage.py --repo <仓库绝对路径> --source-revision <revision>`。`git:` 后接可解析提交，且该提交是 `origin/main` 的祖先时，报告为 pass。`local:` 必须同时传入 `--confirm-local`，否则为 warn。`candidate:`、`test:` 以及其他无法解析的修订为 unknown，不改变 `skill_package.py build`。`context_doctor.py` 不包含这项检查。
```

## 测试必须覆盖

用临时 git 仓库，不读取本仓库的 `origin/main` 作为通过条件。

- 祖先提交 → `pass`，退出码 0
- 不在 `origin/main` 历史上的提交 → `fail`，`PACKAGE_LINEAGE_NOT_ON_DEFAULT`，退出码 1
- `local:note` 无 `--confirm-local` → `warn`
- `local:note` 有 `--confirm-local` → `pass`
- `candidate:dirty` 与 `git:test-revision` → `unknown`，`PACKAGE_LINEAGE_UNRESOLVED`
- 没有 `origin/main` → `unknown`
- 空修订 → `fail`，`PACKAGE_LINEAGE_MISSING`
- 调用前后临时仓库已跟踪内容的哈希不变
- 现有 `tests/test_skill_packages.py` 仍通过，以证明 `build` 仍接受 `git:test-revision`

## 验证

| 项 | 通过标准 |
|---|---|
| V1 | `git diff --name-only 190feaf -- scripts/context_doctor.py scripts/context_identity_core.py scripts/skill_package.py scripts/sync_context_tools.py src/managing_long_task_context/__init__.py skills/context-lite` 无输出 |
| V2 | 沙箱外 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /opt/homebrew/bin/python3.12 -m unittest tests.test_package_lineage` 为 OK |
| V3 | 沙箱外 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_distribution test_real_migration_regression test_skill_packages` 为 OK |
| V4 | 沙箱外 `PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 -m unittest discover -s tests` 为 OK，0 failures |
| V5 | 根目录 `skill_version`、`package_version` 与 `pyproject.toml` 版本都是 `0.8.6` |
| V6 | `git diff 190feaf -- skill-package.json` 只有 `skill_version` 与 `package_version` 两行 |
| V7 | `check_source` 对仓库根为 pass |
| V8 | `git rev-list --count 190feaf..HEAD` 为 1。`git branch -r --contains HEAD` 无输出。该提交不含禁止提交的文件 |

## 交付

- 上述代码、测试、文档与同步结果
- 一个提交，信息说明为何增加只读包血统报告
- `docs/validation/h4-package-lineage-report.md`：逐项 V1–V8 的 pass/fail 与命令输出摘要。不提交该报告
- 任一 V 失败则不得声称完成，不得改验证标准
