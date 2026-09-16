# E3 执行合同 v1：Codex CLI 本地适配

状态：验收与边界冻结；CLI transport 与记录层公开接口/最小接线均已批准。
依据：主计划 v0.31，用户在 E2 收口后“继续”；E2 #20 本地通过。Terra-high 执行，主控集成复验。E3 本地连续执行，不在普通步骤等待用户“继续”。

## 范围与基线

- 工作区 `/Users/zhaowei/Desktop/David/project.nosync/managing-long-task-context`，main HEAD `0f5898e19b4951c661edce1f7db80f95cc1b2ecc`，已有 E1/E2 及用户未提交文件全部保留。
- core SHA256 `7460e51f2e70594f3eb1be78e12fca0ffb803193d5647a9ac950ebda4b6447f6`；handoff `c8a459278158a18ff4e563a1cd69663e2c598b54f6236942d67184a5bc22ed9f`。E2 完整基线包 0.8.0/51 文件，manifest `51331cb7ea3edb2c120d1f1a5efa76dff32d79edd7644a1f0f98312ab0817165`，临时位置 `/private/tmp/mltc-e2-controller.rGw7ow/context-strict`；本轮再次 verify 通过。
- E0 manifest `435e407c064b32a7d5012e0161c9b2e7bddc38c8d70ce42e12659102e7f52a7b`，不改预期或原始样本。C01-C06：E0-076–111；扩展 C04-a/C06-a：E0-139/140。本地实现采用这些语义，不把输入规格检查当产品测试。
- 本机 Codex CLI 0.154.0 仅 help/version 复核。新建与 resume 分别构造参数；resume 不使用 `-s`，不用 --last/线程名称替代精确 UUID。
- 本地测试只能启动标准库假 CLI 子进程、隔离临时文件；不得调用真实 Codex 任务、SSH、业务命令、模型 API，不全局安装、不提交/合并/推送/部署、不启动 E4+。

## 所有权

执行者：新 `src/managing_long_task_context/host_codex_cli.py`、`tests/test_handoff_codex_cli.py`、必要自包含 `tests/handoff_codex_fixture.py`、按需 `references/host-codex-cli.md`、`docs/validation/e3-executor-report.md`、`e3-executor-runs.json`。先批准公开接口，再逐片红绿。

主控：本合同、计划/CONTEXT、工单、独立探针及复验报告、完整包集成。已有 core/handoff/生成副本/清单/CI/旧测试执行者暂只读：确需复用既有锁及事件提交的窄接线，先给具体位置和原因，经主控补录所有权后可动；禁止新建独立权威数据库、常驻调度器、通用命令执行框架或重新实现证据解析器。

## 冻结验收

1. **有约束的启动。** 当前任务/合同版本及摘要/基线/实际工作区/预期代次/授权/attempt ID 均绑定；启动前持久化预留。固定程序路径与执行模型/推理/沙箱/审批均由可信宿主配置提供，模型正文不能覆盖。缺许可、旧代次、跨任务关联或路径漂移均不启动。shell=False、argv 列表、stdin=DEVNULL、实际 cwd；prompt 包含引号/换行/元字符/伪权限不得产生第二命令或新增选项。合法获准符号链接按规范路径使用，不一刀切阻塞。
2. **单写者与不确定性。** 每次 exec/resume 新 attempt；同线程运行时不 resume，未知状态/查询不全/启动已预留但没拿到 ID/超时/结果持久化失败不重发、不另开线程绕过。程序退出不等于业务通过。必须以实际假进程计数与持久化事件证实重复请求不重复启动，不只断言返回 unknown。受控入口外的写者不能凭本地锁声称已封禁；可信宿主无法排他时相应能力保持 unsupported。
3. **任务连续性 C01/C04/C05。** 新适配实例从持久化依据发现原任务与运行/结束/未知状态；分别只读跟踪、读取结果验收、调查且不重派。不能查询/联系原执行者/父退出影响未知时不声称接管、不归档或杀子任务。原任务返修使用精确旧线程（新 attempt），新逻辑任务新线程，安全换实例保持任务合同、未提交成果、失败尝试与未知动作；未到安全点或动作未知不得为省 token 换实例。查询自身不发业务动作。
4. **结果关联与发现 C03-a/d。** 已授权子执行者先把版本化结果及关联落盘，再通知；新主控不依赖旧聊天或通知发现。完整读取实际内容并核查非空/任务/合同/attempt/工作区/版本，不接受仅 pass/合法 JSON/hash 作为业务完成。缺身份/空内容/不可读返回 unknown，完成写入 0。相同身份相同内容重复通知仅一条处理提交；保留独立原始结果。
5. **冲突、晚到与失效 C03-b/c/h。** 同身份异内容双方保留并报冲突；旧合同/旧 attempt 晚到不得覆盖当前结果，但缺陷信号必须保留、相关依赖重新验。已处理结论遇到证据/授权/合同变化不得永久缓存 pass；必要复核不受去重抑制。至少分别测试三类失效及同身份异内容。
6. **处理提交与业务动作分离 C03-e/f/g。** 用既有权威事件流，核验锁外、提交时检查当前代次及依据；主控核验中切换导致旧代次迟到提交拒绝。提交前中断为未提交、提交后丢回执可从事件确认、无法判断则 unknown；重复请求不重复结论，不重跑业务。后续动作 execution_unknown 保持未知，已处理不等于完成或可重试。关键进程中断用实际子进程/屏障+有限超时验证，不仅抛异常；不声称模拟断电。
7. **能力诚实 C06。** resume/fork 含历史，不能证明干净；共享父 ID 不能证明独立，hook 未验证/超时/可绕行不能证明受控。占用不可得返回 manual-or-stage，不捏造 token；不同实例分别判断，不合并占用。跨文件系统不可读路径不用，可读完整版本包先沿用既有 verify/identity 核查。无可信适配说明的原生宿主、自动切换、归档、父退出行为保持 unknown/unsupported；局部通过不得宣称整套真实接管可用。
8. **经济与有界。** 标准库，无常驻服务，无额外模型调用；一次操作不自动循环业务重试，异常至多一次只读确认。沿用 E1 2000事件/8MiB/64KiB事件限额，不为跑通加大；新增 prompt 最多8000字符、标识同E0 ASCII 1–96字符（线程UUID单独精确校验），读单结果最多1MiB、非空UTF-8；日志最多8MiB、单JSONL行最多64KiB。假CLI等待默认10秒、绝对上限60秒，超时仅终止本次受控假进程并保留execution_unknown，不重复启动。正式长任务的监测/超时策略由宿主负责，不把本地等待限额当部署超时批准。检查/输出不泄露完整prompt、授权秘密或无关日志；费用、RSS、token没有实测写UNKNOWN。
9. **回归与包身份。** 旧 E1/E2 测试不降标准、无新增失败；模块加分发时完整包/导入身份一起接入，不把未分发代码描述为安装可用，不给未验宿主自动声明支持。保留旧0.8.0完整包作基线，候选必须标 dirty-worktree；Lite与原7项用户文件不变。全部构建隔离，不安装。
10. **证据。** 按 AC/E0 编号列 expected/actual/命令/退出码/耗时/分母/skips；分别报告本地机制、真实宿主 NOT_RUN、真实模型 NOT_RUN、自然使用 NOT_RUN。先冻用例预期后逐片 red→green；缺模块/导入错误不是行为红，发现架构缺口向主控申请窄接线，不改样本洗绿。报告需给完整 diff 和不可声称的能力。

## 复跑入口与交付门

针对性：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_handoff_codex_cli -v`。

必要回归：相同环境运行 `test_handoff_protocol test_handoff_activation test_handoff_writes test_handoff_concurrency test_handoff_process_recovery test_handoff_gate_combinations test_handoff_distribution test_distribution test_runtime_identity`。

完整回归：`MLTC_LEGACY_PACKAGE=/private/tmp/mltc-review-baseline.GYDdVc/context-strict PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /opt/homebrew/bin/python3.12 -m unittest discover -s tests -q`；旧包类比测试不得静默跳过。

主控独立验收看真实 argv/cwd/stdin、启动次数、现有 events 里的尝试/处理记录、各返回值、实际内容变化及进程退出。主控测试计划与执行者实现分别维护。本地门通过只允许标 E3-local accepted；真实宿主整条路径另行验收后才能开放，不能用 synthetic callback 签发的身份冒充宿主证明。

## 接口裁决 2026-09-15

#21 已认领，Blocked by #20（已关闭）。为了不在CLI适配器另造事实库，E3按同一合同分成两个实现模块；不扩大功能需求：

- `/root/e3_codex_cli`：只拥有上列 transport 文件。`CodexCliHost(config, ledger, observe_host)` 对外 `start_child(request,prompt)`、`resume_child(request,prompt)`、`observe_attempt(attempt_id)`、`verify_host()`；结果处理走记录层，五个既有handoff入口不重写。
- `/root/e3_host_records`：先审新 `host_records.py`、`test_handoff_host_records.py`、`handoff_host_records_fixture.py` 及原core最小事件接线；未批准前不写。通过 `HostTaskLedger.reserve(request,operation)`、`record_observation(attempt_id,observation)`、`observe(attempt_id)` 与transport对接；结果发布/处理另行明确字段后冻结。记录层有独立报告 e3-records-report/runs，不修改transport文件。
- `request` 绑定 `task_id,attempt_id,contract_version,contract_digest,baseline,workspace_root,controller_generation,thread_id`，执行时增加 argv/config/prompt 摘要绑定。同attempt异意图不覆盖。`reserve` 仅 `status=pass` 且字面 `launch_allowed=true` 可启动，重复预留回查一律false。
- `config` 来自可信宿主代码：固定绝对程序（假CLI可sys.executable+固定fixture脚本）、规范工作区、显式model/reasoning_effort/sandbox_mode/approval_policy、timeout_seconds。不得从模型request覆盖；launch前再次核对程序和workspace实际目标。
- `observe_host` 是可信回调，回执绑定任务、attempt、thread、workspace；必须包含已验证身份、排他状态、观测/失效时间、证据refs。缺失不启动。测试固定注册身份并读实际夹具，不能回显请求即pass。回执不证明全OS排他，只在已验证宿主控制范围内生效。
- CLI运行以实际参数数组、DEVNULL及子进程输出验证；仅作用于本次受控假进程。入口定义来自已审核E3及本接口裁决，不额外向用户要求重复批准。

记录层补充裁决（实施前）：

- 批准 `HostTaskLedger(base_dir,host_observer,runtime_identity,write_authorizer)`，结果入口 `publish_result(result)`、`reconcile_result(attempt_id,result_version,verifier)`、`record_action_outcome(action_id,attempt_id,status)`。最后一个只记录not_started/executed/execution_unknown，不执行动作。
- 5种事件：host-attempt-reserved/host-attempt-observed/host-result-published/host-result-processed/host-business-action-observed。事件schema和投影由host_records维护；core只加受控类型、校验/投影委托、复用原task锁与原子publisher（不复制写入实现）。只读严格重放与旧重建都必须校验，不接受metadata伪装。
- 记录执行者额外获得core上述窄点、handoff.py仅 `_OPERATION_PURPOSES` 的新增映射所有权。原映射、5个handoff入口、三态/旧安全规则均不改。reserve及result_process只许当前controller；child只可按原授权观察/发布自己的结果。prepared期间不开放主控调度。根import身份登记及生成同步仍归主控。
- 尚无handoff事件的gen0任务可以首次启动，但必须由程序核对确无control，可信host独立注册身份/授权观察匹配当前任务/合同/base/workspace/baseline/代次，不能将模型参数当批准；已有control则必须使用原direct-write fence并在原锁内重核。
- 不改变AC的安全预期，仅明确实现落点。core长度不作为迫使复制框架的理由：新增实质逻辑留新模块，核心仅接线；修改后按E1/E2全量回归复审。

记录/transport 对齐裁决（保留上述历史）：

- observation 使用21字段闭合结构：`task_id,attempt_id,reservation_id,operation,argv_sha256,cwd,thread_id,exit_status,timeout,observed_at,stdout,stdout_digest,stdout_bytes,stdout_utf8,host_identity_ref,host_exclusivity_status,host_observed_at,host_observation_ref,stderr_digest,stderr_bytes,output_over_limit`。exit_status/timeout均出现，未用者null；未知thread为null。start可观察新UUID，resume只能精确旧UUID或unknown。关联不符拒绝，不删校验以适配字段。
- stdout原文仅入0600 archive，事件/返回用摘要及引用。输出超限、编码错误、线程未知、超时不得仅凭exit=0解锁下一attempt。未保存的stderr原件不得声称已保存。
- 原 `/root/e3_host_records` 停写，由 `/root/e3_records_audit` 接替记录层实施及原窄接线；其修复不再算独立验收。主控独立复跑，transport仍由原owner继续。开发Agent成本未独立计量；并非零模型调用。
- P12实际进程复验先冻结：仅对隔离记录层的events原子replace前/后设置屏障，父测试终止该测试子进程；前者0处理提交，后者1处理提交，新进程重读且重复处理最终仍1。该故障注入不是模拟断电或真实Codex故障。
- 本地E3 child授权的 `work_item_id` 精确等于本次 `attempt_id`；现有宿主授权回执及锁内复核继续使用，不用格式合法代替归属核查。发布/观察/动作记录不能越过此绑定，处理仍仅controller。当前任务最新attempt由原预留事件顺序确定；旧attempt/旧合同晚到只保留历史和安全信号，不作为当前处理通过。处理历史在恢复摘要中一律标需复核，不让只读导航重复充当放行门。
