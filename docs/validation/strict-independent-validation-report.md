# Context Strict 独立验收门禁：本地验证报告

日期：2026-09-11。状态：本地修补、独立复审、哈希保护集成和集成后验证完成；未安装或提交。
原则：保持有效，尽量经济、精致；不以省 Token 为由削弱门禁。

## 边界与基线

- Git 基线：`main` / `3e954ebaf484f79dffd897079bdee012529dd9a3`，开始时已有多轮未提交工作；全部保留。
- 使用 `.scratch/strict-independent-validation-20260911/baseline` 封存完整脏源码，
  在同目录 `work` 隔离副本开发，差异相对这份基线，不把既有改动算成本轮成果。
- 基线源码包 0.7.0：manifest `cad1898e79d159a29754e59ddc7857066b0a197a21afe2f18832ea7715951db3`，
  tree `99b85da1e95f016632aa4e11ed5ddd143057b223cdc76d2323910fce93b1d5c2`。
- 只修 public `publish_contract` / `bind` / `gate(completion)` 的独立验收边界及其分发说明。
  没有新增身份服务、调度器、CLI 或生产宿主适配器。
- 不全局安装、不修改生产项目状态、不提交、合并、推送或部署；没有付费模型评测。

## 实际调用链与升级

1. 可信宿主通过 `bind` 捕获 `independent_validation_required` 和 `validation_resolver`。
2. `publish_contract` 在写入前检查要求，拒绝不符合宿主策略的合同；已有 true 验收项
   不能在普通版本更新中悄悄 false、遗漏或删除。显式宿主授权降级仍需原有发布授权及高版本。
3. 模型的 `evidence_map` 只提供 `validation_ref` 等候选数据，不能提供可信 callable 或自证身份。
4. `gate(completion)` 继续经过既有合同、审计、证据内容、Truth Sources、规则及审批门禁；
   宿主 resolver 每必需项最多调用一次，核对 canonical principal、实际 run/checker、
   task/criterion/合同摘要/工作区/证据摘要/源码版本和 UTC 时效。
   独立合同必须显式给出有效绝对工作区；缺失/无效时返回 unknown，不回退 cwd，也不调用宿主。
5. 完成前复核文件、合同、相关上下文和回执时效；保留原 Truth Sources 锁定判定语义。
   回调期间失效的证据不能继续通过；后续读取失败不能覆盖已知业务 `fail`。
6. 返回只读结果。全部通过才 `passed=true`；`fail` 与 `unknown` 都阻断。
   门禁自身不写完成状态，不授权外部业务动作，也不会自动重试 resolver。

独立回执 `assurance=verified` 只说明该层核验通过，不能覆盖语义检查的 fail。
没有要求独立验收的低风险合同保留旧行为；现代 evidence-handlers 报告为 `not_required`，
旧式非独立报告保留原形状。原来 true 的合同若只有名字/自报时间、没有可信宿主 resolver，
现在会阻断，这是明确的兼容性收紧。

信任边界：同进程 Python 宿主代码被信任。本库无法认证任意调用者，也不能阻止能改源码的人
替换检查器。当前没有验证过可用于 Codex/Claude 的真实宿主身份适配器；缺失证明保持 unknown。

## 冻结案例与验证记录

验收先于执行冻结于 [规格](../specs/strict-independent-validation.md)，包含 IV01–IV22 所有列明变体；
审查中实证的回归在 [审查反例](strict-independent-validation-review-cases.md) 中补充并先跑 RED。
所有新宿主回执均为明确标记的合成案例，文件内容实际读取，未重放业务动作。

核心验收工件位于 `.superpowers/sdd/strict-independent-validation/`：

- `fix-4-rereview.md`：独立审核 Spec PASS / Quality PASS。
- `controller-fix4-public.json`：13 个公共测试方法及 IV/CR 子例通过。
- `controller-task1-regression.json`：既有 context/truth/completion/evidence/feedback/rule 共 252 项通过。
- `controller-full-isolated-main-guard.json`：全部 360 项通过，0 skip，27.281 秒。
- `controller-full-final-fixed.json`：最终修补后全部 363 项通过，0 skip，26.437 秒。
- `controller-post-final-fix-public.json`：最终公共测试 16/16 通过，包含 FR01–FR05 变体。
- `final-rereview.md`：FR01–FR07 最终定向 Spec PASS / Quality PASS，两项 Important 关闭。
  SHA256 `c82b1ff281f760ba5d08ea63ba5a772e5ac9bb130359d8dd02e138079a6630f0`。
- `controller-full-integrated.json`：集成后原工作区 363/363 通过，0 skip，26.403 秒。
- `controller-historical-integrated.json`：集成后原工作区另跑历史 Git 兼容 1/1 通过，0.146 秒。
  合计 364 个不同测试方法；公共 16 个已包含在 363 中，不重复加总。
- `controller-integrated-identity.json`：16 个集成文件哈希、Strict 45 个包文件、Lite 11 个未变文件、
  冻结规格、最终复审报告、Git 分支与 HEAD 全部实测一致。
- `controller-final-probes.json`：初始未观察真相源、回调冲突、entry 自验、输出与结果一致性全部符合预期。
- `controller-final-time-probes.json`：回调途中回执到期阻断；回调途中生成的当前回执允许。
- `baseline-historical-original-checkout.json`：历史版本 Git 兼容用例在原仓库单独通过。
  隔离副本不能正确提供该 Git 历史位置，因此完整副本回归显式排除此 1 项，并引用独立原仓库结果。

期间曾出现真实错误放行、并发错误阻塞和报告状态不一致，均先退回修复再验收。
早期代理报告不能替代当前文件和运行日志；保留 RED 与修正记录，不覆盖失败历史。
全量首次运行的临时 runner 缺少 `__main__` 保护，macOS spawn 子进程重新运行整套测试，
出现 10 项锁时限失败并超时。仅修正 runner 入口后上述 360 项通过；未修改产品测试预期。
失败日志 `controller-full-isolated.json` 与原 runner `full-suite-before-main-guard.py` 均保留。

## 最终 Strict 包与文字成本

- 当前候选：`.scratch/strict-independent-validation-20260911/final-reviewed-strict`，未发布 `0.7.0`。
- Manifest：`7129fe28a04e6a010623fca82a1967cbd05ceff077f751c4dfe34751dcd525a3`。
- Tree：`4d1ded220b2af13d753f029d3cb3251eb9aebf76310411f00fc63b73c3138bb9`。
- 主控整包 verify：45 文件、10 文档路径、16 API exports 全通过。
- 当前包外进程公共测试 16/16，包内示例的 valid / unknown-ref / no-resolver 三分支通过。
  主控独立复跑记录为 `controller-final-package-tests.json`、`controller-final-package-example.json`。
  早先 `task2-strict-package` 和 `task2-strict-package-final` 均保留但已被替代，不能用于最终验收。
- SKILL 正文净增 356 字符、50 个英文词（不是 Token 计量）；详细格式按需读取。
  Lite 完整 payload 逐字节未变。没有以减少文字为由移除硬约束。
- 已安装全局 Strict 仍为 0.6.0，主控按原 manifest hash 复验通过：
  `cbb8b1beff19e5a58c095c947d4bf1713a528b8a25082e019a015bd867d9f92f`。

整体审核实证的问题已修补：没有有效合同工作区时不能退回当前进程目录，而是 unknown 且
不调用宿主 resolver；合法绝对路径规范化继续允许。损坏 criteria 加 resolver 时保留既有
阻断诊断，不抛 TypeError。`final-review.md` 保存原始复现与 FR01–FR07 冻结修复验收，
`final-fix-report.md` 保存 RED/GREEN 和新包身份；`final-rereview.md` 已通过最终定向复审。
旧包和它的绿测量不能代替当前验收。下表的 10 案例机制对照不包含新增 FR 反例；FR 单列验证。

## 效果与成本：只报告本地机制

[机制对照案例](strict-independent-validation-mechanism-cases.md) 在测量前冻结。
同样的模型形状输入、10 个定向合成案例，每个版本各重复 5 次；基线不支持新宿主接口。
这不是随机生产样本，也不是一次真实模型对照实验。

| 指标 | 脏源码基线 | 最终核心候选 |
|---|---:|---:|
| 错误放行（应阻断执行） | 40/40，涉及 8/8 案例 | 0/40，涉及 0/8 案例 |
| 错误阻塞（应允许执行） | 0/10，涉及 0/2 案例 | 0/10，涉及 0/2 案例 |
| 相同输入重复判定一致 | 10/10 案例 | 10/10 案例 |
| 重复门禁前后任务文件字节不变 | 是 | 是 |
| IV01 有效独立验收 gate 中位耗时 | 2.142 ms | 2.564 ms |
| IV18 不要求独立验收 gate 中位耗时 | 2.187 ms | 2.096 ms |
| 50 次显式请求总 gate 时间 | 110.205 ms | 82.602 ms |
| 宿主 resolver 调用数 | 0（无此接口） | 35，单必需项每次请求至多 1 次 |
| 自动重试 / 业务动作 | 0 / 0 | 0 / 0 |

候选包含更早阻断且有并发本地测试，不能用总耗时之差宣称性能或 Token 收益。
原始逐次结果：`mechanism-baseline.json`、`mechanism-final.json`。
较早的 `mechanism-candidate.json` 保留为修补前历史，不用它替代当前候选结果。
模型原始判断、输入/缓存输入/输出 Token、付费金额、真实模型稳定性、自然项目效果均为未知。
确定性重复只证明机制一致，不能冒充模型稳定性证据。
开发过程另计：Task1 经 4 轮局部退回修复，最终整体审核再触发 1 轮范围内修复；
这不属于门禁的自动重试，但确实产生开发时间与模型调用成本。没有可归因的账单数据，
不能声称本轮多 Agent 开发比单 Agent 更省 Token。

## 复跑

从仓库根目录执行（全部仅临时合成状态）：

```sh
env PYTHONPATH="$PWD/src:$PWD/tests" /opt/homebrew/bin/python3.12 -m unittest test_independent_validation test_context test_truth_sources test_completion_upgrade test_evidence test_production_feedback test_rule_execution
/opt/homebrew/bin/python3.12 scripts/skill_package.py check-source --source skills/context-strict
/opt/homebrew/bin/python3.12 .superpowers/sdd/strict-independent-validation/full_suite.py --root "$PWD"
env PYTHONPATH="$PWD/src" /opt/homebrew/bin/python3.12 tests/test_experience_distribution.py ExperienceDistributionTests.test_historical_strict_package_rejects_rule_execution_capability -q
/opt/homebrew/bin/python3.12 .superpowers/sdd/strict-independent-validation/integration_final_check.py
```

完整对照/进程参数与工作目录保存在上述 JSON 的 argv/cwd 字段；机制脚本接受 `--source`
和 `--output`。完整包需要在源码目录以外的进程复跑，以排除源码遮蔽。
通用 skill-creator `quick_validate.py` 因两个本机 Python 均缺 PyYAML 未能运行；
没有为此安装依赖，也不把这项标绿。仓库自身源码/完整包校验是主要分发验收。

## 是否扩大应用

本地机制值得保留，但不能据此直接宣称生产独立验收可靠或全局推广。
后续先接入可核实的真实宿主回执并做小范围自然任务验证；没有宿主证明时应继续阻断，
不能用代理自己填写另一名字恢复放行。生命周期、恢复 CLI、路由及 Token 试验不在本轮。

主工作区已集成通过最终审核的 9 个维护文件和 7 个 Strict 镜像文件。
每个写入前核对旧内容与冻结基线相同，写后核对新内容与候选哈希相同，未覆盖别的脏改动。
本轮实际运行时 diff 为 `__init__.py` +382/-51 行（净增 331 行）；新公共测试 760 行。
这是单一门禁的有界修补，不是几行提示词优化；多数新增文字放在按需参考与可运行例子中。
可审查的完整基线/候选留在隔离目录，逐文件前后 SHA 见 `integration-plan.json`。
Git 仍是同一 `main` / HEAD；这表示直接保留在本地未提交工作区，不表示执行了合并或提交。

本轮使用 Context Strict 冻结/保存任务依据，TDD 与 subagent-driven-development 做前置正反例、
Terra-high 执行和独立审核；skill-creator 约束主正文增量与按需加载；收尾技能要求集成后再验证。
本项目跟踪仅记为 `local-validated`，不伪造宿主回执来取得自身的正式完成门禁通过。
真实宿主适配、标准合同体系、生命周期 CLI、自动恢复和付费评测均未顺手扩展。
