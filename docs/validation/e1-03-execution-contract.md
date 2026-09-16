# E1-03 执行合同 v1：唯一激活与提交恢复

状态：验收/所有权冻结，#17 已于2026-09-15T09:32Z通过最终主控源码验收；接口须主控裁决再写实现。GitHub #18。Terra-high 新上下文，禁止继承执行者长历史。

## 依据与边界

主计划 `docs/superpowers/plans/short-session-handoff.md`，仅 E1 四单授权。读取 `e1-03-verification-preflight.md`、E1-02 执行合同接口附录、E1-02 主控验收记录及冻结 `tests/fixtures/handoff/{protocol.md,interface.schema.json,ready-state.json}` 的相关部分。
E0 manifest SHA256 `435e407c064b32a7d5012e0161c9b2e7bddc38c8d70ce42e12659102e7f52a7b`；不能改字段/预期或直接读 expected 生成产品结果。E0 180 个场景此前只是输入通过，未运行不能记成功。
基线 Git HEAD `0f5898e19b4951c661edce1f7db80f95cc1b2ecc`；有已验收 E1-01/02 未提交源码和用户文件，不能覆盖/清理。当前分发副本未同步，是明确留给 E2 的已知失败；不能改副本或删测试来获得全绿。
禁止全局安装、提交/合并/推送/部署、改生产状态、执行真实子任务/业务动作和新付费模型调用。真实宿主/身份/即时撤权/掉电/自然使用/模型稳定性/token收益均未验证。只用本地临时目录及合成宿主。

## 所有权与实现检查点

可改 `src/managing_long_task_context/handoff.py`、核心 `__init__.py` 的最小锁/提交/薄代理/投影钩子；可新增 `tests/test_handoff_activation.py`、`tests/test_handoff_process_recovery.py` 和该套件的最小进程夹具模块；自己的 `docs/validation/e1-03-executor-report.md`、`e1-03-executor-runs.json`。
主控拥有既有 E1-01/02 测试及两套 controller probes、计划、CONTEXT、E0、分发目录和用户文件。新状态使既有测试需从临时“activated未支持”演进为“身份可核查才接受”时，先指出具体断言，由主控修改；不能删除原错误放行/无写入预期。
先提交短接口提案：沿用 `activate_handoff` 的冻结 JSON 参数及已有 runtime-only verifier/authorizer，说明如何由可信宿主确认候选就是 record.target_session_ref、激活后 controller 写入主体如何绑定当前目标、child 原范围许可如何保留；说明最新控制状态/多个已结束交接/同请求幂等如何从三事件重建；status怎样独立表达当前check与已提交事实；进程故障点、锁序与预算如何复用。
不建立新宿主权限框架或平行状态库；外部回调只在锁外，短锁内纯复核及提交。激活专属编排放独立模块，不继续堆核心。旧核心拥有单一锁与事件提交，禁止嵌套非重入锁和新锁表。正式解析沿用 strict JSON/有界回放；legacy 检测保持独立流式控制事实探测，不能把 2000/8MiB 限制加到无协议旧任务。

## 冻结验收

1. 当前完整 prepared、可信宿主独立确认目标身份/原范围承接许可、内容/合同/包/工作区/产物对应均有效时激活，追加恰好一条 activated、generation 恰好+1。没有verifier/authorizer、模型名字/自填pass、错误主体/授权/目标不能激活。新主控不因此获得业务完成、发布或额外权限。
2. 该次 activate 自行核验；外部传来的旧 validate pass 不作许可。核验期间改变承重文件、record、合同、授权观察或代次，短锁内阻断旧结果；没有激活副作用。保留严格类型比较（bool/float 不能冒充整数代次）。
3. 两个真实并发候选/重复请求使用屏障安排，最多一条激活事实、generation只+1；相同请求重复返回原提交事实，无重复事件。同ID异动作/record/workspace/package必须冲突或unknown，不能由恢复分支掩盖输入错误。
4. 激活后原主控迟到的调度/控制写拒绝；目标主控按当前代次和原范围可写；旧child凭其未撤销的原任务许可可继续进展/结果，不重建子进程、不扩大角色。自填actor不同名字不能作为主体独立性证据。
5. 普通事件序号变化不混同控制代次。核验期间一个合法child普通进展在承重依赖未变时可保留，不能无条件把所有新事件当控制变更；未知影响仍保守重验。用真实记录证明普通进展与控制事件不同。
6. 进程故障验证：事件fsync前终止/失败、fsync后snapshot替换失败、fsync后响应丢失/真实子进程被终止。父进程通过屏障确认故障位置，再用新Python进程只读status。已完整fsync事实应确认已提交且+1，不重复事件；半条/不可读/持久性无法确认保持unknown，不复活旧主控、不盲重试业务。
7. status 分开呈现当前证据check和历史commit：已提交后证据过期/改变，不得改说“未提交”；当前check可unknown/fail，commit仍按权威事实独立确定。状态查询20次没有任务文件内容/数量/mtime变化、模型/业务动作0；程序重复不是模型稳定性证据。
8. 连续交接：取消后新ID再次prepare，以及一次激活后的下一次合法交接可区分历史closed与唯一pending；代次只由每次成功activate增长。存在损坏/冲突/非法顺序/另一交接未知控制事实时不得拿旧prepared继续放行。prepare/cancel本身不涨代次。
9. E1-01/02原门禁、legacy行为、8写入口fencing继续有效；已取消状态不退回无身份legacy；激活后取消不得恢复旧主控。必要旧completion/独立验收/Truth Sources回归无新失败，E2分发失败明确保留。

## 验证方法、失败条件、交付

TDD：每项行为红→最小绿；缺函数/导入/语法失败只是scaffold，不算行为红。通过公开 seam + 真实临时文件验证，故障注入在 `os.replace`/`os.fsync` 等真实I/O边界或真实子进程信号，不mock自有私有提交方法直接返回成功。并发必须有可观察同步点和所有子进程/线程退出断言，不使用sleep猜时序。
包内行为预算保持 events 2000、日志8MiB、单事件64KiB、snapshot items2000、read/parse/rebuild5s；不能用无效padding冒充合法边界，不能在完整读完后才报限额。峰值RSS只报实测，不冒充硬cap。若遇真正接口歧义，向主控提出最小裁决请求，不停下来等用户“继续”。

针对性：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_handoff_activation test_handoff_process_recovery test_handoff_writes test_handoff_concurrency test_handoff_protocol -v`
旧独立：同环境运行 `docs/validation/e1_01_controller_probes.py -q` 和 `docs/validation/e1_02_controller_probes.py -q`（主控先裁决必要状态演进，不自行删断言）。
全回归：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /opt/homebrew/bin/python3.12 -m unittest discover -s tests -q`；工具让出继续poll到终态，不把30秒yield当超时。
冻结输入：`PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 tests/handoff_spec.py tests/fixtures/handoff --expected-manifest-sha256 435e407c064b32a7d5012e0161c9b2e7bddc38c8d70ce42e12659102e7f52a7b`；`git diff --check`。

每项AC对应实际测试、输入/预期/实际结果、命令退出码/计数/耗时、事件与代次证据、未运行部分和hash。测试夹具要独立核对实际内容/身份原范围，不一律反射请求pass。模型原判、token、自然使用未知就写UNKNOWN；机制测试不混入真实效果分母。收口后明确停止源码写入交主控，未验收不派#19；E2+始终未授权。

## v1.1 主控接口裁决（原九项验收不变）

1. 冻结 JSON 参数不变，复用 runtime-only `runtime_identity/write_authorizer/handoff_verifier`。增加仅运行回执的 `subject_session_ref` 完整稳定引用，由可信宿主从真实注册主体独立导出；`subject_id` 不等同 `ref_id`。activate 必须绑定 record.target；已激活后 controller 写、后续 prepare/cancel 必须绑定权威最新 controller，后续 record.source 同样匹配。初次 prepare/cancel 旧回执保持兼容，扩展回执严格字段集合；新阶段缺少主体引用不得放行。child 保持可信宿主核验的原 work_item/scope，不与 controller 身份混同，不新增权限状态库。
2. authorizer purpose 增加 activate，controller 专用；target_activation_status 按操作与投影阶段精确检查。不能已激活后还要求目标未激活，也不能普遍放宽为任意值。
3. 唯一控制投影由三事件严格重建，支持历史 closed 与唯一 pending；代次只由 activate 增加，cancel 不退回 legacy。当前 check 与历史 commit 独立输出，不用证据过期抹去提交事实。
4. 锁外宿主核验，短锁内复核。不能用 events digest 全等误阻塞 AC5：只有可明确证明与承重依据无关的已授权 child progress/result 增量可以穿越；影响未知、承重项或控制投影变化仍阻断。不要无条件忽略所有普通事件。
5. 实际进程屏障定位故障，恢复最多一次只读权威核对，不补写不重试业务。请求冲突/错误工作区不得落入历史成功恢复；复用原 strict parser、边界与单一锁。

主控已审核执行者提案并按上述边界批准 E1-03 编码；需调整旧测试时先由主控裁决。无新增安装、发布或宿主适配授权。

### v1.2 增量可信来源补充（AC5 不降级）

现有普通事件没有可独立验证的 child 授权回执；不能以 actor、合法 JSON 或进程内“曾通过”缓存冒充可信来源。不改冻结事件/请求 schema，不新增持久化权限库。仅在核验期间出现普通增量时，复用 handoff_verifier 的可选 runtime-only `verify_delta(request)`，由可信宿主独立确认具体 child 执行记录、原许可和非承重性质。能力缺失、来源不明则 unknown。
严格回执字段：`status, task_id, handoff_id, record_sha256, contract_version, contract_digest, workspace_root, package_manifest_sha256, controller_generation, before_events_sha256, after_events_sha256, delta_event_ids, delta_events_sha256, non_bearing, observed_at, expires_at`；status=pass、non_bearing严格True，全部绑定和类型/时效均核对。请求附具体delta，不反射请求制造通过。
路径：锁外原完整核验→短共享锁获取after→先拒绝控制/合同/record/refs/代次与明确承重/阻塞/完成变化→锁外增量核验→短独占锁要求after摘要完全一致再提交。没有delta零新增调用，after再变unknown，不循环。合成宿主仅允许自己观测到的真实public child writer事件与明确scope；跨进程真实宿主证明仍未验证。

### v1.3 控制事件发布边界修补（保留原失败证据）

真实进程反例已命中原 `_append_event_locked` 的 event fd（dev/ino匹配）：完整换行flush后、实际fsync前注入OSError，调用却经恢复返回pass/confirmed_committed。可读不等于已刷盘，不能放宽预期或用snapshot掩盖。原反例、命令与输出保留在process报告；不能用后续绿结果覆盖。
批准最小内部修补：只有三种handoff控制事件在既有同一锁内将有界旧log+新event写到同目录临时文件，flush/fsync临时文件成功后，atomic replace发布canonical events，随后更新snapshot。唯一事件流、schema、公共接口和普通业务事件append均不改；不新增平行状态库。保留原文件mode，拒绝不安全路径，清理本次临时文件，不删历史证据。发布前检查最终事件数/字节预算，不能发布后才发现不可读。
canonical events发布是本轮进程故障验证的线性化点：发布前失败且严格旧log可读，确定未提交；发布后snapshot失败/响应丢失，确定已提交。临时文件已fsync但尚未发布不等于事件已提交。半行/不可读/无法确定发布结果仍unknown。此条精确化本合同AC6中泛写的“fsync前均unknown”，采用主计划H12“可证明未提交→重新检查后才考虑重试”；不允许把原append留下的未刷盘新event判pass，不自动重试业务。
真实进程新增屏障：before_temp_fsync、after_temp_fsync_before_publish、after_events_publish、before_snapshot_replace及after_commit_before_response。保留原append失败录证；新测试不得把故障偷偷移到写入之前。进程终止不声称机器掉电、目录项断电恢复或宿主适配已证明。记录控制事件额外有界复制开销/RSS；回归三控制入口与普通写并发，证明不覆盖已锁定的追加。

执行所有权补充：`/root/e1_03_activation` 独占源码及activation tests；其明确移交新process tests/fixture/report给 `/root/e1_03_process_tests`，后者不写源码。主控审核、独立反例与最终验收不变。以上内部发布实现仍在E1授权，不改变E2+禁止范围。
