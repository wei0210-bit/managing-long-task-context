# E1-03 主控独立案例冻结 v1

冻结于 E1-03 实现前；依据 `e1-03-execution-contract.md` v1.1，全部合成隔离目录，不执行模型或业务动作。根用例不调用 executor 的 activation helpers，只复用已验收的 prepare 夹具；可信身份用主控独立注册的对象句柄，文件内容逐一核实。缺 API 不算行为红。

| ID | 输入变化 | 预期 |
|---|---|---|
| A01 | 正常目标、当前证据与原授权 | pass，activated仅1条，7→8；重复请求不写文件 |
| A02 | 无authorizer、无verifier、非注册主体、自报pass | 非pass，无激活、任务文件不变 |
| A03 | 回执缺subject_session_ref、指向source、ref_id冒充subject_id、时间过期 | 非pass，不可凭名字授予控制权 |
| A04 | 该次核验后承重文件变化、record变化 | 非pass，无激活；不依赖先前validate结果 |
| A05 | 重复请求但工作区或包不符、代次为bool/float/旧值 | 非pass，无额外事件，不以恢复掩盖输入错误 |
| A06 | 激活后证据缺失/改变 | 当前check非pass，历史commit仍confirmed_committed、代次8 |
| A07 | status连续20次，无verifier的状态查询 | 查询零写；无verifier当前check未知，不抹去权威提交事实 |
| A08 | 激活后旧主控裸写/旧身份/旧代次；新主控及原child许可 | 旧控制阻断；可信新主控、child原范围可继续；不得扩权 |
| A09 | cancel后新ID；activate后新ID | 新交接可准备；每次activate才增代次，历史不会当未知活动交接 |
| A10 | 进程在真实fsync边界及响应前终止、并发候选、child非承重增量 | 依据合同AC3/5/6分别审executor进程证据，不能用本表冒充已运行 |

实际运行、错误放行/阻塞分母在主控报告另记。确定性重复只说明程序一致性，不说明真实模型稳定性、token收益或宿主已经可信。
