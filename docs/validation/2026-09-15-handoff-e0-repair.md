# E0-R1 至 R4 修复与复审

本轮授权：用户“按你的建议继续”；仅修四项 E0 缺口，不进入产品实现。

## 实施前冻结的验收

1. v1 的 9 个包文件、校验器及测试程序保存至 `archive/handoff-e0-v1/tests/`，原 manifest 指纹可复核，旧结果保留；新版本使用 fixture_version 2。
2. R1：只在核实持久性／读取未知时预期提交未知；已 fsync、恢复可读的进程退出应确认已提交，且不重试业务。
3. R2：三开关 8 组合分别登记正确放行／错误拒绝／检查后变化；6 类旧包迁移路径单独登记，绑定真实旧包 manifest 指纹，补漏行反例。只冻结合成输入和未来观测，不运行宿主或迁移。
4. R3：日志预算只测日志读取；flush 使用显式合成 packet 字节预算，不能成为默认生产限制；分别有反例。
5. R4：保留 number/string 类型兼容；空字符串或仅空白的合同版本返回字段错误，不能依赖整包 hash 报错。
6. 公共测试 seam 沿用 validate_bundle(path)／CLI。每项先观察行为 red 再 green；最终跑针对性测试与必要回归。最终复核四项内容与新指纹，未验证产品能力仍为 NOT_RUN。

## 执行记录

修复和本地复审已完成，四项通过；E1 产品实现仍未授权。

| 项目 | 修正与反向验证 | 复审结论 |
|---|---|---|
| R1 | E0-030 修正为可确认的已提交；E0-044～049 保留独立读取／持久性未知；重新写回错误 unknown 预期会报 E0_EXPECTATION | 通过，仅规格层 |
| R2 | E0-148～171 为 8×3 配置输入；E0-172～177 为 6 类迁移，绑定旧包 manifest；逐一删除任一新增行会报 E0_COVERAGE | 通过，仅输入完整性 |
| R3 | flush 明确 64／65 UTF-8 字节合成限额；E0-178～180 单独测日志 8 MiB 前／等于／超过；借用日志预算会报 E0_BUDGET | 通过，不新增生产默认值 |
| R4 | schema 拒绝空串，字段检查拒绝全空白；number 1／1.5 与非空字符串 1／release-1 仍通过 | 通过，不收窄原版本类型 |

增加 33 个变体后总数 180，ID 唯一；49 个原目录标签保留，不把标签或变体数冒充实际产品验证次数。所有变体仍为 NOT_RUN。

## 本地验证结果

- 新 E0 测试 **32/32，2.740 秒**；完整回归 **396/396，29.542 秒**，无失败／错误／skip。相较 364 个旧测试，当前 E0 有 32 个测试方法。
- 33 行增量矩阵分别移除后均被拦截；四类错误在临时副本中重新计算 manifest 后仍报对应语义错误且不含 E0_HASH。证明拒绝并非只由整包字节变化触发，仍不宣称一般性防篡改。
- 按测试实际调用统计：无效规格输入错误放行 **0/97**（原 54＋6 单项修复反例＋33 单行移除＋4 重新封印反例）；有效规格错误阻塞 **0/26**（原 22 次＋4 个合法版本值）。重复调用不是独立任务或模型稳定性证据。
- 新版 CLI 单次实测 **0.026203667 秒**，不是 P95／SLO；内存和会话 token 归因未知，不宣称节省。无新外部模型调用或业务重试。
- 旧 v1 全部 11 个归档文件保留：旧 manifest 验证通过，归档的两份程序 SHA 与修复前一致；旧套件另行复跑 **23/23**。历史缺口和旧结果保留，不把 v1 重新解释为已修复。
- Strict/Lite check-source 分别检查 45／11 个文件通过；真实旧 Strict 0.7.0 包 verify 通过（45 文件、16 导出），不是迁移测试通过。
- 产品核心 SHA 未变，Git HEAD 仍为 `0f5898e19b4951c661edce1f7db80f95cc1b2ecc`；原 7 项用户文件指纹未变，无提交、安装或部署。

本轮按 TDD 保留了 [6 组实际 red→green 输出](2026-09-15-handoff-e0-repair-runs.json)。中间整套回归曾发现旧 JSON 重复键测试写死 v1，导致 v2 没有注入重复键；现从实际版本构造重复键并先断言替换目标存在，保留原拒绝要求，不删除测试洗绿。

## 版本身份与复跑

| 对象 | SHA-256 |
|---|---|
| v1 manifest（归档） | `6ad1c9b350180ac73155779d047541b22abae257f411dc8da48a846c9c318710` |
| v2 manifest | `435e407c064b32a7d5012e0161c9b2e7bddc38c8d70ce42e12659102e7f52a7b` |
| v2 校验器 | `eb0b07f1f5334ae8d9654a6452e32ac4499ec256214f5684ea89b392ce90cb63` |
| v2 测试程序 | `35502ca6f075ca66bf01f226ff3346b13491fc90504efe4258b8a70d2ddae8f5` |
| 真实旧 Strict 包 manifest | `3d3e4f44b454adaa358d69c4e75eec4bbaa2ecedcb5d84abfdc6b34e33e50cc7` |

```bash
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 tests/handoff_spec.py tests/fixtures/handoff --expected-manifest-sha256 435e407c064b32a7d5012e0161c9b2e7bddc38c8d70ce42e12659102e7f52a7b
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_handoff_spec -v
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /opt/homebrew/bin/python3.12 -m unittest discover -s tests -q
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 docs/validation/archive/handoff-e0-v1/tests/handoff_spec.py docs/validation/archive/handoff-e0-v1/tests/fixtures/handoff --expected-manifest-sha256 6ad1c9b350180ac73155779d047541b22abae257f411dc8da48a846c9c318710
```

v1 测试程序与包均按原布局保存，可用 `PYTHONPATH=docs/validation/archive/handoff-e0-v1/tests` 单独复跑其测试。真实旧包本轮在 `/private/tmp/mltc-review-baseline.GYDdVc/context-strict` 复核；这个临时路径不承诺永久存在。后续迁移验收若包不可用，需从钉住的 Git 基线重建并匹配完整 manifest，否则不得用新版 mock 替代。

## 收口与未验证项

主控按发现、输入、反例和归档指纹逐项复审，E0-R1 至 R4 在**测试准备范围**内关闭。未调用独立 Agent／外部模型，不冒充独立身份验收。

方案及工程输入审核可以收口；这不是产品交接通过。180 个场景需由后续真实实现／适配器产生实际观测，不能由 expected 值拼结果；真实宿主、迁移、冷启动、并发崩溃、业务完成与自然项目效果均未运行。包标识、合成回执和静态表不能产生身份或授权。

下一步仅在 E1 获授权后按冻结工单做产品实现与验证，不重开 CEO 全案，不自动安装、提交或发布。
