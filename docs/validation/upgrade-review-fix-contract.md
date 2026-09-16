# R1–R4 最小修复与验证合同

用户已批准上一轮四项审核发现的修复；2026-09-15 冻结。原报告与复现脚本保留，不改旧预期洗绿。

## 边界

在 `codex/short-session-remaining` 候选工作区修改三个维护源及其现有测试：`host_records.py`、`host_codex_cli.py`、`scripts/context_usage.py`。同步生成 Strict/Lite 副本，更新本地验证报告与恢复导航。只用隔离合成任务/固定 Python CLI；不运行真实模型或业务，不全局安装、提交、合并、推送。不得降低身份、代次、授权、完成门禁和 unknown 禁重试策略。

## 已批准的公开 seam 与验收

| ID | 入口 | 冻结预期与验证 |
| --- | --- | --- |
| R1 | prepare_handoff → cancel_handoff → HostTaskLedger.reserve | 首次取消后当前 source controller 的 start/resume 可预留一次；重复不可再次启动；prepared、错 session/身份、错误代次仍拒绝；使用真实产品函数和合成可信宿主，不 mock 状态机 |
| R2 | CodexCliHost.start_child / resume_child | 同一行不同 thread_id 或重复键均 execution_unknown，不能以最后一个键放行；有界原始输出仍保存，不能解锁后续重复执行 |
| R3 | 同上 | 10000 层且小于 64KiB 的 JSON 不抛未处理异常，返回 execution_unknown，保留输出与退出观察；正常 JSON 路径不退化 |
| R4 | evaluate_pressure / pressure CLI | session_id、sample_id、额外字段的孤立代理字符在正常计量与缺量里程碑均 unknown；CLI 退出2、JSON可读、无 traceback；正常 Unicode 保持可用 |

逐个 seam 先测试红再最小实现绿；既有测试及新测试完整包内都可运行。完成验收：针对性回归、全量 unittest（旧完整包明确注入、无 skip）、两包 check-source/build/verify/源码树外测试、git diff --check。未运行或失败不得算完成，模型效果及 token 收益仍 UNKNOWN。

## 命令与证据

环境：Python 3.12，`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests`。定向模块：`test_handoff_host_records`、`test_handoff_codex_cli`、`test_context_usage`；全量 `python -m unittest discover -s tests -q`。旧包环境 `MLTC_LEGACY_PACKAGE` 沿用已核实完整 0.7.0 基线。逐片记录命令、退出码、实际断言失败、通过数/耗时；修复结果另存报告，原审核报告保持历史。
