# E1-02 执行合同 v1：准备／取消与写入约束

状态：验收和所有权冻结；接口检查点待主控裁决，裁决前只读设计，不写产品实现。GitHub #17，前置 #16 已通过本地源码验收（完整包同步仍由 E2 负责）。执行者使用新的 Terra-high，无长历史。

## 授权与依据

仅 E1：源码开发、隔离测试、主控审核。不要全局安装、改生成包、改 E0 预期、提交／合并／推送／部署、执行业务或付费模型调用。宿主假数据明确 synthetic，不制造真实身份或授权证明。
HEAD `0f5898e19b4951c661edce1f7db80f95cc1b2ecc`；工作树含已验收首单源码及用户文件，不能覆盖或清理。
主计划 `docs/superpowers/plans/short-session-handoff.md` 的 E1；冻结 E0 输入：`tests/fixtures/handoff/interface.schema.json`、`protocol.md`、`ready-state.json`、相关 cases；manifest SHA256 `435e407c064b32a7d5012e0161c9b2e7bddc38c8d70ce42e12659102e7f52a7b`。
首单源码验收与确切 hash 见 `docs/validation/e1-01-controller-review.md`。首单测试 28/28、主控探针 10/10、全回归 423/424，唯一分发比较失败不可删除或宣称通过。

## 文件所有权

执行者可改：`src/managing_long_task_context/handoff.py`；核心 `__init__.py` 中必要写前钩子、薄入口及事件投影；新 `tests/test_handoff_writes.py`、`tests/test_handoff_concurrency.py`；自己的 `docs/validation/e1-02-executor-report.md` 和 `e1-02-executor-runs.json`。
既有首单套件、主控 probes、计划、CONTEXT、E0 和分发目录归主控或其他阶段。若行为确需演进旧测试，先报告具体原断言与新协议依据，由主控决定，不自行删改。
不要通用状态框架、大规模重构或新索引。核心保留锁与提交，交接专属编排在 handoff 模块；禁止嵌套非重入锁、重复锁表和同文件并发执行者。

## 实现前接口检查点

先给主控一个简短但具体的提案：两个写入口的 runtime-only 可信依赖；直接写 API 的调用者身份／授权参数如何验证；初始控制事实从何获得且不由 record 自封；prepare 与派发怎样原子排序；取消怎样确认尚未激活；哪些 I/O 在锁内，哪些宿主检查在锁外；三事件及既有投影如何保留幂等语义。等待主控接口裁决后写行为红。
公开 JSON 参数沿用 schema 的 `prepare_handoff`、`cancel_handoff`。不从 JSON/actor 字符串创造 callable 或许可。无需新增产品 API 来启动真实子进程，派发授权的接受及登记应为受控写动作；该许可不是实际子进程启动成功。宿主真实启动/重启栅栏在后续适配阶段。
准备／取消不增加代次；激活与完整崩溃恢复属 #18，不能在本单声称已有。保留已刷盘事件的权威性；异常无法确定提交则 unknown，不盲重试。

## 冻结验收（实现前确定；逐条测试及红绿证据）

1. 完整、当前、真实临时文件内容相关且可信假宿主确认当前主控和原范围许可时 prepare 成功，事件和完整记录绑定；只准备不激活，代次不变。无核验器、同名假身份、错任务／工作区／包／合同／代次或过期许可不得写入有效交接。
2. 缺依据、损坏日志、超限、文件写入失败或 prepare 过程中依据变化不得发布有效 prepared 引用；旧状态不得写成完成或增加控制代次。不能先写合同／事件后才检查权限。
3. prepare 与受控新派发写竞争：短锁内确定顺序。派发先成功则登记可查；prepare 先成功则派发明确拒绝。以线程同步屏障或独立进程测试，不用 sleep 猜顺序；真实子进程启动不在本单声称范围内。
4. prepared 期间有效在途子任务仍能提交许可范围内的进展／结果；没有许可、冒充 child 或越过原范围修改合同／新派任务不能通过。不是把所有 writer 都拒绝来获得绿灯。验证普通合法子任务正例和伪造／越权负例。
5. 对已启用协议任务，直接调用 `publish_contract`、`record`、`update_item`、`checkpoint`、`mark_truth_sources_dirty`、`observe_truth_source`、`externalize_item`、`restore_externalization_controls` 必须在副作用前通过写入许可及状态约束。缺身份、旧代次、失效运行权限不能绕过；至少验证每个入口未授权时目录原有文件内容不变，并验证正常授权的典型事实写入。没有 handoff 的旧任务保持原签名兼容及原行为。
6. 只有可核查尚未激活且原主控原范围许可仍有效才能 cancel，代次不变、追加一次取消事实、恢复原范围调度而非赋予新权限；宿主 timeout／未知、激活存在、撤权、错代次不得恢复。已取消状态的 validate 不可误当 prepared pass。
7. 同任务 request_id 绑定操作和规范内容：重复相同 prepare/cancel 不新增事件或重复副作用；同 ID 不同内容、跨操作、不同 handoff 冲突；不得覆盖已发布记录。并发重复只能出现一条成功事实。不同 ID 不能绕过已有未决交接。
8. 宿主耗时核验不持独占写锁；核验后短锁内重新核对承重输入、权限观察有效期、控制代次及请求事实。不把外部上次 pass 当提交凭证。不扩大 E0 资源预算。
9. 保留 #16 只读安全预期、旧 completion/独立验收/Truth Sources 机制；运行新测试、首单独立探针和全回归，单独标明 E2 的分发失败。真实宿主、自然使用、token 收益均 UNKNOWN；确定性重复不是模型稳定性证据。

## 验证与交付

使用 TDD：一项行为红→最小绿；导入/语法失败不算行为红。通过公开 seam 和真实临时文件验证；不 mock 自有私有方法返回 pass。允许注入可信宿主和真实 I/O 故障边界。测试是 synthetic，不读业务数据。

针对性：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_handoff_writes test_handoff_concurrency test_handoff_protocol -v`
独立探针：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 docs/validation/e1_01_controller_probes.py -q`
全回归：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /opt/homebrew/bin/python3.12 -m unittest discover -s tests -q`；超过工具初始等待必须继续 poll 获取终态，不把 30 秒让出当超时。
E0：沿用首单合同中的固定 manifest 校验命令；`git diff --check`。

报告每个 AC 的实际测试、命令/退出码/数量/耗时、红绿原始摘录、失败/未运行、源码 hash 和意外写入检查。不得把模块导入、工具退出 0 或代理自报当验收。失败继续原单修复，未通过不派 #18。没有自然等待要求；本单只有本地机制验收，提交后停止写入并通知主控独立复验。

## 接口裁决附录（v1.1，开写前批准）

验收与所有权不变。只采用两个可信依赖：`handoff_verifier.verify(request)` 沿用首单内容检查；`write_authorizer.authorize(request)` 核实宿主调用者与具体动作原范围许可。八个既有写入口和两个新写入口可加 keyword-only `runtime_identity=None, write_authorizer=None`；新交接写入口另有 `handoff_verifier=None`。runtime_identity 只是待核实线索，不是授权对象；禁止根据 JSON 自动构造依赖。

authorizer 请求包含 operation、task_id、规范化 base_dir/workspace_root、合同版本/digest、包 manifest digest、controller_generation、handoff_id、arguments_sha256、runtime_identity；按当前控制事实或首次准备候选构造 source/target/authorization 引用。arguments_sha256 覆盖操作名及规范化非运行时实参（包括 base_dir），禁止同身份跨动作／双存储重放。
请求还必须提供对应的规范化 arguments 内容，供可信 policy 实际判断动作及工作项是否在原范围；不能只给 digest 让 policy 无法核查内容。该字段仅 runtime 内部请求，不扩展 E0 JSON 入口。
严格结果必须含 status、operation、purpose、上述任务/路径/合同/包/代次/交接/实参绑定、subject_id、role、scope_digest、work_item_id、source_session_ref、target_session_ref、authorization_ref、target_activation_status、observed_at/expires_at。检查字段类型、必需项、绑定和时间；缺失/例外/unknown 不放行。role 仅 controller/child；非空 subject 与 scope 由可信 policy 实查，不把 hash 当权限证明。
purpose 由 authorizer 根据实际动作和原范围给出，程序校验 operation→purpose 白名单：record 可派发／进展／结果／普通事实；update/checkpoint 不能变派发。prepare/cancel/dispatch/contract_publish 为 controller；prepared 期间只允许 child+progress/result，必须绑定具体 work_item_id 和本次实参。无许可不能靠 actor、metadata、不同署名变成合法 child。派发只作为既有 record 的原子登记，不是实际启动许可或启动成功证明。

首次 prepare 没有控制历史，不能从不存在的事件推导代次。authorizer 必须独立核实当前 source/controller generation 与候选 target 尚未激活及原范围授权，然后与候选严格对齐。没有可信宿主则 unknown；真实旧进程退出/禁止重启尚待 E2+，本单不声称迁移安全已完成。
启用状态是历史上已有合法 prepared，cancel 不使任务退回 legacy。若控制资料存在但权威日志缺失/损坏，不得走无协议快路。cancel 只恢复原主控原范围调度，不恢复无身份写权限。

所有宿主回调在锁外；禁止锁内二次 authorize。当前调用获取新的有效观察后，在短锁内复核权威状态、当前代次、引用指纹、具体实参、许可时效和请求绑定。无法核实仍适用即 unknown。此机制不声称提供尚未实现的真实宿主瞬时撤权保证，也不复用前一次 validate/不同请求的 pass。
幂等身份只能由权威固定三事件和封印资料重建，不能只存在 snapshot，不能扩展 E0 事件字段。prepare 绑定完整 record 的 canonical hash；cancel 绑定固定请求+该记录引用，跨动作/内容/交接冲突须可重建。已取消状态保持不激活，#18 再实现完整激活与结果查询。

首单两条 prepared 后裸 writer 正例，主控将在集成时仅升级为真实读取合成许可的合法 child（保持进展可写与宿主不占写锁的断言）；执行者不得自行更改首单测试。完整独立探针保持原预期。
