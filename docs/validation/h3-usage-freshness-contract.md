# H3 执行合同 v1：账本新鲜度只读报告

发布者：调度会话。日期：2026-09-22。执行者：Grok 4.6。
本合同冻结。执行者不得修改目标、范围、禁止项、交付物或验证项。现场与合同冲突时停下，带证据汇报。

## 现场

- 仓库：`/Users/zhaowei/Desktop/David/project.nosync/managing-long-task-context`
- 分支：`codex/strict-0.8.2-usage-hardening`
- HEAD：`8b3ae8b`。该提交已推送。本任务的新提交不得推送。
- 版本现在是 0.8.4。本任务升到 **0.8.5**。
- 本机验证用 `/opt/homebrew/bin/python3.12`。含 `git init` 的测试在沙箱外跑。
- 不安装、不推送、不改 `~/.codex`、`~/.claude`。不 amend `8b3ae8b` 或更早提交。

## 为什么这样收口

原设计要把账本停更放进 `audit()`，把超过 72 小时的 checkpoint 放进 `gate(stage="handoff")` 变成 unknown，并让 `brief()` 带出警告。这三处都在 `src/managing_long_task_context/__init__.py`。`tests/test_real_migration_regression.py` 的 `test_reg_06` 要求该文件相对 `097c952` 无 diff。因此：

- 不修改 `audit`、`brief`、`gate`、`checkpoint`、`publish_contract`。
- 新增只读函数。交接前由调用方自己跑。报告可以是 `unknown`，但既有门禁返回值不变。
- 仓库没有“任务已关闭”标志。checkpoint 间隔不另判关闭状态。

## 目标

1. 新增 `usage_freshness_report`。
2. 账本之后仍有非账本文件更新时给出 warning。
3. 最近 checkpoint 早于 72 小时，或没有 checkpoint，报告为 unknown。
4. 合同 `version` 大于 5 时给出 warning。
5. 任务目录里名为 `.DS_Store`，或文件名匹配 ` 2(\.[^.]+)?$` 的条目，给出 warning。`chapter 20.py`、`notes 2.1.md` 不报。
6. 全量现有测试仍通过。版本 0.8.5。一个新提交。不推送。

## 允许修改

- 新增 `src/managing_long_task_context/usage_freshness.py`
- 新增 `tests/test_usage_freshness.py`
- `SKILL.md`：只在 “Publish guards” 节后增加一节 “Usage freshness”
- `scripts/sync_context_strict_skill.py`：在 `COPIED_FILES` 里紧接 `Path("src/managing_long_task_context/evidence.py"),` 之后插入一行 `Path("src/managing_long_task_context/usage_freshness.py"),`
- `tests/test_distribution.py`：在其独立黄金元组的同一位置插入同一行。不改断言。
- `pyproject.toml`：只把 `version` 改为 `0.8.5`
- `skill-package.json`：只改 `skill_version` 与 `package_version` 为 `0.8.5`。不重排 `capabilities` 或其他键。
- 运行 `scripts/sync_context_strict_skill.py` 后，`skills/context-strict/` 里由同步生成的对应文件
- 新增本任务报告 `docs/validation/h3-usage-freshness-report.md`（不提交）

## 禁止

- 不改 `src/managing_long_task_context/__init__.py`、`evidence.py`、`handoff.py`、`runtime_identity.py`、`host_codex_native.py`、`host_claude_native.py`
- 不改 `scripts/skill_package.py`、`scripts/context_doctor.py`、`scripts/context_identity_core.py`、`skills/context-lite/`
- 不把新测试文件加入 `COPIED_FILES`
- 不改 `test_reg_06` 的保护名单
- 不在 `publish_contract` 或 `gate` 里拒绝高版本、旧 checkpoint 或副本文件名
- 不实现安装血统检查（原第五节）
- 不提交 `.DS_Store`、`SESSION-HANDOFF-20260916.md`、`方案对话内容.txt`、`docs/validation/e4-e6-*`、本合同或本报告
- 不推送、不安装

## 函数

`usage_freshness_report(task_root, *, now, checkpoint_gap_hours=72, contract_version_cap=5) -> dict`

- 只读。不创建、不修改、不删除文件。缺文件或坏 JSON 不抛异常，记为 unknown。
- `now` 必须是带时区的 UTC datetime。naive datetime 抛 `ValueError`。
- 不跟随符号链接，不计符号链接。
- 账本文件：`task-contract.json`、`events.jsonl`、`snapshot.json`、`.lock`，以及 `handoff/` 目录树。其余普通文件若 `st_mtime` 晚于最后一条事件的 `created_at`，计入 `LEDGER_ACTIVITY`。
- 最后一条事件是 `events.jsonl` 最后一个非空行。该行不是合法 JSON，或没有合法 `created_at`，则 `LEDGER_UNREADABLE`。
- checkpoint 时间取 `snapshot.json` 的 `latest_checkpoint.created_at`。没有 snapshot、没有 checkpoint 或时间无法解析，则 `CHECKPOINT_MISSING`。年龄严格大于 `checkpoint_gap_hours` 则 `CHECKPOINT_GAP`。
- 合同版本取 `task-contract.json` 的整数 `version`。大于 `contract_version_cap` 则 `CONTRACT_VERSION_CAP`。缺失或不是 int 则 `CONTRACT_VERSION_UNREADABLE`。等于上限不报。
- 目录项名称（文件或目录，不含路径前缀）为 `.DS_Store`，或匹配 ` 2(\.[^.]+)?$`，则每个一条 `STRAY_NAME`。
- 返回：

```json
{
  "status": "pass",
  "warnings": [{"code": "LEDGER_ACTIVITY", "message": "..."}],
  "stats": {
    "ledger_newer_files": 0,
    "checkpoint_age_hours": 1.0,
    "contract_version": 1
  }
}
```

- `CHECKPOINT_GAP`、`CHECKPOINT_MISSING`、`LEDGER_UNREADABLE`、`CONTRACT_VERSION_UNREADABLE` 使 `status` 为 `unknown`。
- 仅有 `LEDGER_ACTIVITY`、`CONTRACT_VERSION_CAP`、`STRAY_NAME` 时 `status` 为 `warn`。
- 没有任何条目时 `status` 为 `pass`。既有 unknown 又有 warning 时，`status` 为 `unknown`，`warnings` 含全部条目。

## SKILL.md

在 Publish guards 之后增加：

```markdown
## Usage freshness

交接前调用 `managing_long_task_context.usage_freshness.usage_freshness_report(task_root, now=...)`。它只读任务目录。账本停更、合同版本超过 5、以及名为 `.DS_Store` 或匹配末尾 ` 2` 副本的条目会给出 warning。最近一次 checkpoint 早于 72 小时，或缺少 checkpoint，报告状态为 unknown。`audit`、`brief`、`gate` 的既有结论不变。
```

## 测试必须覆盖

- 一个比最后事件新的普通文件 → `LEDGER_ACTIVITY`，`ledger_newer_files == 1`
- 只有账本文件 → 无 `LEDGER_ACTIVITY`
- checkpoint 早于 `now` 73 小时 → `status == "unknown"` 且含 `CHECKPOINT_GAP`
- checkpoint 早于 `now` 1 小时、`version == 5`、无多余文件 → `status == "pass"`
- `version == 6` → 含 `CONTRACT_VERSION_CAP`
- `notes 2.md` 与 `.DS_Store` 报 `STRAY_NAME`；`chapter 20.py` 与 `notes 2.1.md` 不报
- 调用前后目录字节不变
- 目录不存在 → `status == "unknown"`，不抛异常
- naive `now` → `ValueError`

## 验证

| 项 | 通过标准 |
|---|---|
| V1 | `git diff --name-only 8b3ae8b -- src/managing_long_task_context/__init__.py src/managing_long_task_context/evidence.py src/managing_long_task_context/handoff.py scripts/skill_package.py skills/context-lite` 无输出 |
| V2 | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /opt/homebrew/bin/python3.12 -m unittest tests.test_usage_freshness` 为 OK |
| V3 | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_distribution test_real_migration_regression` 在沙箱外为 OK |
| V4 | `PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 -m unittest discover -s tests` 在沙箱外为 OK，0 failures |
| V5 | 打印根目录 `skill-package.json` 的 `skill_version` 与 `package_version`，以及 `pyproject.toml` 版本，三者都是 `0.8.5` |
| V6 | `git diff 8b3ae8b -- skill-package.json` 只有 `skill_version` 与 `package_version` 两行 |
| V7 | `check_source` 对仓库根为 pass |
| V8 | 相对 `8b3ae8b` 恰好一个新提交；`git status -sb` 显示该提交未推送（ahead 1）。工作树没有本合同禁止提交的文件被纳入该提交 |

## 交付

- 上述代码、测试、文档与同步结果
- 一个提交，信息说明为何增加只读新鲜度报告
- `docs/validation/h3-usage-freshness-report.md`：逐项 V1–V8 的 pass/fail 与命令输出摘要。不提交该报告
- 任一 V 失败则不得声称完成，不得改验证标准
