# E1-01 主控复验记录

状态：E1-01 本地源码机制验收通过（2026-09-15T08:37Z）；允许进入 #17。完整分发／发布仍阻塞于 E2，非全仓全绿。以下前几轮结论保留为历史。
对照：执行合同 v1 SHA256 `39b770f90ae67a16b7fbeddc2e98269217c284e405aa010cf0800d921407fc45`。

## 第一轮独立反例（2026-09-15）

主控使用执行者的隔离 fixture 构造器、通过公开 `validate_handoff` 独立变更输入。
预期来自已批准的合同和 E0 类型／时效／权威日志约束，不来自实现返回值。

| 编号 | 注入 | 冻结预期 | 实际结果 | 状态 |
|---|---|---|---|---|
| CR01 | 当前合同 int 1；record 改 float 1.0，重封 record/事件引用并绑定假宿主 | 版本类型不同，不得 pass | pass | 已退回执行者修复 |
| CR02 | 最后一次宿主 callback 得到结果后修改真实临时证据，返回旧结果 | 旧检查不能放行已变化证据 | pass | 已退回；不得无限追加 callback 掩盖时序 |
| CR03 | envelope event_type=handoff_activated，payload.type=handoff_prepared | 类型不一致不得放行 | pass | 已退回 |
| CR04 | 首条 contract-published digest 改零值，sealed contract 保持原值 | 未与已提交合同对应不得放行 | pass | 已退回 |

本轮针对上述 4 个构造负例错误放行为 4/4；不是总体效果估计或自然项目故障率。
对应 shell 工具实际输出均为 `{"actual":"pass","reasons":[]}`，命令退出 0（代表探针运行成功，不代表产品验证成功）。

## 追加验收关注

第二轮独立探针发现：prepared 预期代次=900/实际代次=7 仍 pass；日志同键异值（后一个7覆盖900）仍 pass；宿主授权 unknown 被误记 fail；malformed ref_id 列表引发未捕获 TypeError。均退回原单修复。首轮4探针已有一次主控4/4通过，但不覆盖这些新发现或未补齐的原合同。
复跑脚本：[主控公开入口探针](e1_01_controller_probes.py)。当前共8项；CR02 改为在每次实际callback返回前改变证据，避免把“两次调用”作为实现约束，安全预期不变。

- 当前 7 项测试不足以覆盖原合同；继续补齐日志错误、资源边界、时效、撤权、包／工作区绑定以及内容对应关系。
- validate 返回 `not_attempted`；status 返回实际提交事实，不能混为一条别名路径。E0-178～180 明确前者语义。
- 缺失、过期、冲突和错绑定保留 unknown；不把所有非 pass 一律判 fail。已确认内容违例才 fail。
- 读取 record、manifest、contract 不能先无限 `read_bytes` 再检查限额；日志须验证 payload、已提交合同和重建结果，不仅 envelope。
- 宿主不可用／JSON 伪造／无语义检查不得 pass；假宿主和临时包不能证明真实身份或完整包一致性。
- 旧套件的 `test_distribution_matches_maintained_sources` 失败由核心源码已改而 Strict 副本未生成引起，E2 边界仍保留。不能删断言／同步越权／称全量通过；需在后续集成阶段解决。

## 执行连续性

旧执行者报告上下文限制，保存停止点后由主控 `list_agents` 确认 completed；新 `/root/e1_01_repair2` 使用 Terra-high、fork_turns=none 接续同一工单。未让两个执行者同时改核心。
主控脚本现10项：新增CR09（另一handoff激活未阻断，错误放行）及CR10（合法file URI编码空格被误阻）。首次10项运行8通过2失败；预算测试的非法padding/空payload及裸x边界不作为有效正反证据。详见修复交接，不能以旧17项计数结单。

用户已授权四单依次执行，补齐本合同未完成项不需再询问“继续”。普通进展使用 commentary；仅实质授权或安全范围变化才请求决策。未完成验收不关工单、不派后继；本记录不是生产授权。

## 最终主控复验与阶段判定

两名执行者均停止写入后，主控把 runtime 交接编排迁至 `handoff.py`，核心只保留薄代理与锁／读取钩子；没有扩展状态机或修改旧门禁。下列结果均在此次集成之后独立执行。

| 检查 | 实际结果 |
|---|---|
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_handoff_protocol -q` | 28 项，0.456 秒，退出 0 |
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 docs/validation/e1_01_controller_probes.py -q` | 10 项，0.042 秒，退出 0；9 个定向负例错误放行 0/9，合法编码 URI 正例错误阻塞 0/1 |
| `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /opt/homebrew/bin/python3.12 -m unittest discover -s tests -q` | 424 项，29.324 秒，退出 1；423 通过，唯一失败 `test_distribution_matches_maintained_sources` 的核心源码／Strict 副本比较 |
| E0 冻结校验（命令见执行合同，manifest 未变） | 输入通过，0.024 秒，退出 0；180 个产品场景仍 NOT_RUN，不用本单套件替代矩阵执行 |
| 新鲜 Python 进程独立运行合法日志 8 MiB 三点测试 | 1 项含三点，0.179 秒，Darwin `resource.getrusage(RUSAGE_SELF).ru_maxrss` = 68,042,752 bytes < 134,217,728 bytes；退出 0 |
| `git diff --check` | 退出 0 |

RSS 复跑：以 `PYTHONPATH=src:tests` 新开 Python，使用 unittest.TestSuite 只加入 `HandoffProtocolTests('test_complete_logs_observe_the_8mib_minus_one_equal_and_plus_one_boundaries')`，运行前后 `time.perf_counter()`，随后读取 `resource.getrusage(resource.RUSAGE_SELF).ru_maxrss`。Darwin 单位为 bytes，Linux 不可照抄单位。这是夹具进程峰值，不是程序硬限额；`/usr/bin/time -l` 曾因 sysctl 权限未能返回 RSS，该次不能算 RSS 证据。

冻结 AC1–8 逐项核对执行报告的公共 seam 测试、合法边界夹具和主控探针，满足本单只读范围。AC9 的旧运行机制回归未发现失败；分发一致性失败是合同预先明确由 E2 负责的未完成依赖，不是被删除、跳过或改成通过。源码阶段通过不授权使用未打包的新能力，更不代表完整包验证通过。

修正执行者报告的分母表述：CR10 是正例误阻，不属于负例错误放行；新增 CR09、bool 版本及 float 代次是三个负例。上表只计主控脚本实际独立运行的 9 负例／1 正例，不将不同集合拼成总体故障率。固定输入 20 次相同且无写入只证明程序确定性；真实模型稳定性、token、自然项目效果均 UNKNOWN。业务核验和真实宿主仍待后续阶段，未声称可生产启用。

验收时文件 SHA256：

- 核心：`aae5d57700ea763540c9fa649b4267810a7c09f928500c2b7e372c83a28c8930`
- handoff：`adeb91df6f75a742dc1f3af5fe0df6e442198e6bd8a0f07fe91072a02de3d2b4`
- 执行者套件：`25b6c9ca94b87c7651c3c5697daef48ddf3008e6ebd8f71c6451236cd19def25`
- 主控探针：`abdd11119063247bf3bf9dff5d2922d6cc733157475f17c3e7f21ba9bdc1fc81`

下一单可以修改同一源码，但不得追改本次历史指纹或以新结果覆盖旧缺陷。E2+、安装、提交、合并、推送、部署和真实付费调用仍未授权。
