# H3 账本新鲜度只读报告执行报告

执行代理：Grok 4.6。日期：2026-09-22。
合同：`docs/validation/h3-usage-freshness-contract.md`（未改合同）。
结论：**完成。V1–V8 全部 PASS。未推送。合同与报告未提交。**

## 开工与交付

| 项目 | 值 |
|---|---|
| 分支 | `codex/strict-0.8.2-usage-hardening` |
| 基线 HEAD | `8b3ae8b18bfecd8400882ddd607fab9ee158f5fb` |
| 交付 HEAD | `190feaff4b88bfc276db04aff278dadc572fde0e` |
| 提交信息 | `feat: add a read-only usage freshness report so handoff can see stale ledgers without changing gates` |
| 相对 8b3ae8b 提交数 | 1 |
| 版本 | 0.8.5 |

未 amend。未 checkout 其他分支。未 fetch/pull/push。未改 git config。未安装。合同与报告未提交。

## 实现要点

- 新增只读 `usage_freshness_report`。不改 `audit`、`brief`、`gate`、`checkpoint`、`publish_contract`。
- 账本之后的普通文件更新 → `LEDGER_ACTIVITY`；checkpoint 缺口或缺失 → `unknown`；合同 `version > 5` → warning；`.DS_Store` 与 ` 2(\.[^.]+)?$` → `STRAY_NAME`。
- 不跟随、不计符号链接。缺文件或坏 JSON 不抛异常。
- `SKILL.md` 在 Publish guards 后增加 Usage freshness 节。
- 黄金清单与 sync 脚本各只插入合同指定的一行。随后跑 `scripts/sync_context_strict_skill.py`。
- 只改根目录 `skill-package.json` 的 `skill_version` 与 `package_version`，未重排 `capabilities`。

## V1–V8

| ID | 结果 | 证据 |
|---|---|---|
| V1 | **PASS** | `git diff --name-only 8b3ae8b -- src/managing_long_task_context/__init__.py src/managing_long_task_context/evidence.py src/managing_long_task_context/handoff.py scripts/skill_package.py skills/context-lite` 无输出。 |
| V2 | **PASS** | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /opt/homebrew/bin/python3.12 -m unittest tests.test_usage_freshness` → `Ran 9 tests in 0.014s`，`OK`。 |
| V3 | **PASS** | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_distribution test_real_migration_regression` 在沙箱外（`required_permissions` 含 `all`）→ `Ran 31 tests in 5.536s`，`OK`。 |
| V4 | **PASS** | `PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 -m unittest discover -s tests` 在沙箱外 → `Ran 684 tests in 93.925s`，`OK (skipped=1)`，0 failures。 |
| V5 | **PASS** | 打印根目录 `skill-package.json` 的 `skill_version` 与 `package_version`，以及 `pyproject.toml` 版本，输出 `0.8.5 0.8.5 0.8.5`。 |
| V6 | **PASS** | `git diff 8b3ae8b -- skill-package.json` 只改 `skill_version` 与 `package_version` 两行（0.8.4 → 0.8.5）。 |
| V7 | **PASS** | `python3.12 scripts/skill_package.py check-source --source .` → `{"codes":[],"errors":[],"stats":{"documented_paths_checked":12,"files_checked":105,"python_exports_checked":21},"status":"pass"}`。 |
| V8 | **PASS** | 相对 `8b3ae8b` 恰好 1 个提交 `190feaf`。`git status -sb` 为 `## codex/strict-0.8.2-usage-hardening...origin/codex/strict-0.8.2-usage-hardening [ahead 1]`。`git branch -r --contains HEAD` 无输出。提交文件仅：`SKILL.md`、`pyproject.toml`、`scripts/sync_context_strict_skill.py`、`skill-package.json`、`skills/context-strict/SKILL.md`、`skills/context-strict/pyproject.toml`、`skills/context-strict/skill-package.json`、`skills/context-strict/src/managing_long_task_context/usage_freshness.py`、`src/managing_long_task_context/usage_freshness.py`、`tests/test_distribution.py`、`tests/test_usage_freshness.py`。未纳入 `.DS_Store`、`SESSION-HANDOFF-20260916.md`、`方案对话内容.txt`、`docs/validation/e4-e6-*`、本合同或本报告。 |

## 提交后工作树

未跟踪（按合同不得提交）：

- `.DS_Store`
- `SESSION-HANDOFF-20260916.md`
- `docs/validation/e4-e6-github-delivery.md`
- `docs/validation/e4-e6-github-summary.md`
- `docs/validation/h3-usage-freshness-contract.md`
- `方案对话内容.txt`
- 本报告 `docs/validation/h3-usage-freshness-report.md`
