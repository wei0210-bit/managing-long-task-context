# R1–R4 修复验收

状态：**LOCAL_VERIFIED**，2026-09-15。四项审核缺陷已修复，本轮全量及完整包验证通过；真实宿主自动接管仍 BLOCKED，模型效果/token收益 UNKNOWN。仅本地候选，不是安装或发布。

## 实际改动

冻结范围见 [修复合同](upgrade-review-fix-contract.md)，原发现见 [审核报告](2026-09-15-upgrade-review.md)。工作区为 `.worktrees/short-session-remaining` / `codex/short-session-remaining`，HEAD 仍 `0f5898e19b4951c661edce1f7db80f95cc1b2ecc`；本次源码仍未提交，不用 HEAD 冒充包来源。

| 项目 | 最小实现 | 实际验证 |
| --- | --- | --- |
| R1 | `host_records.py` 两处资格判断增加已获原主控授权的 cancelled；身份、代次与锁内复核不变 | start/resume 各预留一次，重复不启动；prepared、目标会话冒充、未登记身份、错代次均拒绝；主控另跑原公开链的修复断言 |
| R2 | CLI 复用现有严格 JSON 解析器，拒绝重复键，不再 last-key-wins | start/resume × 同值/异值重复 thread_id 共4子例；真实台账保存原始输出；重复请求与新替代尝试均不再启动 |
| R3 | 受限解析边界处理 RecursionError，返回未知线程但继续观察归档 | start/resume × 10000层、20087字节 JSON；返回 execution_unknown，退出0的原始输出仍保存，不能以退出码解锁替代执行 |
| R4 | canonical 一次完成 UTF-8 编码并返回 bytes；非法编码转已有 unknown，两处指纹直接消费 bytes | 两条路径、session/sample/额外字段、孤立高/低代理字符均拒绝；真实 CLI 退出2/结构化unknown/无traceback；正常中文/emoji及旧previous兼容 |

产品修改仅三个维护文件，加上同步生成副本；没有新状态机、公共字段、依赖、常驻服务或提示词。Strict/Lite SKILL 正文在这轮未变化。测试代码增加11个方法，保留旧断言及旧审核反例；复现脚本退出0的含义仍是“旧缺陷复现”，不能拿它当修复验收命令。

执行分工：Terra-high 修 R1，主控修 R2–R4并集成；主控独立复核 R1，R1执行者只读交叉审核主控实现的 R2–R4，非自己验自己。受线程上限影响未启动额外独立审核任务，不声称新增全面安全审计。

## 红绿与实测

原始命令、输出及退出码：[runs.json](upgrade-review-fix-runs.json)。计数为测试方法；重叠套件不相加成独立场景数。

| 验证 | 结果 | 耗时 |
| --- | --- | --- |
| R2 红→绿 | 1方法/4子例由错误 exited 转正确 unknown | 绿0.240秒 |
| R3 红→绿 | 1方法/2子例由 RecursionError 转有记录的 unknown；含R2复跑2/2 | 绿0.364秒 |
| R4 红→绿 | 2方法/18子例原异常；usage整个模块26/26通过 | 绿1.325秒 |
| R1 执行者整模块 | 24/24 | 1.403秒 |
| R1 新测试在保留的旧完整实现 | start/resume 2/2按原缺陷失败，原因 HANDOFF_CONTROLLER_AUTHORIZATION_REQUIRED | 0.042秒 |
| 主控原R1公开链修复探针 | pass；一次新事件，重复请求日志不变 | 仅记录结果 |
| R2–R4 / Lite相关回归 | 57/57 | 16.881秒 |
| R2–R4交叉复核回归 | 43/43，由另一Agent执行 | 12.614秒 |
| 全量回归，显式完整旧包，无skip | **561/561** | **62.134秒** |
| 源码树外 Strict 完整包 | **73/73** | **14.150秒** |
| 源码树外 Lite 完整包 | **46/46** | **5.717秒** |
| 旧/新usage公开结果对照 | 27/27相同，含旧previous、ASCII/中文/emoji | 未单独计时 |
| 两包check-source/build/verify/full doctor | pass；无任务绑定请求，因此binding为not_run | 未单独计时 |

全量与包外执行开启 ResourceWarning，输出未出现资源警告。不是对真实业务、模型稳定性或生产可靠性的验证。

记录保真：R1执行者红日志返回 RESERVATION_COMMIT_UNKNOWN，未充分记录其当时夹具/中间版本，不能把该日志独自当作原始缺陷的精确红证据。主控另将最终测试放到保留的旧0.8.0完整实现中，明确打印旧模块加载路径，实际得到原审核对应的2个失败；新实现及独立公开探针都通过。未覆盖或删除该不完整日志。

首次 Strict doctor 命令遗漏包内 `PYTHONPATH`，被正确判为 RUNTIME_UNVERIFIED；补上 `<Strict包>/src` 并从 `/private/tmp` 运行后完整校验及smoke通过。保留首次unknown，不将其归因于产品修复失败或隐藏成全绿。

## 完整候选身份

两包均构建到新目录 `/private/tmp/mltc-review-fix.x5qKWs/`，旧候选未覆盖。保持尚未发布的版本号，使用不同来源标记及完整hash区分。

| 包 | Strict | Lite |
| --- | --- | --- |
| 版本 / 文件数 | 0.8.0 / 67 | 1.4.0 / 17 |
| source_revision | candidate:dirty-worktree-0.8.0-review-fix | candidate:dirty-worktree-1.4.0-review-fix |
| manifest SHA-256 | cbd3499c536c1f6800b45b26c73fb19a7848e1ae7a11fa897fbeb5d22d3550d3 | f953804bb28b01856060088a0b9822d7da88fe8a8331583e35d9564bb32bcb3c |
| source_tree SHA-256 | 2194a3cde30d223bb17a535ff63fdcbd72b515aa9686f6a6c818f3da2b7b27db | 2538a1d5b8692a3fe859723b8ad88584b71db90fa8a84405befbaded68b4d58e |

持久副本：[Strict manifest](upgrade-review-fix-strict-manifest.json)、[Lite manifest](upgrade-review-fix-lite-manifest.json)。临时包可能被系统清理；需按来源与文件树重新构建核验，不能仅信版本字符串。旧 v0.37 候选留作历史，不是本次修复包。

维护源最终 SHA-256：

- `host_records.py`：`d22aee2e50471525ac031c93518819fabcb6b7af4996302795b634bb9afc83ae`。
- `host_codex_cli.py`：`ceb43c8b672de5a85ea004b3b994cdf0f76de5be21509ed30b5844083edb59aa`。
- `scripts/context_usage.py`：`4c0b9eb4d0d77266dd96700655c961c0658faf06dad80ecd6f7f20fefb9afa45`。

## 复跑与边界

在候选工作区运行：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_handoff_host_records test_handoff_codex_cli test_context_usage -q
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 docs/validation/upgrade_review_cancel_fix_probe.py "$PWD"
MLTC_LEGACY_PACKAGE=/private/tmp/mltc-review-baseline.GYDdVc/context-strict PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -W always::ResourceWarning -m unittest discover -s tests -q
```

包外命令和verify/doctor精确参数在 runs.json；旧0.7.0完整基线本轮verify通过，manifest `3d3e4f44b454adaa358d69c4e75eec4bbaa2ecedcb5d84abfdc6b34e33e50cc7`。基线不存在时不能省略环境变量并把skip算通过。

本轮没有安装、提交、合并、推送、部署或生产任务写入。E4真实原生宿主接管仍BLOCKED，E7未触发，token收益与修复的增量内存/性能收益未测。完成的是已授权的四项本地修复，不是所有真实宿主能力或收益已验证。
