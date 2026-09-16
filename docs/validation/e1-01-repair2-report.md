# E1-01 repair2 执行报告（待主控独立验收）

执行合同 SHA-256：`39b770f90ae67a16b7fbeddc2e98269217c284e405aa010cf0800d921407fc45`。

本轮只修改合同授权的 `handoff.py`、核心只读接入和
`test_handoff_protocol.py`，以及本报告和运行记录。未修改 E0 fixture/manifest、
主控 probes、分发副本或用户文件；未安装、提交、推送、部署或调用真实宿主/模型。

## 修复内容

- 控制状态：任意 `handoff_activated` / `handoff_cancelled`（包括其他
  handoff）在 E1-01 只读路径均为 unknown，不能继续用旧 prepared 事实放行。
- 本地引用：标准库严格解析 `file:` URI，解码 `%20`；只接受绝对路径、空或
  `localhost` authority、无 query/fragment，并继续限制 workspace、常规文件和
  非 symlink。
- 严格 replay：新路径拒绝不完整 item/checkpoint payload；旧
  `_rebuild_snapshot` 未改。高容量 item replay 避免每条复制既有完整 projection，
  但公开 `record → update_item → checkpoint → brief` 回归仍能观察原投影。
- verifier binding：逐字段要求 Python 类型和值均一致，拒绝 `True` 代替 `1` 和
  `7.0` 代替 `7`。
- 状态语义：`validate_handoff` 的任何未知结果均为 `not_attempted`；
  `handoff_status` 在日志不可读时仍为 `unknown`，不把提交事实降格为未尝试。

## AC 映射与实际证据

| 合同 AC | 公共 seam 测试／子例 | 本轮结果与边界 |
| --- | --- | --- |
| 1 | `test_valid_complete_prepared_record_passes_without_writing_or_granting_control`；`test_known_business_blocker_remains_ungranted_by_readonly_validation` | 通过；无写入、gen=7、`not_attempted`。业务 blocker 的承重内容可读，但返回明确不授予 business completion。|
| 2 | URI `%20` 正例；workspace/package、float version、重复字段、错 digest、缺/变 source/artifact、发布合同不匹配 | 通过；合法本地 URI 不误阻，缺失/错误绑定为 unknown。|
| 3 | 无 verifier、伪 verifier reference、撤回授权、host exception、binding `True`/`7.0` | 通过；合成 verifier 标记为 synthetic，未声称真实身份/授权完成。|
| 4 | `test_known_business_blocker_remains_ungranted_by_readonly_validation` | 通过 E1-01 只读边界；完整 business gate 组合仍属于后续 E1-04，未标为已跑。|
| 5 | 缺日志、坏 UTF-8、截断、未知/跨任务事件、同一缺日志的 `validate_handoff` 与 `handoff_status` | 通过；状态查询不可读时 commit 为 unknown，未以 snapshot/旧结论放行。|
| 6 | 完整合法 item 的 8MiB −1/等于/+1，64KiB −1/等于/+1，1,998 item/2,000 event，读取和重建 deadline | 通过；资源超限为 unknown + `not_attempted`。2,000 事件总上限包含合同发布和 prepared 两条，故最大可达 item 为 1,998；不是 snapshot 2,000 条限制的正例。新鲜进程 8MiB 三点夹具：Darwin `ru_maxrss=67,977,216` bytes，低于 134,217,728；这是该进程实际峰值，不是程序硬限额。|
| 7 | `test_twenty_fixed_readonly_queries_are_semantically_and_bytewise_stable` | 通过；20 次固定只读查询无任务目录内容/数量/mtime 变化。token 成本 unknown，未调用模型。|
| 8 | callback 后文件改变、callback 期间 writer 进展、CR09 其他 activated | 通过；最终输入变化 unknown；线程握手确认 verifier 不持写锁，writer 完成后最终重观测阻断旧结论。|
| 9 | `test_context` 两条 completion gate 回归 | 通过（2/2）；未改变未启用 handoff 的 completion 冲突/unknown gate。完整发现式回归本环境两次均在 30.2 秒交互窗口未给出终态，故不声称全绿；E2 分发同步依赖仍未处理。|

## 分母与未验证

- 本轮针对性执行者套件：28/28 通过。主控 probes：10/10 通过；仍需主控独立复跑，不以执行者结果代替验收。
- 错误放行：本轮定位的 CR09、CR10、`True` version、`7.0` generation 共 4/4 均已由对应公共 seam 阻断；这不是自然故障率。错误阻塞：编码空格 URI 1/1 已恢复 pass。
- 真实宿主、生产身份/授权、模型冷启动、自然使用、token 收益、完整 activate/cancel/write 状态机与 E2 分发同步均为 UNKNOWN/未实现，不计为通过。

原始命令、退出码、分母和输出摘要见
[`e1-01-repair2-runs.json`](e1-01-repair2-runs.json)。本报告不是验收结论。
