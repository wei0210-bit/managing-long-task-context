# E0 收口复核：需修改，不放行 E1

**后续状态：** 本文保留 v0.21 的发现和当时结论。四项已在 v0.22 [修复与复审](2026-09-15-handoff-e0-repair.md) 中关闭；仅方案／工程输入审核收口，E1 未授权，实际产品验证未运行。

2026-09-15 06:37 UTC；基线 `0f5898e19b4951c661edce1f7db80f95cc1b2ecc`。

结论：**本轮复核已结束，工程审核未通过。** v0.20 的“测试程序通过”证据仍有效，但不足以支持“E0 可作为完整开发输入”的验收结论；该结论暂停，待下列问题修复后复审。

范围：主计划中的 E0、冻结目录／147 个变体、schema、只读校验器及测试。文件均未提交，commit diff 为空，不能按 `code-review` 的非空提交差异前提运行双 Agent 审核；本次是主控本地工件复核，不是独立交叉验收。按 Context Strict 的失败判据检查实际内容，不以 manifest 或测试绿灯替代语义审核。

## 发现

### E0-R1 · P1 · 已刷盘后退出被写成提交未知

`cases.json` 的 **E0-030** 从 prepared 开始，前置动作 `activate_until_injection`，故障点 `after_fsync`，故障仅为进程 `kill`，却预期 `unknown/unknown/null`。同文件 **E0-041** 在相同提交阶段预期 `pass/confirmed_committed/+1`。

主计划 ENG-D2 与 protocol.md 要求：事件已刷盘且后续可读取时，恢复查询能确认提交；不能因为进程退出、快照或回执丢失否认提交。E0-030 没有注入读取失败、日志损坏或持久性未知。因此当前预期缺少成立条件，会把能正确查回提交的实现误判为失败。

修复要求：将进程退出与持久性／读取未知分开冻结。前者恢复读取应确认已提交，后者明确注入故障再期望 unknown；两者都不得重复业务动作。修改原预期须升级 fixture 版本并保留 v1。

### E0-R2 · P1 · 标签齐全不等于计划要求全部落盘

主计划第 544 行要求 TS／规则门禁／独立验收的 **8 种组合**，每个受支持组合包含正确放行、错误拒绝、检查后变化；第 755、788 行要求真实旧包迁移的活动／退出未知／旧版重启／直接 API／合法迁移／重复请求路径。

147 个变体中仅有单独 `truth_sources_enabled=false` 及泛化的旧任务对照，没有这些三开关组合和迁移情境的具体登记。共享 ready-state 也未提供相应配置。校验器只比较 49 个目录标签的集合，因此原先所说的“覆盖全部标签”成立，**“覆盖所有已批准验证要求”不成立**。

修复要求：在原需求归属下补紧凑的组合／迁移表及可消费输入，绑定既有完整旧包指纹，明确各批次测试方法；不对全部宿主和全部故障做笛卡尔积，不在 E0 实际执行迁移或模型调用。缺行必须有确定性失败断言。

### E0-R3 · P2 · 日志预算被借作 flush 工件预算

**E0-017** 对 `mandatory_bytes=8388609` 预期 prepare 在写入时阻断，但冻结预算的 8 MiB 是 **event log read/parse/rebuild** 上限；budget-profile 的 scope 明确不是完整 handoff。该案例没有声明独立的 flush/packet 预算。

修复要求：日志预算在日志读取边界测试；若验证 flush 的必需项超限，应显式注入该测试的 packet 预算及计量单位，并标为合成测试参数，不能悄悄把日志数值变成产品默认值。保持不截断必需证据的约束。

### E0-R4 · P2 · 承重合同版本空串未被 schema 拒绝

`interface.schema.json` 的 `contract_version` 只限制 number/string，未限制空字符串。隔离副本中同时将 ready.record 与 prepare.request.record 的版本置为 `""`，`validate_bundle()` 只返回 **E0_HASH**，没有 schema 或语义错误。

这不意味着篡改当前已钉住的包能绕过哈希检查；它说明一个带空合同版本的**重新封印包**仍缺少独立的字段校验。主计划第 842 行明确要求拒绝必需字段空值。

修复要求：保留既有 number/string 兼容性，对字符串拒绝空值，并给出对应公共入口反例；不能用更新 manifest 替代这项语义校验。

## 现场复核证据

- E0 旧测试重新运行：**23/23，1.187 秒**；全部通过，却未发现上述规格缺口。这是测试覆盖不足，不是新产品失败或安全策略需要放宽。
- E0 manifest 仍为 `6ad1c9b350180ac73155779d047541b22abae257f411dc8da48a846c9c318710`。
- 校验器／测试程序仍为 `0e8a02d5073b31829bcde7f066029fa232121442572365499206b6fd9f025056`／`a8c628970e1016f93c524471bb33fb2eb84ffb52eac579a3a2594b62d3d50050`。
- 本轮不改代码、schema、fixture 或 manifest，只记录审核结论并修正计划状态。之前的 387 项完整回归是 v0.20 的历史证据，本轮未重跑、也不冒充收口语义证明。

空版本探针复跑（仅现有测试辅助函数操作临时副本）：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 - <<'PY'
from test_handoff_spec import HandoffSpecTests
def change(b):
    b['record']['contract_version'] = ''
    b['requests']['prepare_handoff']['record']['contract_version'] = ''
print(HandoffSpecTests().mutated('ready-state.json', change))
PY
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_handoff_spec -q
```

## 收口边界

先修 E0-R1 至 R4，保存旧版、冻结新版期望与来源，运行针对性反例／必要回归，再复审。四项均落实已批准需求，不需要重开全部 CEO 设计；不借修复启动 E1 产品实现、安装、发布或付费评估。真实宿主、模型、自然使用与 token 收益仍未验证。
