# E5 Lite 短会话接续执行报告

执行工作区：`.worktrees/short-session-remaining`。冻结合同
`docs/validation/e5-execution-contract.md` 已在开始前核对 SHA-256：
`2c93b048f7091936950c33661e25f9e997d7e0ad71449108b3f9887f6757cdba`。
本单没有安装、提交、推送、远程工单、生产／业务动作或额外模型调用；也没有改动
既有 E3 未提交工作、共享包声明、版本、CI 或 Strict 引擎。

## 接缝与冻结验收映射

测试接缝是 Lite 公共 `flush` CLI、完整包身份绑定后的 `cold-check` CLI 和它们的
原子文件边界。每个 `ContextLiteHandoffTests.setUp` 都从 Lite 源码临时构建一个完整
包、以该包的 manifest hash 初始化绑定，并从该包的 `scripts/context_lite.py` 启动
独立 Python 进程。新测试的根定位也支持其被复制到 `context-lite/tests/` 后直接
运行，不依赖源码工作区；所有 NOW 输入均为 synthetic fixture。

1. `test_flush_matches_atomic_write_and_is_idempotent`：flush 复用 write，首写和重复
   写的内容／mtime／摘要一致。
2. `test_flush_preserves_old_now_for_validation_goal_and_atomic_write_failures` 与既有
   validator 覆盖：坏标题、First、字符超限、同 ID 目标冲突及注入的 `os.replace`
   中断均保留旧 NOW，沿用旧错误码。
3. `test_cold_check_returns_material_only_after_identity_bound_resume`：完整包＋绑定后
   只读返回 task、原字节 SHA-256、目标、全部七段、唯一 First 及刷新映射；
   不返回原 `context` 正文。
4. `test_cold_check_preserves_resume_hard_stops`：requires-rule-proof、错工作区、错包
   均无恢复材料；可选 experience 参数仍由原 resume 成对参数门禁处理。
5. `test_cold_check_refuses_bad_or_changed_handoff_hash_without_material` 与
   `test_cold_check_refuses_a_now_change_after_identity_and_first_read`：坏／错指纹、首次
   字节读取后变化均为 unknown 且无材料。
6. `test_cold_checks_are_repeatable_read_only_and_never_execute_refresh_refs`：20 个独立
   Python 进程仅靠临时完整包、绑定和 NOW 给出同一份材料；这是程序冷读取，不是模型
   冷启动或语义验证证据。
7. 同一 20 次测试核对 NOW mtime 未变、两个 `read:` 目标未被创建，故不执行 refresh／
   recovery 引用，也不重试 unknown 的 in-flight。
8. `test_short_workflow_reference_keeps_semantics_pending`、既有 router 回归及范围自审：
   Skill 只补短流程和按需引用，保留 hard stops；未加入 Strict 身份／授权控制引擎，旧
   validator/router 行为保持通过。

额外边界反例：`test_cold_check_keeps_crlf_bytes_as_the_handoff_version` 证明交接摘要来自
首次原始 CRLF 字节；`test_unchanged_flush_hashes_existing_crlf_bytes` 证明 existing CRLF
文件的 unchanged flush 对磁盘字节哈希；`test_flush_digest_uses_the_written_bytes_without_a_post_write_read`
证明 flush 不在写后另读目标而把旧写报告与新字节混合；`test_cold_check_extracts_the_unique_first_action_and_all_next_items`
保留完整 Next 段并在 validator 容许的空白形式中正确提取唯一 First。

## TDD 原始输出

先仅加入新行为测试后执行冻结命令，红灯为功能缺口而非导入失败：

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_context_lite_validator test_context_skill_router test_context_lite_handoff -v
Ran 19 tests in 2.510s
FAILED (failures=9)
context_lite.py: error: argument command: invalid choice: 'cold-check'
context_lite.py: error: argument command: invalid choice: 'flush'
AssertionError: False is not true  # references/short-session.md absent
```

最初功能实现后的同命令绿灯为 19/19、3.719 秒。主控随后的字节边界审阅发现三个具体
风险：CRLF 的旧文本回写摘要、非有界 read_bytes、以及 flush 写后另读。已最小修补为：
cold-check 首次和二次读取均以最多 32,000 UTF-8 字节捕获（合法 NOW 最多 8,000 Unicode
字符），首次原始字节同时决定材料和 SHA-256；flush 使用 `_write` 捕获的写入／既存原始
字节。最终针对性绿灯原始尾部如下：

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_context_lite_validator test_context_skill_router test_context_lite_handoff -v
Ran 25 tests in 5.008s
OK
```

## 修改清单与自审

- `skills/context-lite/scripts/context_lite.py`：新增 flush、identity-bound cold-check、
  原字节摘要和有界二次读取；`write`／`resume` 的公开旧输出不变。
- `skills/context-lite/SKILL.md`：仅补短接续流程和不可替代 finish 的 hard stop。
- `skills/context-lite/references/short-session.md`：只读接续、独立观察与语义 pending 边界。
- `tests/test_context_lite_handoff.py`：25 项目标组合中的 12 项新增交接行为测试；其余 13
  项是冻结命令指定的既有 validator/router 回归。
- `docs/validation/e5-executor-report.md`：本报告。

`git diff --check` 无输出。作用域状态仅显示上述五类授权文件；现有 E3 和其他脏文件未改。

## NOT_RUN／不可声称事项

- 未运行全仓库测试、真实宿主、真实新会话、模型评分器或自然业务路径；25/25 不是这些证明。
- 未生成／安装／发布完整包。本单临时包测试仅证明隔离包的本地 CLI 与绑定路径；主控仍须
  统一处理 `payload_roots`、`required_paths`、版本、分发和 CI 后独立复核。
- `history_inheritance` 仍为 `unknown`，`semantic_verification` 仍为 `pending`，
  `archive_allowed` 恒为 `false`。文本合法、哈希相同或两进程材料相同不构成语义冷启动、
  控制权、完成或归档许可。
