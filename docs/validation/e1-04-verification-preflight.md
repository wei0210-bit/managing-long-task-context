# E1-04 验证前置草稿（未派发，不能越过 #18 验收）

本文件由主控在 E1-03 执行期间准备，只定位组合验证输入与迁移风险。不是新增框架或实现授权；正式派发时冻结合同、源码指纹和具体命令。

## 组合矩阵

使用冻结 E0-148～171 的 8 种 truth_sources/rule_execution/independent_validation 开关组合，各执行 valid、invalid_basis、changed_after_check，共24项。不得把未实现适配器、跳过测试或只读取schema计绿；输出每项实际调用、check/commit/business gate、generation/event数量及输入指纹。
`valid` 指可接管依据有效，业务有阻塞也可移交；不能把交接pass等同业务完成。`invalid_basis` 应在激活前阻断；`changed_after_check` 必须在真实核验回调与提交之间修改实际承重文件，不只把返回状态改成fail。
可复用既有专项夹具（按需阅读，不导入TestCase导致重复收集）：

- `tests/test_independent_validation.py`：真实临时工件与独立回执；不能把异名当不同身份。
- `tests/test_truth_sources.py`：公开观察、dirty、文件变化与completion尾部复验。
- `tests/test_experience_rule_gate.py` 及 rule execution 专项：既有经验/规则/业务门禁，保持承重判据。

## 迁移边界

真实旧包固定于 `/private/tmp/mltc-review-baseline.GYDdVc/context-strict`，必须重新用包校验器验证完整manifest `3d3e4f44b454adaa358d69c4e75eec4bbaa2ecedcb5d84abfdc6b34e33e50cc7`，不能只改版本字符串模拟旧包。
旧包自身不识别新fence，不能指望新库的写门禁自动约束旧进程。E0-172～177 应分别验证：旧writer活动/退出未知/检查后重新启动不得开放接管；可信安全退出及禁止重启证明后才能启用；重复请求零重复启用。`migrate_task` 是测试动作名，不新增产品API。
本地Python进程能证明本次测试进程退出，但不是Codex/Claude真实宿主适配证据。无法证明禁止旧writer重启时必须保留unknown和能力关闭，不能用假host直接pass掩盖缺口。需要新增宿主设施或E2+实现时由主控报告授权边界，不自行扩大。

## 防回归与成本

E1-01/02/03针对性和全部主控独立probe、旧completion/独立/Truth Sources/规则回归。唯一E2分发副本失败继续明确保留，禁止同步副本或删测试求全绿。
记录反例/正例分母、确定性重复、真实进程次数、耗时与重试。模型/自然使用/token仍UNKNOWN，禁止由本地重复推算生产可靠或节省比例。
