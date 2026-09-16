# E1-01 执行合同 v1：只读接管核验

状态：冻结，已派发，接口检查通过。发布者：本任务主控；执行者：`/root/e1_01_readonly`，Terra-high，独立新上下文。GitHub：#16。
本文件是开发授权记录，不是可信宿主身份、生产任务合同或接管许可。

## 已批准边界

用户已确认 E1 四单串行；本单仅实现只读接管核验。主计划 v0.22 的 E0 输入已通过，开发授权由本轮“按推荐”更新。
基线 HEAD：`0f5898e19b4951c661edce1f7db80f95cc1b2ecc`。
E0 v2：`tests/fixtures/handoff/manifest.json`，SHA256 `435e407c064b32a7d5012e0161c9b2e7bddc38c8d70ce42e12659102e7f52a7b`。
只读输入：`interface.schema.json`、`protocol.md`、`ready-state.json`、`cases.json`、`budget-profile.json`。不得改冻结预期、读取 expected 字段伪造实际输出。

## 所有权及交付

可修改：新 `src/managing_long_task_context/handoff.py`、核心 `src/managing_long_task_context/__init__.py` 的最小只读接入、新 `tests/test_handoff_protocol.py`。
执行报告：`docs/validation/e1-01-executor-report.md`；红绿运行记录：`docs/validation/e1-01-executor-runs.json`。
其余文件归主控或原用户所有。禁止修改 E0、生成包、SKILL、能力发布表、已有测试预期、生产状态与全局安装；禁止提交、合并、推送、部署、新付费模型调用。测试只用临时隔离目录，不读业务秘密，不执行业务动作。

## 已确认测试边界与实现约束

公开 seam：`validate_handoff`（读取已发布交接）、`handoff_status`（只读提交事实）。参数与响应遵循冻结 JSON schema；写入口本单不实现。
本单测试可以在隔离目录物化已发布记录／日志作为输入；不得因此新增能绕过核验的产品导入／发布入口。完整 prepared/activated/cancelled 状态机分别由后续工单实现；本单未支持的状态明确 unknown，不得猜测提交。
既有内核拥有锁及权威事件读取；新模块纯校验无 I/O，运行入口延迟调用内核。不得新增锁表、嵌套非重入锁或用普通非 TS 快照快路代替严格回放。
宿主核验为运行时注入的可信依赖，不属于 JSON 输入。没有可核查身份、许可及内容语义核验能力即 unknown；不能让文件自填 pass、合法格式、名字不同或 hash 相同单独证明条件满足。测试假宿主必须标 synthetic，文件核验使用真实临时文件。
**实现前接口检查点（已通过）：** 执行者先提出 runtime-only 签名、存储定位及只读 hook，主控于 2026-09-15 审核通过如下补充。不得自行发明宿主权限或放宽 E0。

### 主控接口裁决（开写前冻结）

- 两 Python seam 增加 keyword-only `handoff_verifier=None`，仅运行时依赖，不添加 JSON schema 字段；不改 bind，不造全局注册表。禁止从 JSON 加载可执行代码或构造 callable。应用注入的可信宿主是信任边界，不声称防御同权限恶意 Python 调用者。
- `handoff_verifier.verify(request) -> result`：核验输入由权威读取构造，含任务、交接、record digest、合同版本及 digest、工作区、包、代次、session/auth/basis/artifact 引用与观察时点。结果需身份／授权／内容分项检查，核验引用完整对应必需项，含绑定和时效。不能只反射输入构造 pass；缺字段、异常、错绑定、过期均不通过。宿主与内容 checker 由可信应用提供，假宿主正例需独立已知事实／规则对真实临时原件核验。
- 记录固定在 `<base>/<task-id>/handoff/<handoff_id>.json`，必须与权威 prepared 事件的 canonical record hash 一致。拒绝遍历和跨任务；合法工作区别名可规范化核对，不能随意重绑或放开引用 symlink。
- 为使已发布资料可读，准许最小 prepared 事件纯校验及读取投影接入；不能跳过未知事件或将其伪装为普通进展。activated/cancelled 语义在后续工单实现，本单未知状态不猜测。
- 读取期间受限 readline／计数／计时，缺日志不当空历史，未完整换行尾部不通过。共享锁外调用昂贵核验，再核对承重文件及宿主观察；不在持锁区域重新进入公开加锁 API。
- 本单不承诺 direct writer fencing（E1-02）或完整分发模块身份（E2）；源码开发正例不代表新协议可安全生产启用。

## 冻结验收（每项均须映射测试名及实际证据）

1. 有效、完整、当前且内容相关的隔离记录通过只读 validate；返回明确的 check_status、commit_status、代次、核验引用和只读下一步。不产生控制权、业务完成、授权或磁盘写入。
2. 必需依据遗漏、不可读、过期、冲突、未知分别不通过；错误任务／合同类型和值／digest／工作区／包／源码及产物绑定不通过，原因定位具体引用。H01-H03；冻结 E0-001～013 的相关输入语义。
3. 自报完成、自填 pass、有效 JSON 的虚假或不相关内容、不存在的宿主核验器、伪造身份／授权不能通过。可信假宿主的有效原范围许可为正对照；其缺失／撤回／过期／跨任务为反例。H15；不声称真实宿主验证完成。
4. 确定已存在的业务阻塞可以被完整读取，不能当成缺失接管依据；交接检查不得将业务 gate 改为通过。H05；后续 E1-04 验证完整组合。
5. 权威日志缺失、损坏、坏 UTF-8、截断、未知事件或读取失败均不以旧 snapshot 放行；不能把无法读取推断成未提交。H11-H14；完整新事件提交恢复由 E1-03负责。
6. 正式读取受冻结事件数／单事件字节／日志字节／items／时间预算约束，在读取、解析和重建过程中检查；超过限制 unknown 并指明资源原因，禁止先无限读取再报超限。预算不隐式扩大，不截断必需依据。E0-178～180 的准确 8 MiB 边界相关场景须记录实际运行或明确阶段依赖。峰值 RSS 仅实测，不冒充程序硬限额。
7. 固定输入和时钟下重复查询 20 次：语义相同，任务目录文件内容、数量与 mtime 不变，业务动作／新模型调用为 0；允许必要正式核验读取，不把它与后续轻量监测混同。
8. 核验回调前后有关文件／合同／授权观察发生变化时旧结果不可直接放行；耗时宿主检查不持独占写锁。H10-H11。本单只读响应为时点结果，后续 activate 必须重新检查，不能复用外部 pass。
9. 不改变未启用交接的旧任务 API、completion/independence gate。运行新测试与必要旧回归；真实宿主、模型冷启动、自然使用、token 收益均为未验证。

## 验证与失败条件

严格按 tdd 一条行为红→绿推进；缺模块、语法错误、导入失败不是行为红。测试只能从公开 seam 观察；允许注入宿主、时钟、文件系统边界，不 mock 自有私有方法制造通过。

冻结输入核验：
`PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 tests/handoff_spec.py tests/fixtures/handoff --expected-manifest-sha256 435e407c064b32a7d5012e0161c9b2e7bddc38c8d70ce42e12659102e7f52a7b`

针对性测试：
`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_handoff_protocol -v`

必要回归：
`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /opt/homebrew/bin/python3.12 -m unittest discover -s tests -q`

交付须有实际命令、退出码、测试数／失败／跳过、红绿输出、耗时、案例映射、未运行项和已知缺口。错误放行及错误阻塞写数量与实际分母；未测 token 写 unknown。未实现的 E0 变体保留 NOT_RUN，不算分母。
任一错误放行、意外写入、伪宿主冒充真实、放宽预期、未运行却报通过，均不验收。遇接口或安全语义冲突，提交具体请求给主控后停止该分支，不自行扩范围。

## 后续与审核

主控独立读取 diff、针对性复跑并检查负例；执行者完成消息不是验收。通过后才允许 E1-02 开始。不要求自然时间等待：本单为本地机制验收；实际宿主和项目使用留到后续授权阶段。
