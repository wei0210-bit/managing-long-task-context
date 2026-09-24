# H2 发布校验执行报告

执行代理：Grok 4.6。日期：2026-09-22。
合同：`docs/validation/h2-publish-guards-contract.md`（含修订 R2，未改合同）。
结论：**完成。V1–V9 全部 PASS。未推送。合同与报告未提交。**

## 开工与交付

| 项目 | 值 |
|---|---|
| 分支 | `codex/strict-0.8.2-usage-hardening` |
| 基线 HEAD | `c9e9932216d050eb09dfd9d0cb9ee4412c55f204` |
| 交付 HEAD | `38bfc3850c13375af190c50ff0c4ab16e5c1c6c8` |
| 提交信息 | `feat: reject missing workspaces at publish and add builtin evidence kinds` |
| 相对 c9e9932 提交数 | 1 |
| 版本 | 0.8.3 |

未 checkout 其他分支。未 fetch/pull/push。未改 git config。`src/managing_long_task_context/__init__.py` 相对 `c9e9932` 无 diff。`docs/validation/h2-*.md` 未跟踪。

## 实现要点

- `contract_compat_report` 只在 `evidence.py`。测试从 `managing_long_task_context.evidence` 导入。
- 不在 `publish_contract` 拒绝 `workspace_root`。
- 三种内置 kind：`command-output`、`screenshot`、`evidence-manifest`。未提供 verifier 时三层 pass 则 claim=pass。
- `check_source` 对文件名含 ` 2.` 或以 ` 2` 结尾报 `PACKAGE_DUPLICATE_COPY`。
- `SKILL.md` 增加 `## Publish guards`，指向 `managing_long_task_context.evidence.contract_compat_report`。`skills/context-strict/SKILL.md` 只差 `name:`。
- R1：`tests/test_evidence.py` 七种 kind 集合。
- R2：`tests/test_context.py` 七种 builtin 报错字符串；`test_reg_06` 仅允许 Lite 的 `skill_package.py` 变化，并断言与根目录字节相同。

## V1–V9

| ID | 结果 | 证据 |
|---|---|---|
| V1 | **PASS** | `tests/test_publish_guards.py`：现存绝对目录 + `file` → `status=pass`；缺失/相对/不存在/普通文件/数字各至少一条 warning；这些无效值 `publish_contract` 成功。临时目录测完删除。 |
| V2 | **PASS** | 示例合同仅因 `workspace_root=/absolute/path/to/project` 不存在而 warning；`合并提交号` 无 handler 时 warning 非空。 |
| V3 | **PASS** | 空命令输出失败；PNG/JPEG 魔数通过；错误魔数失败；manifest 摘要不符失败；越出允许根失败。正例无 verifier 时 claim=pass。`file` 无 verifier 时 claim 不是 pass。 |
| V4 | **PASS** | 临时包放入 `experience 2.py` 后 `check-source` 为 fail 且含 `PACKAGE_DUPLICATE_COPY`。当前仓库 `check-source` 为 pass。 |
| V5 | **PASS** | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /opt/homebrew/bin/python3.12 -m unittest discover -s tests` → `Ran 675 tests in 94.686s`，`OK (skipped=1)`，0 failures，0 errors。 |
| V6 | **PASS** | 版本命令输出 `0.8.3 0.8.3`。`git diff c9e9932 -- skill-package.json` 只有 `skill_version` 与 `package_version`。 |
| V7 | **PASS** | `git diff --name-only c9e9932..HEAD` 不含 `tests/test_distribution.py`。`tests/test_evidence.py` 只改那一条集合断言（及函数名）。`tests/test_context.py` 只改那一条 built-in 字符串。`__init__.py` 无 diff。无 `ledger_activity`、`ephemeral_workspace`。 |
| V8 | **PASS** | `git branch -r --contains HEAD` 无输出。相对 `c9e9932` 恰好 1 个提交。已跟踪文件干净。 |
| V9 | **PASS** | 包外 check-source / verify / doctor 均为 `"status": "pass"`。verify 与 doctor 的 `skill_version` 均为 `0.8.3`。manifest `80459bb88c35ef4f92fddf1c334b3a88cebc41f412ff260a96517b48a738c7a4`。 |

## 包外核验摘录

check-source：`{"status":"pass","codes":[]}`

verify identity：`skill_name=context-strict`，`skill_version=0.8.3`，`package_version=0.8.3`，`status=pass`

doctor full：`status=pass`，`skill_version=0.8.3`，`full_verification=pass`
