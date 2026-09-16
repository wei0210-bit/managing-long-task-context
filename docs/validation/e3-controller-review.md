# E3 主控集成审核

状态：**E3-local accepted**。2026-09-15主控独立验收完成；仅本地阶段通过，不代表真实宿主已上线。

范围：既定E3本地Codex CLI适配。所有运行均为隔离Python模拟CLI及合成宿主；没有真实Codex任务、SSH、生产动作、安装、提交、合并、推送或部署。开发Agent确实有模型使用，但未独立计量其token；这里的“模型未运行”仅指效果评估/真实CLI业务任务。

## 入口、实际调用链与边界

`CodexCliHost.start_child/resume_child` → 输入/固定配置/宿主回执核查 → `HostTaskLedger.reserve` → 既有任务锁、严格事件重放、合同与主控代次/授权复核 → 原子预留事件 → 再查程序/工作区身份及回执有效期 → `Popen(argv, shell=False, stdin=DEVNULL, cwd=...)` → 有界读取 → 0600输出工件与观测事件。

结果路径为 `publish_result` → 原件落盘/版本化事件 → `reconcile_result` 实际调用检查器 → 在锁内重查合同、授权、原件及代次 → 单条处理提交。新实例用 `observe` 按引用发现记录，不需要旧聊天。历史通过结论在摘要中标记需重新核验；摘要不是放行许可。

**处理提交不等于任务完成或业务执行成功。** `status=pass`可能仅表示记录操作成功；业务检查结果另在`verdict`，旧完成`gate()`不被重写或旁路。模型填写pass、线程事件或退出0均不能因此完成任务。未知动作不自动重试，旧attempt晚到信号保留但不冒充当前结果。

真实身份、进程排他、工作区基线及授权来源仍需要可信宿主适配器。合成回调的成功不能证明实际Codex/Claude宿主已受控，`verify_host()`仍明确返回未知能力。线程占用、干净会话、自动rollover、父任务退出影响、自动归档不在本地结果中冒称可用。

## 发现并修补的缺口

- CLI的显式JSON输出、精确resume线程事件、参数隔离及无效编码；预留后程序/工作区替换与授权过期不得启动。
- 未知线程、错误/冲突输出、超时、超限、继承管道未结束与持久化异常，不得误标未执行或解锁后续尝试。
- 旧代次请求、观测与预留不一致、冲突预留重放、旧合同/旧attempt晚到结果均不能放行；旧原件和安全信号保留。
- 冒名发布、同结果三次处理产生重复提交、检查器读取后原件或授权变化等真实反例均先记录失败再修补。
- child授权的`work_item_id`必须精确等于attempt；prepared不允许主控继续调度，但允许授权child发布自己的结果；跨attempt拒绝。事件actor使用实际已核主体。
- 恢复摘要按result_version识别冲突，保留最新64条并显式报告截断；不把合法版本迭代误判为冲突，不将历史pass缓存成当前许可。
- 恢复统一UTF-8摘要编码，修复中文路径误阻；输入surrogate显式拒绝，不靠换编码规则绕过。
- 完整包测试发现未关闭管道资源警告；reader最终在自身线程关闭流，不让主线程阻塞在仍被读取的buffer锁上。

## 最小改动与兼容性

以E2冻结完整包为基线，不以Git HEAD混入已有E1/E2改动：

- 新增`host_codex_cli.py`和`host_records.py`，核心只接入5类事件的校验/投影、既有原子publisher与导入身份覆盖；handoff只新增5个operation-purpose映射。原状态机、证据解析器、完成门禁不替换。
- 根SKILL正文相对E2没有新增；宿主说明按需放在`references/host-codex-cli.md`，不默认把实现源码放入模型上下文。
- 新模块、测试及其依赖一起进入59文件完整候选包；缺失/篡改/异包导入不能借用合法身份。独立开发分发测试不打进安装包。
- Strict保持0.8.0本地候选，以manifest区分完整包；不是已提交版本。Lite不变。原7份用户文件和E0预期不改。
- 新事件对旧、不认识这些事件的程序不承诺兼容写入。继续沿用E1/E2的完整包身份和迁移限制，不允许混用旧进程与新包来执行接续。

## 冻结案例与验证记录

预期：[执行合同](e3-execution-contract.md)、[P01–P16](e3-controller-cases.md)。实际运行记录独立保存在[e3-controller-runs.json](e3-controller-runs.json)，旧失败、撤回候选及夹具错误不覆盖。

| 组 | 本地核验方式 | 不可推出的结论 |
|---|---|---|
| P01/P02/P03/P06 | 参数数组、EOF、8000字符正常边界、中文路径、请求拒绝、实际启动计数及fresh Ledger恢复 | 真实模型或权限配置已经生效 |
| P04 | 两个真实Python进程，同一UUID不同attempt，命名入口屏障后至多1个预留 | 全操作系统所有旁路写者均被封禁 |
| P05/P15 | 实际超时/输出超限/坏UTF8/冲突线程/管道继承、路径替换、FIFO、不合法输入 | 业务未执行、子孙已停止、可以重试 |
| P07 | 旧代次拒绝与gen1正常对照，prepared/child归属；检查中撤销授权拒绝 | 宿主身份签发器具备生产可信度 |
| P08/P09 | 重复3次仅1提交、冲突双方原件、旧attempt晚到、新实例发现 | 任意历史结果可以继续当当前事实 |
| P10/P11 | 实际检查器缺失/失败、原件变化、合同变化、授权变化，禁止不充分结论 | 原始结果文本等于业务正确 |
| P12 | 真进程在事件replace前/后被终止，新进程重读与两次处理最终仅1提交 | 断电、内核崩溃或真实Codex中断恢复 |
| P13/P14 | 未知动作阻止替换/重试，未验能力显式unknown | 已具备完整调度器或自动rollover |
| P16 | 源码目录外完整包、双模块6个缺失/篡改/异路径子例 | 全局安装或远程CI已通过 |

真实历史数据没有被重新执行；这些E3实现探针全部明确为合成案例。E0原始180个场景预期保持原样，不把输入规格检查改写为产品通过。部分补充测试是在修复之后首次持久化/运行，记录中明确为追补验证，不伪称全部完成了TDD红阶段。

## 候选身份

E2基线包：`/private/tmp/mltc-e2-controller.rGw7ow/context-strict`，manifest `51331cb7ea3edb2c120d1f1a5efa76dff32d79edd7644a1f0f98312ab0817165`；本轮再次verify通过，未修改。

首个E3包`/private/tmp/mltc-e3-controller.NK3pJL/context-strict`（manifest `83b531edd328fee21bf29b2d4f79ddbd7550826cf29693994d61f3e62c04257d`）因资源警告撤回，不作交付包。

最终候选：`/private/tmp/mltc-e3-controller.NK3pJL/context-strict-final`，59文件，来源`candidate:dirty-worktree-0.8.0-E3`。

- manifest：`cf4b6266af825704fcf377120e9daf24574df4946180745d385c87a46d46c074`
- source_tree：`94de99a5e47698f2af08b1b6bfc1e9fceb27a56660885781ebca19a52d6fdb7a`

临时路径可能被系统清理；可从本轮源码按相同命令重建，不能靠这个临时位置建立项目长期记忆。

## 复跑命令

仓库根目录使用Python3.12；不启动真实Codex：

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python3.12 docs/validation/e3_controller_probes.py -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python3.12 docs/validation/e3_process_probes.py -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests python3.12 -W always::ResourceWarning -m unittest test_handoff_codex_cli test_handoff_host_records test_handoff_host_distribution -v
MLTC_LEGACY_PACKAGE=/private/tmp/mltc-review-baseline.GYDdVc/context-strict PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3.12 -W always::ResourceWarning -m unittest discover -s tests -q
```

旧包类比路径须先确认存在；拿不到不能忽略skip后声称完整回归。完整包用`scripts/skill_package.py build/verify`，然后在源码树外显式设置`PYTHONPATH=<package>/src:<package>/tests`运行宿主测试，检查非零测试数量。CI仅补了定义与本地等价验证；远程CI未触发。

## 成本与待验

最终全回归507/507，55.844秒，0 skip、0 ResourceWarning；源码树外宿主33/33，13.110秒；E2包身份反例6/6，1.077秒；P16双模块缺失/篡改/异路径6个子例随完整回归通过。完整包verify及doctor full均通过。所有验证进程已收取退出。

主控17个接口案例＋3个实际进程案例，按TestCase方法分组（内部子输入不重复计分）：12个应阻断/降级组错误放行0/12；8个正常/恢复组错误阻塞0/8。相同合成场景连续复跑3轮，60/60组断言成立。接口组每轮0.611/0.625/0.632秒，进程组1.012/1.000/1.020秒。此计数仅针对本地E3操作，**不是业务完成率、真实模型稳定性或生产故障率**。

幂等性成本：同attempt重复请求增加启动0；同结果重复3次处理提交仍1；核验会重新运行以检测依据变化，不以永久缓存pass省开销。管道清理反例在独立解释器开启ResourceWarning后先红后绿。运行耗时包含解释器、测试夹具、文件与本地子进程，不是仅Skill增量成本；没有控制其他宿主负载，不能与历史47秒直接算性能退化或收益。

token输入/缓存输入/输出、RSS增量、开发Agent独立成本、真实模型稳定性、自然项目完成率与省token收益均UNKNOWN/NOT_RUN。确定性重复只能说明本地程序在这些固定输入上的一致性，不能当真实模型稳定性。

结论：值得进入后续宿主适配/受控真实路径验证，但尚不值得据此全量自动迁移生产项目。E3本地工单可关闭；真实宿主、模型效果、自然使用单列待验。不安装，不提交/发布，E4+尚未启动。
