# H2b 执行合同 v1：收窄副本文件名规则

发布者：调度会话。日期：2026-09-22。执行者：Grok 4.6。
本合同冻结。冲突时停下，带证据汇报。

## 现场

- 仓库：`/Users/zhaowei/Desktop/David/project.nosync/managing-long-task-context`
- 分支：`codex/strict-0.8.2-usage-hardening`
- HEAD：`38bfc38`。不要 amend。
- 规则在 `scripts/skill_package.py`：`" 2." in name or name.endswith(" 2")`。
- 它会误伤 `chapter 20.py`、`notes 2.1.md`。
- 验证用 `/opt/homebrew/bin/python3.12`。测试在沙箱外跑。不推送，不安装。

## 目标

把副本判断收成：文件名以 ` 2` 结尾，或 ` 2` 后面只跟最后一个扩展名。版本升到 **0.8.4**。一个新提交。

## 允许修改

- `scripts/skill_package.py`
- `skills/context-strict/scripts/skill_package.py`
- `skills/context-lite/scripts/skill_package.py`
- 这三份 `skill_package.py` 必须字节相同。
- `tests/test_publish_guards.py`：只扩展 `test_check_source_rejects_duplicate_copy_and_repo_still_passes`，或在同类里加用例。
- `pyproject.toml`、`skill-package.json`，以及 `skills/context-strict/` 下对应的版本字段。只改版本号到 `0.8.4`，不要重排 `capabilities`。

## 禁止

- 不 amend `38bfc38`。
- 不改 `__init__.py`、`evidence.py`、`test_reg_06`。
- 不跑会改动其他文件的全量 sync。只复制 `skill_package.py`，并手改版本号。
- 不推送，不安装，不改本合同。

## 行为

文件名判断改为匹配 ` 2(\.[^.]+)?$`。

| 文件名 | 结果 |
|---|---|
| `experience 2.py` | `PACKAGE_DUPLICATE_COPY` |
| `experience 2` | `PACKAGE_DUPLICATE_COPY` |
| `file.tar 2.gz` | `PACKAGE_DUPLICATE_COPY` |
| `chapter 20.py` | 通过 |
| `notes 2.1.md` | 通过 |
| `v2.py` | 通过 |

`.DS_Store` 继续跳过。当前仓库 `check-source` 仍为 pass。

## 验证

| ID | 通过标准 |
|---|---|
| V1 | 上表六种文件名都有测试，结果符合表。当前仓库 `check-source` 为 pass。 |
| V2 | 三份 `skill_package.py` 的 SHA256 相同。 |
| V3 | `python3.12 -c` 打印 skill 与 package 版本，输出 `0.8.4 0.8.4`。`git diff 38bfc38 -- skill-package.json` 只有版本号。 |
| V4 | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python3.12 -m unittest test_publish_guards test_distribution test_real_migration_regression` 为 OK，0 failures。原命令未把 `tests` 放入 `PYTHONPATH`，会导致 `import test_handoff_preflight` 失败；该失败不是本变更的回归。发布者于 2026-09-22 在沙箱外重跑修正命令：`Ran 41 tests` / `OK`。 |
| V5 | 相对 `38bfc38` 恰好 1 个提交，未推送。`git diff --name-only 38bfc38..HEAD` 不得出现上表允许修改之外的文件。 |

提交信息：`fix: match only Finder duplicate filenames in package check`

报告写到 `docs/validation/h2b-duplicate-name-report.md`，不要提交。逐项 V1–V5。任一 FAIL 不得声称完成。
