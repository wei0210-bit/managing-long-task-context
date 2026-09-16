# E1-01 第二执行会话接续

任务仍为 GitHub #16，原执行合同 v1/hash 不变。用户已授权范围内连续推进；修复原 AC 不需再次询问用户。
原 Agent `/root/e1_01_readonly` 报告上下文限制，已要求停止代码写入并保存报告。新 Agent 必须由主控确认旧 Agent 结束后才开始写，不能只凭此文件推断退出。

## 必读输入（不加载整段聊天）

1. `docs/validation/e1-01-execution-contract.md` 全文，SHA256 `39b770f90ae67a16b7fbeddc2e98269217c284e405aa010cf0800d921407fc45`。
2. `docs/validation/e1-01-executor-report.md`，只作为导航，实际读代码／复跑验证。
3. `docs/validation/e1-01-controller-review.md` 与主控独立脚本 `docs/validation/e1_01_controller_probes.py`。
4. E0 protocol/schema/budget，原 manifest `435e407c064b32a7d5012e0161c9b2e7bddc38c8d70ce42e12659102e7f52a7b` 不改。

## 当前事实与风险

- 只读两入口已实现；一次可信 runtime verifier + 最终 capture/引用指纹复核，假的宿主/包仅限隔离机制。
- 主控最近实际8/8负例通过；原执行者报告 targeted17项。不以测试总数替代AC逐项覆盖。
- 首版4项错误放行已修；后续三态/畸形引用/重复字段/代次约束也修。请复跑主控脚本，不能只信报告。
- **AC5/6仍未通过：** 8MiB预算用item-recorded payload.padding填充、2000events用payload={}，不是真正完整合法事件。+1用裸x同时使JSON截断，是混合故障，不能做资源单变量证据。这些测试需先正确物化完整合法item模板，再断言精确字节和状态；旧测试曾绿不代表边界已验收。
- 严格路径仍可能忽略缺item/id/结构字段的普通事件。只在新handoff路径拒绝；复用已有类型/必需字段检查，不改legacy默认语义，不另造完整框架。历史过期warning不应一律阻断移交，当前业务阻塞与接管依据须区分。
- **主控新复现 CR09：** prepared之后追加另一交接HO-OTHER的activated事件、代次8，查询原HO-001仍pass/gen7。E1-01不能忽略未实现的控制状态；返回unknown（后续#18实现完整转换），不能自填旧主控事实。
- schema依赖、items/deadline在重建中检查而非事后、manifest有限读取、文件hash在共享锁外已经开始落实，需核实和测试。
- 分发副本同步测试失败是E2未完成依赖，禁止偷偷改生成副本/删断言。其余旧回归必须查实际结果。#17保持阻塞；本单不实现prepare/activate/cancel写入。

## 剩余验收（沿用原AC，不扩大范围）

1. 合法精确日志 8MiB-1/等于/+1，三者语法完整、单条和数量限制满足，正例必须真的回放进items，超限具体资源原因；64KiB单条边界、2000events及最大可达items，清楚解释被其他限制支配的不可达边界。
2. 系统时钟注入验证读取和逐事件重建各自超时停止（不mock私有方法）；错误日志/payload/type/digest不静默忽略；CR09和主控8项均不放行。
3. 原AC2/3/4/8剩余：缺失/不可读/过期/冲突/版本、伪授权、源/产物内容不相关、有明确业务阻塞仍可移交、检查后变化、host异常。每项有公共seam证据，不只复述规则。
4. 明确不持独占锁运行昂贵host验证/外部引用读取，用隔离进程或线程握手证明子进展仍可写；不要sleep猜时序，不执行业务动作。
5. 在不改变公开签名前提下，让新模块承接专属验证编排，core仅必要I/O/lock/replay hook；不做全核心重构。不要因结构整理再扩大接口。
6. 最终9项AC→测试/结果/未验证映射；保存实际原始运行命令/退出码/失败/跳过与红绿输出；错误放行和错误阻塞用实际分母，token未知。

## 所有权与验证

原合同三个代码/测试文件归新执行者。旧报告不覆盖；新报告 `docs/validation/e1-01-repair2-report.md`，运行证据 `docs/validation/e1-01-repair2-runs.json`。
主控脚本和计划/CONTEXT归主控，只读。所有原用户未跟踪文件不改。
使用 `/opt/homebrew/bin/python3.12`，`PYTHONDONTWRITEBYTECODE=1`；具体命令见原合同。所有fixture仅临时目录。
进展用 send_message，不发final后声称仍在执行。全部原单工作完成或具体实质阻塞才结束；不得自行派#17或关工单。
