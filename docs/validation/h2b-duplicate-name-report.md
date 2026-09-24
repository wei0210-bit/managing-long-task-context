# H2b 副本文件名规则执行报告

执行代理：Grok 4.6。日期：2026-09-22。
合同：`docs/validation/h2b-duplicate-name-contract.md`（未改合同）。
结论：**未完成。V4 FAIL。不得声称完成。**

## 开工与交付

| 项目 | 值 |
|---|---|
| 分支 | `codex/strict-0.8.2-usage-hardening` |
| 基线 HEAD | `38bfc3850c13375af190c50ff0c4ab16e5c1c6c8` |
| 交付 HEAD | `68b65df846899973e2c5d341a01f64ea5b5a98c0` |
| 提交信息 | `fix: match only Finder duplicate filenames in package check` |
| 相对 38bfc38 提交数 | 1 |
| 版本 | 0.8.4 |

未 amend。未 checkout 其他分支。未 fetch/pull/push。未改 git config。合同与报告未提交。

## 实现要点

- `check_source` 用 ` 2(\.[^.]+)?$` 判断 Finder 副本名。
- 三份 `skill_package.py` 只复制，未跑全量 sync。
- `test_check_source_rejects_duplicate_copy_and_repo_still_passes` 覆盖合同六种文件名。
- 只改允许清单里的版本号到 `0.8.4`，未重排 `capabilities`。

## V1–V5

| ID | 结果 | 证据 |
|---|---|---|
| V1 | **PASS** | 六种文件名均在 `test_check_source_rejects_duplicate_copy_and_repo_still_passes`：`experience 2.py` / `experience 2` / `file.tar 2.gz` → `PACKAGE_DUPLICATE_COPY`；`chapter 20.py` / `notes 2.1.md` / `v2.py` → 通过。当前仓库 `check_source` 输出 `pass []`。 |
| V2 | **PASS** | 三份 `skill_package.py` SHA256 均为 `97656664d4247f4cb6fe4c81976093167d029378bc9cbba5244f4a5277be52fd`。 |
| V3 | **PASS** | `/opt/homebrew/bin/python3.12 -c` 打印 skill 与 package 版本，输出 `0.8.4 0.8.4`。`git diff 38bfc38 -- skill-package.json` 只改 `skill_version` 与 `package_version`。 |
| V4 | **FAIL** | 合同原文命令 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3.12 -m unittest tests.test_publish_guards tests.test_distribution tests.test_real_migration_regression` 为 `FAILED (errors=1)`，不是 OK。`tests.test_real_migration_regression` 导入失败：`ModuleNotFoundError: No module named 'test_handoff_preflight'`（`tests/test_real_migration_regression.py:25`）。该 import 在 `38bfc38` 已存在，未改该文件。仓库惯用命令 `PYTHONPATH=src:tests ... -m unittest test_publish_guards test_distribution test_real_migration_regression` 为 `Ran 41 tests` / `OK`；这不是合同 V4，不能用来改判。 |
| V5 | **PASS** | 相对 `38bfc38` 恰好 1 个提交 `68b65df`。`git branch -r --contains HEAD` 无输出。`git diff --name-only 38bfc38..HEAD` 仅：`pyproject.toml`、`scripts/skill_package.py`、`skill-package.json`、`skills/context-lite/scripts/skill_package.py`、`skills/context-strict/pyproject.toml`、`skills/context-strict/scripts/skill_package.py`、`skills/context-strict/skill-package.json`、`tests/test_publish_guards.py`。 |

## 冲突（停下）

V4 作为冻结合同不可改写。原文命令在本仓库不可达：`PYTHONPATH=src` 且以 `tests.test_*` 加载时，`test_real_migration_regression` 的兄弟模块 import 失败。这是合同核验与现场的冲突，不是实现回归。需要调度方修订 V4 后再签发。
