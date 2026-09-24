# H4 包血统只读报告执行报告

执行代理：Grok 4.6。日期：2026-09-22。
合同：`docs/validation/h4-package-lineage-contract.md`（未改合同）。
结论：**完成。V1–V8 全部 PASS。未推送。合同与报告未提交。**

## 开工与交付

| 项目 | 值 |
|---|---|
| 分支 | `codex/strict-0.8.2-usage-hardening` |
| 基线 HEAD | `190feaff4b88bfc276db04aff278dadc572fde0e` |
| 交付 HEAD | `11d65cfb14b366a5fe59cb89f22e8d4fc366712f` |
| 提交信息 | `feat: add a read-only package lineage report so maintainers can confirm origin/main ancestry without changing build` |
| 相对 190feaf 提交数 | 1 |
| 版本 | 0.8.6 |

未 amend。未 checkout 其他分支。未 fetch/pull/push。未改用户全局 git config。未安装。合同与报告未提交。

## 实现要点

- 新增只读 `package_lineage_report`。不改 `build`、`verify`、`context_doctor check`。
- 可解析 `git:` 提交是 `origin/main` 祖先 → pass；否则 `PACKAGE_LINEAGE_NOT_ON_DEFAULT`。
- `local:` 未确认 → warn；`--confirm-local` → pass。
- `candidate:`、`test:`、`git:test-revision` 及其他无法解析修订 → unknown，不阻断现有构建。
- `SKILL.md` 在 Usage freshness 后增加 Package lineage 节。
- 黄金清单与 sync 脚本各只插入合同指定的一行。随后跑 `scripts/sync_context_strict_skill.py`。
- 只改根目录 `skill-package.json` 的 `skill_version` 与 `package_version`，未重排 `capabilities`。
- 测试里的 `git config` 只作用于临时仓库，未使用 `--global`。

## V1–V8

| ID | 结果 | 证据 |
|---|---|---|
| V1 | **PASS** | `git diff --name-only 190feaf -- scripts/context_doctor.py scripts/context_identity_core.py scripts/skill_package.py scripts/sync_context_tools.py src/managing_long_task_context/__init__.py skills/context-lite` 无输出。 |
| V2 | **PASS** | 沙箱外 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /opt/homebrew/bin/python3.12 -m unittest tests.test_package_lineage`（`required_permissions` 含 `all`）→ `Ran 8 tests in 0.863s`，`OK`。 |
| V3 | **PASS** | 沙箱外 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_distribution test_real_migration_regression test_skill_packages`（`required_permissions` 含 `all`）→ `Ran 40 tests in 6.735s`，`OK`。 |
| V4 | **PASS** | 沙箱外 `PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 -m unittest discover -s tests`（`required_permissions` 含 `all`）→ `Ran 692 tests in 95.023s`，`OK (skipped=1)`，0 failures。 |
| V5 | **PASS** | 打印根目录 `skill-package.json` 的 `skill_version` 与 `package_version`，以及 `pyproject.toml` 版本，输出 `0.8.6 0.8.6 0.8.6`。 |
| V6 | **PASS** | `git diff 190feaf -- skill-package.json` 只改 `skill_version` 与 `package_version` 两行（0.8.5 → 0.8.6）。 |
| V7 | **PASS** | `/opt/homebrew/bin/python3.12 scripts/skill_package.py check-source --source .` → `{"codes":[],"errors":[],"stats":{"documented_paths_checked":13,"files_checked":107,"python_exports_checked":21},"status":"pass"}`。 |
| V8 | **PASS** | `git rev-list --count 190feaf..HEAD` 为 `1`。`git branch -r --contains HEAD` 无输出。提交 `11d65cf` 文件仅：`SKILL.md`、`pyproject.toml`、`scripts/package_lineage.py`、`scripts/sync_context_strict_skill.py`、`skill-package.json`、`skills/context-strict/SKILL.md`、`skills/context-strict/pyproject.toml`、`skills/context-strict/scripts/package_lineage.py`、`skills/context-strict/skill-package.json`、`tests/test_distribution.py`、`tests/test_package_lineage.py`。未纳入 `.DS_Store`、`SESSION-HANDOFF-20260916.md`、`方案对话内容.txt`、`docs/validation/e4-e6-*`、`docs/validation/h3-*`、本合同或本报告。 |

## 提交后工作树

未跟踪（按合同不得提交）：

- `.DS_Store`
- `SESSION-HANDOFF-20260916.md`
- `docs/validation/e4-e6-github-delivery.md`
- `docs/validation/e4-e6-github-summary.md`
- `docs/validation/h3-usage-freshness-contract.md`
- `docs/validation/h3-usage-freshness-report.md`
- 本合同 `docs/validation/h4-package-lineage-contract.md`
- `方案对话内容.txt`
- 本报告 `docs/validation/h4-package-lineage-report.md`
