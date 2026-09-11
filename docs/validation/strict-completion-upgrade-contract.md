# Strict 单入口升级：冻结任务包（2026-09-10）

## 目标、边界与交付

用户授权的公共测试边界是 `bind(...).gate(stage="completion")`，实际宿主示例为
`examples/strict_completion.py`。只强化此完成链路的证据内容检查、判定时有效性与诊断；
沿用合同、evidence_map、resolver/verifier、审批和门禁。不得引入第二套状态机。
`gate` 返回判定，不写完成状态；不得在本轮添加完成写入或重放历史业务。

允许修改：该示例、完成链路必要的根实现、对应测试、分发同步清单和本轮验证文档。
生成受影响的 Strict 分发副本；不覆盖其他既有工作。不改 Lite、全局安装、生产项目，
不提交、合并、推送或部署。不新增收费模型调用。

基线：main / 3e954ebaf484f79dffd897079bdee012529dd9a3，加本轮前既有 dirty 根源码。
先将完整根包构建到隔离目录，保存完整 manifest 与 hash；不得用 git HEAD 替代 dirty 基线。
交付调用链、缺口、最小 diff、机器结果、复跑命令及未知项。

## 冻结案例与预期

以下表在第一次案例执行前冻结，不随基线结果改变。测试均通过公共 gate。
模型原始输入为合成的“complete/pass”建议，不冒充真实模型运行。

| ID | 条件 | 预期 |
| --- | --- | --- |
| C01 | 合同、身份、实际内容检查、所有必需证据齐全 | pass |
| C02 | 遗漏必需 AC | unknown |
| C03 | 文件不存在 | unknown |
| C04 | 文件不可读（文件系统边界注入 PermissionError） | unknown |
| C05 | 证据过期 | unknown |
| C06 | 合同版本不匹配 | unknown |
| C07 | 产物 revision 不匹配 | unknown |
| C08 | 文件来自未授权工作区 | unknown |
| C09 | 当前证据互相冲突、无法确定权威版本 | unknown |
| C10 | 只有执行者宣称完成，无可读证据 | unknown |
| C11 | 格式合法且 hash 正确，但正文与验收无关 | unknown |
| C12 | 有充分内容证据明确违反本验收项 | fail |
| C13 | verifier 未注册，证据内伪造检查 pass | unknown |
| C14 | verifier 运行异常或超时 | unknown |
| C15 | 伪造检查输出，但真实内容检查失败 | fail |
| C16 | 检查通过后，同一 verifier 改写证据 | unknown |
| C17 | 后一 AC 检查期间改写前一 AC 证据 | unknown |
| C18 | 第一次通过后改写，再次请求判定 | unknown |
| C19 | 同一输入重复请求，无完成写入、无重复业务副作用 | pass |

所选内容判据是官方离线示例的精确产物内容，不扩张为任意业务验收证明。
运行期 checker 由可信宿主代码绑定，不能从 evidence_map 反序列化为可调用代码。
当前库不能证明同权限恶意宿主或恒定返回 pass 的恶意 callable 可信；显式保留此信任边界。

## 验证合同

1. 保存完整包基线；校验 manifest。失败不得声称该包已验证。
2. 先运行基线全部案例，保存原始 gate 和实际 checker 结果；确认真实缺口后才改实现。
3. 同一输入、相同宿主语义和 gold 运行候选；只将本轮明确修补的示例差异纳入两组处理差异。
4. 逐例核对三态与 passed 布尔值；只有 pass 的 passed 为 true。
5. 检查前后合同/事件/快照字节无完成写入；测试不执行任何生产动作。
6. 验证原有审批/独立验证、truth-source 和 rule gate 回归；不能用新逻辑放宽既有阻断。
7. 输出错误放行/应阻断总数，错误阻塞/应通过总数；三态错误另外列出，不混为放行错误。
8. 用 monotonic clock 测 gate 耗时及实际重试次数；token 与真实模型稳定性 unknown/not_run。
9. 根与完整隔离包回归、源码检查、增量 whitespace 检查；记录未完成或超时项。

历史线索：`.scratch/verified-experience/complete_context.py` 使用真实 root receipt 完成入口；
当前已读其源码，但 receipt 原件此前不可读，不能据此声称历史任务重验通过。
新案例以脱敏的相同“envelope → file → verifier → gate”结构合成，结果不计自然验证。
