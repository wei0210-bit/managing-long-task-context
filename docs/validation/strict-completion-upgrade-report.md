# Strict 完成判定最小升级：本地验证报告

日期：2026-09-10。状态：**所选入口机制验证通过；完整历史兼容回归仍有 1 项未验证；真实模型/自然使用未运行。**

## 1. 仓库与包身份

工作目录 `/Users/zhaowei/Desktop/David/project/managing-long-task-context`，分支 `main`，
HEAD `3e954ebaf484f79dffd897079bdee012529dd9a3`。本轮开始前已经有经验/规则、分发、Lite 等未提交修改及带 ` 2` 的文件，全部保留。
基线不是干净 HEAD，而是本轮前的完整 dirty 根源码包；用 manifest 绑定，避免覆盖前轮工作。

| 包 | 版本 | 完整 manifest SHA-256 |
| --- | --- | --- |
| 冻结 dirty 根源码基线 | 0.7.0 | `76354ab7dc6affb8c6f04c099c7aa35e3ef6180bd1eeaf418b9380171c3e1e58` |
| 最终根源码包 | 0.7.0 | `d75b66e7b1c4d2f014dc7cb424528ba375c3e2c1d8aee15dffdb66611977095d` |
| 最终 Context Strict 分发包 | 0.7.0 | `96dc85092f61d0cfd1bd3f77335427e3b3267a2247725997c906a8d4c02d3ab0` |
| 本轮读取的全局安装包，未修改 | 0.6.0 | `cbb8b1beff19e5a58c095c947d4bf1713a528b8a25082e019a015bd867d9f92f` |

均执行过完整包验证。初次 Strict 源码目录检查读取超时；随后源码检查与完整构建/验证成功，不能把最初超时记为 pass。
本轮不发布版本，候选仍为未发布的 0.7.0；评估/安装必须绑定完整 manifest，不能只比较版本号。

所有本轮原始工件位于 `.scratch/strict-completion-upgrade-20260910/`，目录未跟踪，尚未提交或分发。

## 2. 实际入口和调用链

公共入口：`src/managing_long_task_context/__init__.py` 的 `gate()`，或 `bind(...).gate()`。
实际宿主接法：`examples/strict_completion.py` 的 `run_example()` / `make_file_claim_verifier(workspace)`。

```text
模型提出 evidence_map（其中 status/pass/checker_result 不可信）
  → 宿主绑定 workspace 和实际 verifier callable
  → gate(stage="completion") 冻结输入
  → 原有合同、审批、证据 handler、上下文/Truth Sources/规则检查
  → 每个 AC：resolver 读取原件、核对完整性/时效/范围
  → 宿主 verifier 实际读取内容；声明 required_revision 时实际读取 Git HEAD
  → 所有回调结束后，重新解析通过的 file 证据，并复查合同
  → decision + passed + 每项检查/原因；只有全 pass 且无既有门禁错误才放行
```

**没有完成状态写入。** `gate()` 是只读判定，不能把结果当后续部署/支付/发布授权。
失败不会写“已完成”；重复 gate 不改变合同、事件、快照，也不重试 verifier 或业务动作。
任何调用者若另行写状态，仍须在它自己的受控、幂等写入入口接 gate；本轮没有新增该外部接口。

历史线索 `.scratch/verified-experience/complete_context.py` 确实经 `ctx.gate(stage='completion')`
检查 root receipt，然后写判定报告；不是一段模型文字直接改完成状态。
本轮读取了其 receipt，SHA-256 为 `da9f6aceb45d1e2f265e8ba6d4928c3f1a7c896272f6b02b86784f3efa55f37d`，
其中有 10 个检查名。但没有重跑历史业务、逐条重验历史日志或再次关闭该任务，不能据此补记历史验收通过。

## 3. 具体缺口与最小修改

1. **宿主语义缺口**：原官方 verifier 只比较 scope。向其交付更强的内容验收条件时，正确 hash 的无关正文和明确失败正文仍被接受。
   改成由可信宿主绑定的内容检查器，读取文件原件，不读模型填的检查结论；真实 HEAD 不符为 unknown。
   原示例自己的合同只要求存在/hash，本轮也将示例合同明确为精确内容要求；不是声称旧示例违反了它原本较弱的合同。
2. **判定期间证据变化**：普通文件原先只在 verifier 之前解析；同一 verifier、后一个 AC 或规则回调可以使先前证据失效。
   在所有回调后加 file 尾检，不重跑语义 verifier；检查失败返回 unknown 并阻断。
3. **合同绑定和三态诊断**：提供的 contract_version 必须是整数且与封印版本一致；新示例还在 required_scope 绑定合同版本。
   缺失、过期、digest/revision/scope 不符归 unknown；明确内容反证仍 fail。保留原始检查码与 raw_status，不放宽 passed 条件。
4. 新诊断字段只加到启用 `evidence-handlers/v1` 的合同，保留旧版公共报告 hash 基线。
   每项附 AC ID、合同版本、workspace、证据引用/版本/scope、实际检查结果和尾检原因。

根源码增量 7 个文件，353 行新增、22 行删除，主要为 196 行测试；Strict 另有 5 份生成副本。
实现变化集中在完成链路和官方示例，未重写 resolver、审批、Truth Sources 或经验框架。
完整增量（相对本轮开始的 dirty 源码，而非 main）：`.scratch/strict-completion-upgrade-20260910/upgrade-only.diff`。
既有未提交 payload 中，本轮以外文件 hash 未变化，见 `incremental-integrity.json`。

兼容性影响：依赖 `passed` 的调用者仍按相同字段阻断；把某些证据不可用错误硬编码为 fail 的调用者应兼容 unknown。
对应 3 个旧核心测试只调整了该三态预期，保留阻断及原因码断言。示例的独立 verifier 改为工厂绑定，不能继续照搬旧弱校验回调。

## 4. 冻结案例与结果

先冻结 `strict-completion-upgrade-contract.md` 的 19 项，后在执行前补充 C20 实际 HEAD 反证。
gold 未根据测试结果改写。C04 注入路径修正、统一观察时间的计量修正见 `strict-completion-upgrade-addendum.md`。
全部新案例都是**合成、隔离、确定性**案例；历史材料只帮助定位接口，不冒充新的自然项目样本。

| ID | 场景 | 预期 | 基线 | 候选 |
| --- | --- | --- | --- | --- |
| C01 | 齐全且内容通过 | pass | pass | pass |
| C02 | 必需 AC 遗漏 | unknown | unknown | unknown |
| C03 | 证据不存在 | unknown | fail | unknown |
| C04 | 不可读 | unknown | unknown | unknown |
| C05 | 过期 | unknown | fail | unknown |
| C06 | 合同版本不符 | unknown | pass | unknown |
| C07 | 产物 revision 不符 | unknown | fail | unknown |
| C08 | 工作区不符 | unknown | fail | unknown |
| C09 | 已记录但未解决的冲突 | unknown | unknown | unknown |
| C10 | 执行者自报完成 | unknown | unknown | unknown |
| C11 | 合法 JSON/hash，但内容无关 | unknown | pass | unknown |
| C12 | 明确内容反证 | fail | pass | fail |
| C13 | 无实际 verifier，模型填写检查 pass | unknown | unknown | unknown |
| C14 | 实际 verifier 超时 | unknown | unknown | unknown |
| C15 | 伪造通过结果，真实内容失败 | fail | pass | fail |
| C16 | 同一 checker 后改写证据 | unknown | pass | unknown |
| C17 | 后一个 AC 改写前一证据 | unknown | pass | unknown |
| C18 | 首次通过后文件改变，再请求 | unknown | fail | unknown |
| C19 | 不变输入重复请求 | pass | pass | pass |
| C20 | envelope 声称版本正确，实际 HEAD 已变 | unknown | pass | unknown |

两组规范化输入完全一致，每例重复 3 次；不把重复当作新增独立样本。

| 指标 | 基线 | 候选 |
| --- | --- | --- |
| 错误放行 / 应阻断的不同案例 | 7/18 | 0/18 |
| 错误阻塞 / 应通过的不同案例 | 0/2 | 0/2 |
| 三轮错误放行 / 应阻断判定 | 21/54 | 0/54 |
| 三轮错误阻塞 / 应通过判定 | 0/6 | 0/6 |
| 三态错误 / 60 个末次案例判定 | 36/60 | 0/60 |
| 三轮本地判定一致的案例 | 20/20 | 20/20 |
| gate 请求数（含 C18/C19 前置请求） | 66 | 66 |
| gate 总墙钟耗时，不含 fixture 构造 | 127.47 ms | 764.67 ms |
| 每请求均值，仅描述此样本 | 1.93 ms | 11.59 ms |
| 自动业务重试 | 0 | 0 |
| 真实 token / 真实模型稳定性 | unknown / not_run | unknown / not_run |

候选增加实际 Git、内容和尾检，因此本地耗时增加约 9.65 ms/请求；没有宣称省 token。
计量含实际 checker 和 gate，模型调用、端到端业务成本、缓存计费均未测。
调试阶段失败测试、整仓超时和复跑另留日志，不从交付证据中删除；三个整仓尝试各达到 60 秒预算，并非业务重试。

## 5. 本地验证与复跑

- 冻结案例：20 项 × 3 轮全部符合预期；合同/事件/快照前后字节一致。
- 六组针对性和必要回归：241 个 unittest 方法通过（其中 1 个包含 20 个冻结子案例）。
- 隔离物化工作区：346 个测试通过，约 35.97 秒。**未包含 1 项历史 Git archive 测试**；原工作区完整回归存在读取超时，未声称全量绿。
- 根源码、Strict 源码、完整根包、完整 Strict 包验证通过；Strict 包从 `/private/tmp` 实际执行新案例通过。
- 新旧公共报告 hash、合同/审批校验、独立验证、Truth Sources、规则门禁均有既有回归覆盖。
- 本轮新增/修改源文件 whitespace 检查、生成副本逐字节检查通过。曾误将 unified diff 本身当源文件检查得到格式噪音，已改为检查实际源文件对，不作为产品失败或通过证据。

在本项目 cwd 下：

```sh
# 当前源码，20 个冻结案例
/opt/homebrew/bin/python3.12 tests/test_completion_upgrade.py

# 相同案例对冻结基线；应出现已记录的失败，不应伪装成绿色
COMPLETION_PACKAGE_ROOT="$PWD/.scratch/strict-completion-upgrade-20260910/baseline" \
  /opt/homebrew/bin/python3.12 tests/test_completion_upgrade.py

# 完整 Strict 包身份校验
/opt/homebrew/bin/python3.12 scripts/skill_package.py verify \
  --package .scratch/strict-completion-upgrade-20260910/strict-package \
  --expected-manifest-sha256 96dc85092f61d0cfd1bd3f77335427e3b3267a2247725997c906a8d4c02d3ab0

# 三轮对照和分组回归；保留整仓超时报告，勿把它视为全量通过
/opt/homebrew/bin/python3.12 .scratch/strict-completion-upgrade-20260910/run_validation.py

# 重跑已经保存并核对过 hash 的隔离工作区：346 项，显式排除 1 项历史 Git 测试
/opt/homebrew/bin/python3.12 .scratch/strict-completion-upgrade-20260910/replay_materialized.py
```

机器证据：`summary.json`、`baseline-{1,2,3}.json`、`candidate-{1,2,3}.json`、`commands.json`、
`materialized-regression.json/.log`、`strict-build.json`、`strict-verify.json`、`incremental-integrity.json`。
原始模型判断字段明确是 synthetic fixture，实际 checker 结果和 gate 最终结果分别保存。

## 6. 限制与应用结论

**值得进入一个真实项目的受控试点，不支持立即全局推广或宣称生产可靠。**

- 本轮内容 checker 只理解官方示例的精确内容条件；真实业务必须绑定自己的可信、可执行验收逻辑，不能照搬该字符串或写一个恒定 pass 的回调。
- 程序能执行、验证宿主提供的 checker，不能认证同权限恶意宿主、伪装成 checker 的恶意 callable，或证明手写日志确实来自某次执行。模型不得控制注册表。
- 本轮尾检覆盖 `file`；`test-report`、URL、自定义 resolver 保持原有保证，没有声称一并强化。
- legacy envelope 可省略 contract_version；严格版本绑定应按示例在封印 required_scope 中要求该字段。不能把兼容路径当新契约。
- 冲突案例验证的是已记录冲突的阻断，不是自动发现任意自然语言证据矛盾。
- gate 返回后的外部修改、多个文件的对抗式并发写入及实际完成状态写入的原子性，不由只读 gate 独自保证。
- 1 项历史 Git 包回归仍未知；真实模型对照、自然项目效果、token 收益未验证，没有新增付费调用。

按 Context Strict 的证据边界与 TDD 顺序，先复现、后修补，再独立复跑；未全局安装，未修改生产状态，未提交、合并、推送或部署。
