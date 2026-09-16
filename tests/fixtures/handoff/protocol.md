# E0 接口冻结 v2（拟实现规格）

此文件及 schema 不表示已安装新能力。E1 必须实现后才可验证行为；当前内核事件白名单不改。

## 类型与接口

`interface.schema.json` 的 `$defs` 是五个拟实现入口的关键字参数格式。Python 对应：JSON object → `Mapping[str, Any]`，array → `Sequence`，string → `str`，integer → `int`（拒绝 bool），null → `None`；无隐式类型转换。`base_dir`、`workspace_root`、`package_root` 为绝对路径字符串，运行入口另需核实实际路径／工作区归属，词法合法不证明可访问。

合同版本保留旧合同的 number/string 原值及类型，不擅自改为纯整数，也不以数值相等代替版本／digest 一致。引用中的 `uri` 仅导航；宿主身份、许可、内容及验收对应关系必须由实际核验提供。E0 的 fixture URI 不发起外部读取。

`prepare_handoff` 除通用写参数外接收 `record`。目标会话引用必须指向宿主已创建但未获执行权的候选会话；创建候选不等于激活。真正身份与授权不接受 record 自报。另四个入口使用 `handoff_id` 读取已发布记录。

`event_cursor` 是普通事件的稳定 ID，不是控制权代次。请求 ID 在任务内绑定操作名及规范化内容；相同 ID 不同内容必须冲突。

## 持久化事件

只新增三个协议事件类型（`interface.schema.json#/$defs/event`）：

| type | 前置 | 主控代次 | 投影变化 |
|---|---|---|---|
| handoff_prepared | 当前主控、原范围授权有效、完整工件已发布 | 不变 | 冻结新派单；记下交接、请求和记录指纹 |
| handoff_activated | 核验有效，短锁内依赖及代次复核成功 | 恰好 +1 | 唯一新主控生效，旧主控失去调度权；子任务原许可不自动撤销 |
| handoff_cancelled | 可证明尚未激活，原主控授权仍有效 | 不变 | 取消交接，恢复原范围调度 |

校验／状态读取不新增事件。响应丢失只读核对；已刷盘的事件不能因 snapshot 写失败被当成未提交。`record_sha256` 绑定记录的 UTF-8 JSON（键排序、紧凑分隔、不转义非 ASCII 字符），不把 hash 当授权。事件外围沿用旧 `_new_event` 格式；schema 定义新增 payload。既有子任务进展／结果仍使用原事件与事实登记，不在 E0 另造消息队列或预定全部宿主事件。

## 依赖方向

内核持有锁、读取权威事件和提交；`handoff` 提供无 I/O 的校验／转换。运行入口延迟引用内核，禁止导入期互环；内核已持锁时不得再次进入公开加锁入口。宿主 adapter → 公开 handoff 入口 → 内核；纯函数不反向调用 adapter。导入／锁序的实际验证属于 E1，不以这张关系说明代替测试。

## 案例适配约定

每个变体从独立临时目录物化 `initial_state.fixture` 中的内联文件和假宿主，以 initial_state 的 phase／controller 覆盖共用模板，再执行 `setup_actions`，根据 `operation.request_fixture` 选择请求，在 `injection_point` 注入 `stimulus`。`activate_once` 执行一次正常激活；`activate_until_injection`／`process_result_until_injection` 只运行到指定故障点，再由 operation 查询／核对。空 setup 不偷偷先执行激活。宿主、占用和证据均是假数据，不能冒充真实回执。非五入口的 `entry_point` 是测试动作名，不是声称存在的产品 API。

`assertions` 是适配器可观测输出上的等值黄金断言；适配器必须返回实际观测，不能读取 expected 字段生成结果。`expected_generation_delta` 指整个场景相对初始代次的变化（包括先提交后丢回执），不是每次 status 调用的增量。null 表示不可断言或该维度不适用，不能当成 pass；适配器未实现一律 NOT_RUN，不能 skip 后计入成功。

`protocol_fixture` / `isolated_process_fault` / `host_adapter_then_live` / `existing_lite_public_cli` / `fixed_usage_fixture` / `budgeted_fresh_model` 是六种测试方法，不是当前可调用的产品测试。真实宿主和模型层另行验收；自然使用另采真实记录，不用这些合成记录替代。

资源预算只针对读／解析／重建。占用 70/100 是测阈值边界用的合成配置，不是发布默认值。只读观测重复 20 次不能发模型调用、brief、完整回放或重复写入。

## v2 收口修正与矩阵消费

- E0-030：只杀死已 fsync 的写进程，随后从可读权威日志查询，应确认提交及代次 +1。E0-044～049 单独承载读取／持久性未知，不因未知去重试业务。
- E0-148～171：8 组三开关 × 3 场景。显式把 truth_sources／rule_execution／independent_validation 应用到临时合同；valid 具有有效交接依据，invalid_basis 缺少承重依据，changed_after_check 在检查后改变依据。规则结果和独立验收回执另有有效合成输入；不得把业务 gate 的失败直接等同交接失败（H05 仍保留）。目标是验证组合接入，不宣称组合现已支持；实际不支持必须记失败／阻断对应能力开放，不能跳过计绿。每种机制自身的否定路径沿用 H02、H15、H16 及其现有专项测试，不做全部组合与全部故障的笛卡尔积。
- E0-172～177：migrate_task 是未来验收动作名，不是新增产品 API。必须使用指定 manifest 的真实旧包，按旧写入者运行／未知／检查后重启、新版直接 record 的失效身份、可信安全退出及重复请求分别观察。安全迁移只新增一次协议启用记录，不改变主控代次；启动真实宿主前另外证明退出和禁止旧写入者重启。数据中的 synthetic-exit-observation 不是真实证明。
- E0-017：packet 限额是该合成案例的 64 UTF-8 字节，必需内容占 65 字节；不是生产默认值。E0-178～180：8 MiB 前／等于／超过只作用于日志读取，日志必须由适配器生成可解析且其他限制满足的精确字节夹具，不可拿测得大小直接伪造结果。
- contract_version 保留 number/string 原类型；字符串不得为空或只含空白。原 v1 工件及程序存于 docs/validation/archive/handoff-e0-v1，旧报告不覆盖。
