# E6 执行者报告：本地 usage 观察与压力建议

执行时间（UTC）：2026-09-15T14:30:40Z。执行合同 SHA-256 已在开始时实测为 `74be2152547da2fd8ebd4bbfc169805cdfb41de2d7d898a32797399c957ccf9a`。范围只限 `scripts/context_usage.py`、`tests/test_context_usage.py`、`references/context-usage.md` 与两份既有观察文档的追加；未修改同步、包、CI 或共享状态，未安装、提交、发送、抓价格、调用模型、读完整真实聊天或执行业务动作。

## 交付

- 两个公开纯函数：`summarize_usage(events)` 与 `evaluate_pressure(sample, previous=None, *, now)`；无持久化、轮询或自动动作。
- 一次性标准库 CLI：`summarize` / `pressure` 只读显式常规 JSON 文件；1 MiB / 1000 记录上限，重复键、NaN、UTF-8、非常规文件、坏结构均结构化 unknown。
- 计数口径：`input_tokens` 是报送原值；`normalized_input_tokens` 只在 `separate` cache 口径下纳入 cache。`total_tokens` 是完整提供观察集总量，不是窗口读数或全任务总量；空 usage 为 unknown，明确零事件可为 0。

## TDD 原始关键输出

首轮 RED（保守 stub 后的真实行为失败）：

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_context_usage -v
Ran 10 tests in 0.036s
FAILED (failures=12)
```

主控反例到达后，执行者先新增反例；当时无界 `list(events)` 使无限 generator 测试在约 30 秒后被主动终止。该 RED 同时显示完成/执行未知优先级失败，以及 `mode` / `cache_accounting` / `basis` 的 list/dict 触发 TypeError。主控独立冻结探针当时为 12 methods、4 failures + 5 errors（含 subtests）。这不是测试成功或自然运行证据。

GREEN（全部合成资料）：

```text
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_context_usage -v
Ran 17 tests in 0.193s
OK

PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 docs/validation/e6_controller_probes.py -q
Ran 13 tests in 0.001s
OK
```

用同一 17 项合成测试在单独 Python 进程记录到 `0.199s`，`resource.getrusage(RUSAGE_SELF).ru_maxrss=27066368`（原始单位由宿主 Python 提供，未换算或与 token 混同）。`/usr/bin/time -l` 的测试本体已全绿（17 tests / 0.229s），但其后续 `sysctl kern.clockrate` 被沙箱拒绝，故该命令退出 1；不把它写成内存测量成功。模型 tokens、真实费用、重试成本、Skill 归因、全任务覆盖与产品收益均 **UNKNOWN**。

## 反例修复与自审

- `safe_point=true` 的有效当前窗口在阈值上/上方可 `prepare`，不再要求 `milestone=true`；milestone 仅用于过期/未知读数的明确安全降级。
- `task_complete` 与 `execution_unknown` 先于过期分支处理，均只 `defer`，不产生里程碑通知。
- 迭代输入逐条截断到第 1001 条；文件用 `lstat`、`O_NOFOLLOW|O_NONBLOCK`、`fstat` 和最多 1 MiB+1 的分块读取，避免 `read_bytes`/FIFO/替换路径造成无界读取或挂起。
- list/dict 的 mode、cache 口径、basis 均回退 unknown，不抛栈；累计窗口、超窗口、缺量和空事件集同样不制造低压力或 0 使用幻觉。
- 同样 sample 的 20 次输入只通知第一次；内容改变是 explicit unknown，跨 session 的 previous 不去重。函数返回的 previous 仅供调用方自有局部记录，工具自身不写第二权威状态。

`git diff --check` 无输出，CLI `--help` 可调用。执行者交付时生产脚本320行；主控随后仅格式化，新格式为555行，行为未改变并复跑17/17及13/13。维持两条公共纯函数及小CLI，未触及合同外代码。此报告完成后，执行者停止写入，等待主控独立复核；不声称真实宿主或自然项目验证完成。
