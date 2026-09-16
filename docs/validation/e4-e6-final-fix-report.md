# E4-E6 最终集中修复执行记录

范围、停止线与冻结依据：`e4-e6-final-fix-contract.md` 在开始时的 SHA-256 为
`1814b7ed2e077351f9ddb3c1f21f0c25afe53ac98bc36106bff46d55528d3582`。只改合同
列出的 Lite helper、根测试/同步/分发/清单/CI、使用说明和本报告；未提交、安装、同步
工作区生成副本、运行全套、调用业务/远程/付费能力。

## 改动

- F1：`tests/test_context_lite_handoff.py` 补真实磁盘两读间替换为不同 goal 的反例，断言
  `NOW_CHANGED_DURING_COLD_CHECK`、`unknown` 和无 material；原始字节 digest、CRLF、mtime、
  原子失败和 goal 冲突断言保留。工作源已有的 cold-check 两读字节相等门禁满足此例。
- F2/F5：`scripts/context_usage.py` 将 `previous.notified` 作为已通知历史保留；未通知的
  defer 不消耗后来安全里程碑的首次提醒。缺失/非法窗口数值只在身份、时间、四个 bool 与
  安全里程碑全部有效时给一次 `milestone`，从不构造百分比或 `prepare`；累计口径、时间/身份/
  安全字段缺失、完成和执行未知仍不走该分支。
- F3：所有输入时间及直接 `now` 的 UTC 换算捕获 UTC 范围溢出，返回结构化 unknown；合法跨
  时区观察继续有效。
- F4：Lite validator 的 ROOT/TOOL 可从包根定位；同步脚本、required_paths、分发一致性检查
  和包外 CI 都纳入该 validator。`references/context-usage.md` 同步说明 F5 裁决取代旧的
  “缺量一律 unknown”候选行为。

## RED（先行为）

命令：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_context_lite_validator test_context_lite_handoff test_context_usage -q
```

原始结果：`Ran 42 tests in 1.634s`，`FAILED (failures=17, errors=5)`，shell 记录
`EXIT=1 ELAPSED_S=2`。关键原始失败为：

- 两个 `0001-...+23:59` / `9999-...-23:59` 例在 `_parse_time(...).astimezone()` 抛
  `OverflowError: date value out of range`，CLI stdout 为空而不能给 JSON；
- 低占用 defer 后同 sample 到期仍 `notify=false`；
- 缺失/非法/超窗口数值仍为 `unknown`，未给受限 milestone；
- 新增 required path 尚未由主控同步到 `skills/context-lite/tests/` 时，包检查明确报
  `PACKAGE_REQUIRED_PATH_MISSING: tests/test_context_lite_validator.py`。

## GREEN 与自审

- 根 usage 针对性：`test_context_usage`，`Ran 23 tests in 0.259s`，`OK`，
  `EXIT=0 ELAPSED_S=0`。
- 独立 E6 probes：`docs/validation/e6_controller_probes.py`，`Ran 13 tests in 0.001s`，
  `OK`，`EXIT=0`。
- 为验证 F1/F4 的包根行为，使用临时、可复核副本
  `/private/tmp/e4-e6-lite-source.4XBYtC`：先复制 `skills/context-lite`，仅向**临时**副本
  放入根 `tests/test_context_lite_validator.py`，未运行同步脚本、未改工作区生成副本；命令为
  `cd /private/tmp/e4-e6-lite-source.4XBYtC/context-lite && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts:tests /opt/homebrew/bin/python3.12 -m unittest test_context_lite_validator test_context_lite_handoff -q`；
  原始结果 `Ran 18 tests in 4.548s`，`OK`，`EXIT=0 ELAPSED_S=5`。
- 静态自审：`rg` 确认两个 UTC 换算点均由异常边界包围，notified 仅从 `previous` 读取并保留；
  `git diff --check`（当前可追踪授权文件）退出 `0`。未发现 `automatic_action` 变更，仍为 false。

## 已知、预期未绿项与停写

合同指定三模块命令在未同步工作区直接复跑的原始结果为 `Ran 42 tests in 1.741s`，
`FAILED (failures=13)`，`EXIT=1 ELAPSED_S=2`；13 项均在 handoff `setUp` 的 package build
阶段由同一个 `PACKAGE_REQUIRED_PATH_MISSING: tests/test_context_lite_validator.py` 导致，未进入
业务断言。此为合同明确要求保留、由主控统一同步生成后消除的包清单差异；没有改测试预期或
再次重跑红测。主控仍需同步根工具/测试/说明、构建包并运行冻结三模块命令、包外 CI 和全回归。

本执行者至此停写。

## 复审更正：F1 unchanged-flush 与 F5 口径（追加）

此前 F1 记录错误地把 cold-check 两读当作关闭依据；`_flush` / `_write` unchanged 入口当时
没有源码改动。现已以同一入口的真实磁盘替换反例更正：目标先被验证为 candidate，随后在
`_read` 与 digest 读取之间分别替换为不同 goal、同 goal 不同 state 的合法 NOW。修复前，临时
包副本 `/private/tmp/e4-e6-f1-red3.YeaRJU/context-lite` 运行
`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=scripts:tests /opt/homebrew/bin/python3.12 -m unittest test_context_lite_handoff -q`
得到 `Ran 14 tests in 4.003s`、两项 F1 failure、`EXIT=1 ELAPSED_S=4`；错误输出是
`status: unchanged` 搭配替换后的 `now_sha256`。修复后 `_write(..., include_persisted_bytes=True)`
在返回 raw-byte hash 前，以 universal-newline 文本同源校验第二读；不同文本返回
`unknown/NOW_CHANGED_DURING_FLUSH` 且无 `now_sha256`。CRLF 仍只归一用于同源比较，hash 仍取
原始 persisted bytes。绿色临时副本
`/private/tmp/e4-e6-f1-green2.fGo0zx/context-lite` 的同一命令得到 `Ran 14 tests in 4.200s`、
`OK`、`EXIT=0 ELAPSED_S=5`，其中包含原 CRLF、mtime、旧 write/原子失败断言。

F5 另补有效口径门：fallback 只接受字符串 `current-window` 或 `estimate`，在任何缺量分支前
拒绝 `cumulative`、`delta`、任意字符串、列表和 `None`，不会对不可哈希值抛异常。修复前根
`test_context_usage` 为 `Ran 23 tests in 0.272s`、4 个非法 basis failure、`EXIT=1`；修复后命令
`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_context_usage -q`
为 `Ran 23 tests in 0.276s`、`OK`、`EXIT=0`。主控独立原入口 probe 以
`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests:docs/validation /opt/homebrew/bin/python3.12 -m unittest e4_e6_final_controller_probes -q`
验证 F1/F5，`Ran 2 tests in 0.004s`、`OK`、`EXIT=0`。

本执行者在本次更正后再次停写；仍未同步、构建或运行全套。
