# Skill 隔离使用验收

状态：LOCAL_PASS_WITH_LIMITS，2026-09-16。不是浏览器QA、真实模型冷启动或生产接管验收。

## 身份与范围

工作区 `.worktrees/short-session-remaining`；分支 `codex/short-session-remaining`；HEAD `0f5898e19b4951c661edce1f7db80f95cc1b2ecc` 加未提交候选。
主计划v0.38 SHA-256 `18b269fc833c5ad3459f9f0434ddeed65f7b4773336cfe9ed38a69968225b028`，与恢复入口一致。
每一包清单文件逐字节匹配上一轮持久收据，每一分发文件匹配当前候选源码；完整 verify/doctor 均通过。

- Strict0.8.0 manifest：`cbd3499c536c1f6800b45b26c73fb19a7848e1ae7a11fa897fbeb5d22d3550d3`。
- Lite1.4.0 manifest：`f953804bb28b01856060088a0b9822d7da88fe8a8331583e35d9564bb32bcb3c`。
- 包路径：`/private/tmp/mltc-review-fix.x5qKWs/context-strict` 及 `context-lite`。

本轮未修改产品文件，只新增验收工件及恢复导航。没有安装、提交、推送、部署、模型或业务调用。

## 冻结与实际结果

运行前冻结：[验收合同](2026-09-16-skill-acceptance-contract.md)。
完整命令、输出、时间、退出码及冻结文件hash：[原始结果](2026-09-16-skill-acceptance-runs.json)。

| 路径 | 预期 | 实际 |
| --- | --- | --- |
| Lite flush→绑定→新进程cold-check | 交付材料，保留unknown在途项和阻塞 | 通过；First action正确；语义pending、历史继承unknown、归档false |
| 相同NOW新进程读取3次 | material一致、不改NOW | 3/3一致；字节不变 |
| NOW指纹错误 | 不交付材料 | exit2，material=null |
| 工作区错误 | 不交付材料 | exit1，material=null |
| NOW缺失 | 不交付材料 | exit2，material=null |
| 原件变化而NOW不变 | 不冒充原件核验 | 返回旧材料，仍pending/禁止归档；未自动识别原件变化 |
| Strict公开合成示例 | prepare/validate/activate/cancel成功，重复不追加 | 通过，activation_events=1，重复日志不变 |
| 包外Strict定向测试 | 无失败、跳过、资源警告 | 55/55；13.666秒（测试框架） |
| 包外Lite定向测试 | 无失败、跳过、资源警告 | 14/14；4.478秒（测试框架） |

69个测试方法与公开路径有覆盖重叠，不能相加成独立业务案例。旧561项全量结果仍属于2026-09-15，本轮没有重跑全量。

## 成本与判定

- 16条子进程命令累计墙钟19.800秒，包括校验、夹具生成、启动及测试；不包括编写脚本、人工/模型分析时间。
- Lite正常cold-check三次分别63.929/63.127/66.967毫秒，单台本机合成样本，不是性能SLA。
- 独立负向材料释放案例错误放行0/3；正常材料释放案例错误阻塞0/1。正常案例重复3次仍只计一个独立场景。
- 原件变化案例是语义边界观察，未纳入上述分母；不能将其称为stale自动拦截成功。
- 程序判定一致性：同输入3/3。真实模型一致性NOT_RUN。
- 新模型调用0；真实模型输入/缓存/输出token、费用、节省比例、重试收益UNKNOWN。本轮对话本身存在模型消耗，未单独计量，不称零token成本。
- 未单独量内存，无新增常驻进程；临时合成任务由测试清理，原始输出持久保留。

## 结论与下一阶段

候选可继续做有限、人工接续的隔离Agent试用；不能据此开启未经验证的自动接管或替换生产安装。
Lite的cold-check只保证材料与身份，**不保证材料与当前事实一致**。这是既有明确边界，不能用本轮全绿掩盖；本轮不扩写提示词或新建校验框架。
Strict示例使用合成宿主注册表；CLI测试用假命令夹具；Codex/Claude原生接口只测拒绝路径，真实可信身份、控制权排他、跨父会话存活/接续仍未验证。

下一步真实Agent验收应先固定四类输入：正常接续、原件已变化、unknown在途动作、包/工作区不匹配；仅提供完整包与最小任务入口，不给历史答案。独立核对目标/约束/阻塞/下一步，并要求原件变化不能继续当已核实、unknown不能自动重试。分别记录模型原始回复与程序结果，不能让模型自报通过。
真实模型调用与费用上限、可信干净会话来源尚未确定，本轮不启动。该阶段不得用现有69个程序测试替代；自然项目使用另表记录。

## 复跑

在候选工作区执行，输出用新文件名保留原结果：

```sh
/opt/homebrew/bin/python3.12 docs/validation/skill_acceptance_20260916.py /private/tmp/mltc-skill-acceptance-rerun.json /private/tmp/mltc-review-fix.x5qKWs
```

临时包失效时按2026-09-15修复报告重建并核对上述manifest；不跳过身份检查。
