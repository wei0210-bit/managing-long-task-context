# E4–E6 本地集成验收

状态：LOCAL_ACCEPTED_WITH_HOST_LIMITS（2026-09-15）。剩余可行的本地开发与验证完成，E4 真实原生宿主接管 BLOCKED、E7 条件未触发。这是本轮唯一汇总报告；先前局部通过不能替代最终结论。

## 范围与实际交付

源工作区：`/Users/zhaowei/Desktop/David/project.nosync/managing-long-task-context/.worktrees/short-session-remaining`，分支 `codex/short-session-remaining`。
基线为 HEAD `0f5898e19b4951c661edce1f7db80f95cc1b2ecc` 加原 main 中 E1–E3 未提交文件快照，不是仅此 Git 提交。
原 main 保留 E1–E3；本轮不合并、不提交、不安装、不推送、不部署、不运行真实付费宿主任务。

- E4：新增 Codex/Claude native capability 报告及控制拒绝入口，纳入运行身份和完整包。可用证据只是当前接口快照，带日期和适用范围；缺少可信身份、fencing、干净会话和跨主控证据，真实原生接管仍 BLOCKED。
- E5：Lite `flush → _write` 复用原子 NOW 写入；`cold-check → identity-bound resume → bounded original bytes/material` 返回接续材料与原件指纹。未证明模型语义理解、无聊天继承或真实接管；不允许自动归档。Lite 版本 1.4.0，Strict 候选 0.8.0。
- E6：两包复用单一 `scripts/context_usage.py`。`summarize_usage` 仅核对调用方提供的计量；`evaluate_pressure` 给有界、去重、安全点建议，不执行宿主/业务动作。缺量仅在全部关联、时间、安全字段有效的显式安全里程碑降级；累计口径不能冒充当前窗口。费用和收益无实测则 null。
- E7：既有 25 次代表性探针均未触发预算阈值，保留条件后置，不增加索引框架。依据 [触发评估](e7-trigger-assessment.md)。

## 冻结验收与修复审计

冻结依据：[集成合同](e4-e6-integration-contract.md)、[最终修复合同](e4-e6-final-fix-contract.md)。实现记录见 [执行报告](e4-e6-final-fix-report.md)。合成输入，不重复业务动作。

整批独立审核发现 0 Critical / 4 Important，另有 F5 计划澄清。首次集中修复的 42/42 及中间全回归 549/549（61.467 秒）仍不能验收：F1 错测 cold-check，未覆盖原 unchanged flush；F5 未排除 `basis=cumulative` + 缺量组合。主控拒绝关闭并要求原合同内补齐，不修改预期。

| 项目 | 冻结预期 | 最终状态 |
| --- | --- | --- |
| F1 unchanged flush 两读间原件变化 | 不混合 A 的目标/状态与 B 的指纹；unknown，无成功指纹；保留 CRLF 和 mtime | ADDRESSED，原 `_flush` 两种磁盘替换反例及 CRLF 正例独立复核 |
| F2 首次到期里程碑提醒 | 原来 defer 未通知，首次到期通知；随后 20 次不通知，通知记忆不丢失 | 独立限定复审 ADDRESSED |
| F3 UTC 换算上下界溢出 | usage、pressure、直接 now 和 CLI 均 unknown；合法时区仍可用 | 独立限定复审 ADDRESSED |
| F4 完整包旧 validator | 原断言不变，源码/包根均可执行；同步、清单、CI 一致 | ADDRESSED；最终 Lite 包外 43/43 含原 validator |
| F5 缺量里程碑降级 | 缺安全/关联/时间不得建议，累计口径不得降级，完成/执行未知不触发轮换 | ADDRESSED；5 类非法 basis 拒绝，2 类有效 basis 缺量/None 连续 21 次仅首次提示 |

旧 67/16 文件候选 `/private/tmp/mltc-remaining-controller.hDcO2Z/context-strict`、`context-lite` 已暂缓，不是最终可验收包。原日志 `e4-e6-first-*.log` 和 `e4-e6-intermediate-regression.log` 保留，不覆盖历史。

## 最终复跑

稳定源码同步后，以下全部实际退出 0。实现者 Terra-high；主控集成及独立 Astra-high 整批/限定复审。不以代理自报作为验收。

| 验证 | 实际结果 | 耗时 |
| --- | --- | --- |
| 根针对性 validator + handoff + usage | 43/43 | 5.527 秒 |
| 主控 F1/F5 原入口独立探针 | 2/2 方法，含多组合 | 0.004 秒 |
| 主控 E6 独立探针 | 13/13 | 0.001 秒 |
| 最终全部发现回归 | 550/550，0 skip，0 ResourceWarning | 62.376 秒 |
| 源码树外 Strict 包 | 62/62，0 skip，0 ResourceWarning | 13.460 秒 |
| 源码树外 Lite 包，含原 validator | 43/43，0 skip，0 ResourceWarning | 5.765 秒 |
| 两包 source-check/build/verify/full doctor | 全部 pass；doctor 的 task binding 为 not_run，因为仅验证包 | 仅记录结果，不虚构独立耗时 |

这些套件有重叠，不将次数加总成独立案例数。原始输出：[全回归](e4-e6-final-regression.log)、[Strict 包外](e4-e6-final-strict-package.log)、[Lite 包外](e4-e6-final-lite-package.log)。主控 F1/F5 探针首次误用 `status`（实际键 `decision`）属于夹具错误，不算产品红；纠正后捕获非法 basis 4 个失败，修补后绿色。

在上述源工作区复跑：

```sh
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 scripts/sync_context_strict_skill.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_context_lite_validator test_context_lite_handoff test_context_usage -q
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 docs/validation/e4_e6_final_controller_probes.py -q
PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 docs/validation/e6_controller_probes.py -q
MLTC_LEGACY_PACKAGE=/private/tmp/mltc-review-baseline.GYDdVc/context-strict PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /opt/homebrew/bin/python3.12 -W always::ResourceWarning -m unittest discover -s tests -q
```

显式旧包缺失时不得省略变量假装旧包路径已测，应按 E0 基线重建或记 NOT_RUN。包构建用 `scripts/skill_package.py check-source --source skills/<skill>` 和 `build --source skills/<skill> --destination <新空路径> --source-revision <下表来源>`，随后 `verify --package <路径> --expected-manifest-sha256 <下表指纹> --expected-source-revision <下表来源>`。

| 完整候选 | Strict | Lite |
| --- | --- | --- |
| 版本/文件数 | 0.8.0 / 67 | 1.4.0 / 17 |
| source_revision | candidate:dirty-worktree-0.8.0-E4-E6-final | candidate:dirty-worktree-1.4.0-E4-E6-final |
| manifest SHA-256 | a6dd801dd5595c75d02f2b7ebd44f128fbf3150950cd53075a88dac47309b18c | 23ba12cd500f7247317d898e2fbf720be068bec2d854c3f0eedb6e792bfce62f |
| source_tree SHA-256 | ae8fff77bb64eea4f7e278212f86701dc54b43f1e140a638b40bb5f9b90e5f62 | 1e595ffd590408e776f9a455b32ce409cf2225fb0ca37f2b162b164120019ec7 |

当前包路径为 `/private/tmp/mltc-remaining-controller.hDcO2Z/context-strict-final`、`context-lite-final`；临时文件可能清理，长期保存的 [Strict manifest](e4-e6-strict-manifest.json)、[Lite manifest](e4-e6-lite-manifest.json) 用于重建核验，不代表全局安装身份。
源码树外以 `/private/tmp` 为 cwd，设置 `PYTHONPATH=<Strict包>/src:<Strict包>/tests`，实际运行 `python -W always::ResourceWarning -m unittest test_handoff_codex_cli test_handoff_host_records test_handoff_codex_native test_handoff_claude_native test_context_usage -q`；Lite 设置 `<Lite包>/scripts:<Lite包>/tests`，模块为 `test_context_lite_validator test_context_lite_handoff test_context_usage`。每包执行 `<包>/scripts/context_doctor.py check --mode full --package-root <包>`。

## 成本与范围核对

最终计量工具 SHA-256 `fffdfd4617f682de89e430714c2c339d3412b21be300892c4edefe58972f8de4`。3 个全新 Python 进程，各聚合 1000 条合成 usage：0.005786–0.005927 秒；各判断 pressure 20 次：0.000300–0.000321 秒，每轮通知 1 次。整个 Python 进程 RSS 峰值 25,346,048–25,411,584 字节，不是 Skill 增量内存。时间不含启动和输入构造；三轮非完整交接耗时。原始结果：[最终计量](e6-final-measurement.jsonl)。未建立前后对照，不能据此宣称优化收益。

核心 `__init__.py` 相对 E3 原工作区仅增加两个 native import 和两个 runtime identity 路径，4 行；handoff/CLI/records 原实现指纹均保持 E3 值。新行为主要在独立模块和按需说明，不把全部实现注入 SKILL 正文。五项原用户文件及 E0 manifest 指纹不变；两份使用观察文档仅追加 10/7 行，无旧记录覆盖。`git diff --check` 通过。包内重复文件由既有同步器维护，不是手工维护第二份实现。

## 尚未验证与扩大使用条件

机制测试、真实模型离线对照、自然项目使用分开：后两类本轮未运行，真实模型稳定性、token 节省、缓存费用、生产可靠性均 UNKNOWN。程序重复只证明给定输入的确定性。
E4 尚需可信宿主接口证据及真实路径测试，不建议扩大自动接管。E5/E6 即使本地验收通过，也只具备候选进入隔离试用的条件，不等于已全局加载。
远程 CI 未运行；远程工单因内部计划上传被权限审查拒绝，未重试或绕过，本地合同完整保留。

## 主控裁决与代价

1. 隔离分支叠加现有未提交源码，避免覆盖用户工作；若基线漂移须重新核对，不能只看 HEAD。
2. 无提交授权，按冻结文件差异审核并保留派单记录；代价是额外指纹核对，不能用提交区间省略证据。
3. 原生宿主未知能力保持关闭；代价是暂时不能自动接管，而不是以模型自报伪造能力。
4. 远程上传受阻后用本地工单继续；代价是远程看板未同步，需要单独数据发送授权。
5. 缺量但安全里程碑采用受限提醒；代价是少量降级分支及一次提示，不能产生控制或业务权限。
