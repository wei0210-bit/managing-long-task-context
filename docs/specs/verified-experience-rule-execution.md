# 可验证经验与选定规则执行：Lite / Strict 规格 v2

Status: implementation authorized for the six approved tickets; external independent specification review not completed.

用户在确认 1A、2A 和六张纵向切片后批准按该拆分执行。此后续授权允许本项目开发与主控审核，不代表此前外部独立审核已通过，也不授权安装、提交、合并、推送或生产 Eval。工单为私人仓库 #10–#15；验收先冻结，再由 Terra-high 执行，主控复核原件与测试。

## Context and approved scope

帮助各项目积累可复用经验，重点解决规则写下但没有执行、无证据声称已执行、绕过入口令规则不触发的问题。经验自动积累不等于自动赋予权威。承重规则必须经过交叉验证、反向验证、效果验证和明确批准。

仅治理项目明确选定的规则；经验默认项目内。跨项目迁移、全局 hooks、自动每日扫描、自动修改项目指令、Agentic-Dev 修复均不在范围。不得削弱现有安全策略或将可选能力变成所有任务的固定负担。

## Verified current state

规格起草时基线：仓库 main 工作区干净。开发派发前仅本规格未跟踪，全量基线 291 项测试通过。现有 Lite 1.2.0 / Strict 0.6.0 为源码清单版本，不作为本轮安装版核验结论。

| 文件 | 已有行为 | 本次变化 |
|---|---|---|
| skills/context-lite/SKILL.md | finish 不产生长期记忆，恢复只读 NOW 与定向来源 | 显式启用的经验候选与检索；不自动从 finish 建库 |
| skills/context-lite/scripts/context_lite.py | validate/write/resume 公开 CLI | resume 可选接入经验建议与升级提示 |
| src/managing_long_task_context/__init__.py | gate release/resume/handoff/completion；审计、证据验证 | 新能力与既有 verdict 做 AND，不替代原有检查 |
| tests/test_dynamic_context_scenario.py | 使用恒 pass handler 测状态流程 | 新证据真实性场景必须使用真正读取原件的 handler |
| scripts/sync_context_tools.py | 共用工具同步分发 | 经验工具继续单一来源 |

本仓库根 CONTEXT.md 和 docs/adr/ 当前不存在，不假设其内容。Agentic-Dev 仅作为只读案例来源：三个脚本无 self-test 分支；角色守卫限定 src 路径；session-orient 会继续调用远程检查，本轮未执行。存在 DEVIATIONS 文件不证明调度违规表在维护。历史是否实际违规不能仅凭关键词缺失裁定。

## Trust and observation boundaries

1. 本库不是 OS 沙箱、身份认证系统或全局工具拦截器。相同文件权限的恶意调用者直接篡改存储不在防御承诺内；可检测结构/摘要损坏不得静默接受。
2. actor_id、approval_ref、不同模型名称都不证明独立性或授权。可信宿主提供 approval_checker 和 evidence_checker；JSON 数据不能注册或执行代码。
3. 规则 checker 与观察源都由宿主显式注册。源记录只能证明声明的覆盖范围；不能由 Agent 自填 complete=true 取得完整覆盖结论。
4. 没有独立观察源时返回 unknown/OBSERVATION_COVERAGE_UNKNOWN，不宣称已发现全部绕过。检测到确定违规时 fail 优先于 unknown。
5. 受控入口被调用才执行检查；gate 从未被调用时，库不声称会阻止行为。

## Four approved public test seams

### S1. Experience CLI: persist and retrieve

标准库实现 scripts/context_experience.py；跨 CLI 进程验证持久化，不直接读内部缓存确认成功。

```
context_experience.py init --workspace W --store S
context_experience.py record --workspace W --store S --input candidate.json
context_experience.py query --workspace W --store S --tags tag1,tag2 [--include-candidates] [--limit 3] [--max-chars 2000]
context_experience.py get --workspace W --store S --id E --revision N
```

所有 CLI 输出 JSON：{status: pass|fail|unknown, codes: string[], data: object|null}；退出码分别 0/1/2。输入错误为 fail/INVALID_INPUT，不输出 traceback 或敏感正文。

init 显式创建 S，默认 W/.context-experience；规范化绝对路径，固定 workspace identity，跨 workspace 拒绝。未 init 不自动创建。ID 复用现有任务 ID 语法，revision 正整数，UTC RFC3339。

首次 init 在锁内建立真实空记录与绑定；已绑定库丢失记录文件时 query/get/再次 init 均 unknown，不把状态丢失解释为空库或自动重建。

候选输入 exact keys：schema=1, experience_id, revision, claim, tags, applicability, exclusions, source_refs, supersedes。claim 非空且 <=2000 Unicode 字符；tags 为 1..10 个非空字符串；applicability/exclusions 为非空字符串数组（允许 exclusions=["none-known"]，不代表无例外）。revision=1 的 supersedes=null；后续版本的 supersedes exact keys 为 {experience_id:同一ID, revision:当前版本减1}，所指前版必须已存在。整数不接受布尔值。输入不得携带批准状态。

source_refs 是至少一个 {path: canonical absolute local file, sha256: 64 lowercase hex}。禁止 URL、路径逃逸和符号链接原件；本版原件须位于 W 内。read/hash 上限沿用现有 file resolver 16 MiB。缺失/不可读为 unknown，摘要不符为 fail。不会执行引用内容。

系统生成 created_at、workspace_id 和 candidate 状态。相同 ID/revision/规范化输入是幂等重放；不同内容同版本 fail/REVISION_CONFLICT。记录历史追加；索引可重建。锁住读改写、同目录原子替换；磁盘失败旧状态仍可 get，临时文件不得成为可恢复状态。

query 按显式 tags 交集匹配，不使用 embedding、不调用模型；最新版本优先，同分按 ID 排序。默认只返回当前有效 validated/approved 建议；include-candidates 才返回候选且标明不可依赖。已撤回/争议条目不作为建议返回，get 仍可读历史。适用范围须由调用者确认，tag 命中不是自动适用证明。

get 的 data 保留历史 status 与完整 provenance，并返回 validity={status:pass|fail|unknown,codes:[...]}；顶层 status/codes 与当前 validity 同步。S2 接入后附 latest_revision，已被同 ID 新版替代的旧版当前 validity 为 unknown/RULE_VERSION_SUPERSEDED，仍保留历史记录。原件过期、变化或缺失不得借历史 status 变为可依赖，但不抹掉可读历史记录。存储本身损坏/不可读时不伪造历史 data。未实现晋升前，S1 不接受只有 approved 字样而无晋升材料的存储记录。

预算按最终 data 的紧凑 JSON Unicode 字符数计；最多 3 条/2000 字符默认值。单条必须包含 ID/revision/status/claim/applicability/exclusions/source_refs。不可完整放入的条目不截断，返回 omitted_count 与 BUDGET_OMITTED；get 按 ID 定向取完整记录。不得用此预算裁剪已选承重规则。

### S2. Strict experience review interface

在 managing_long_task_context 新增公开 bind_experience(workspace_root, store_root)，返回以下 interface；Lite 包不暴露 review/approve。

```
store.review(id, revision, validation_refs, *, evidence_checker)
store.approve(id, revision, approval_ref, *, approval_checker, evidence_checker)
store.dispute(id, revision, reason, source_ref)
store.revoke(id, revision, reason, approval_ref, *, approval_checker)
store.get(id, revision)
```

结果 envelope 与 S1 相同。callbacks 是宿主注册 Python callable，不接受经验文件中的 import/命令路径。evidence_checker(record, validation_refs) 与 approval_checker(record, approval_ref) 返回 {status: pass|fail|unknown, codes: string[]}。缺 checker 是 unknown，不是降级批准。

S2/S4 共用回调边界契约（2A）：库校验返回对象类型、各接口必填字段、字段类型和枚举；None、布尔值、缺字段、非法状态或畸形引用结构统一为 unknown/CALLBACK_INVALID_RESULT，不按 truthiness 接受。普通回调异常（Exception）归一化为 unknown/CALLBACK_ERROR，TimeoutError 或宿主适配器明确报告超时为 unknown/CALLBACK_TIMEOUT；不吞掉 KeyboardInterrupt/SystemExit，不输出异常中的敏感正文。实际时间上限由宿主有界适配器执行，库不承诺中止任意 Python callable，也不盲目重试。此归一化仅针对新回调边界，不改变已有证据解析器或合法结果中明确 fail 的优先级。发生这些 unknown 时不得完成相应经验状态转换；S4 按当前阶段选定承重规则的阻断语义处理。

validation_refs exact keys：cross, counterexample, effectiveness。每项均含 source_refs、checker_id、checker_version、validated_at、expires_at；cross 另含 independence_basis（非空，审核说明）；counterexample 另含 original_pass_ref、mutated_fail_ref、restored_pass_ref、mutation_hit_ref；effectiveness 另含 representative_run_ref、non_applicable_run_ref。所有 *_ref 使用上述 file/sha256 结构。验证器负责内容含义及独立性，库只校验结构、版本、时间与摘要。不以字段齐全或测试 exit 0 证明真实验证。

状态 candidate -> validated -> approved；任一状态可 dispute；可信批准下可 revoke。disputed/revoked 版本不得重新批准，修订产生新 revision 并重新验证。新版本不继承批准。旧版本保留 historical 状态供追溯，但不能继续作为当前有效建议；已选旧版本规则的任务返回 unknown/RULE_VERSION_SUPERSEDED，须授权更新合同。

validity 与历史 status 分离：当前证据过期/不可读取返回 unknown；摘要变化 fail；均不可依赖。approve 必须重新核查当前验证材料并检查批准绑定 exact record digest、workspace、id/revision。批准 checker 认证能力由宿主承担，无可信实现时 approve 不可用。

S2 具体绑定结构：get.data.record_digest 为规范化持久记录的 SHA-256（排除派生 validity 与 record_digest 本身，不含实时调用时钟）。approval_ref exact keys 为 {workspace_id, experience_id, revision, record_digest, source_ref:{path,sha256}}。库验证绑定与批准原件完整性，可信 approval_checker 验证授权含义；四元组、文件存在或摘要相符均不能独立证明批准。approve 对当前 validated 状态、revoke 对待撤回版本当前持久状态绑定；回调不能改变已冻结的绑定或材料。

### S3. Lite resume interface

保留现有 resume 参数；新增 --experience-store S --experience-tags tags 两项必须同时提供。未提供走旧路径，不打开经验库。身份检查和 NOW 校验先于查询。

在原有结构中增加可选 experience 字段：{status, codes, suggestions, requires_strict}。NOW 的固定标题/80行/8000字限制不变；候选只通过单独 query 显式查询。

Lite 不负责晋升，也不自动执行建议。NOW 声明需要严格证明时由现有 Blockers 写明，机器入口增加 --requires-rule-proof 以让宿主显式声明；此参数为 true 时返回 unknown/STRICT_REQUIRED，不返回可用于继续执行的成功恢复结果。它不能自动识别所有自然语言承重要求，说明文件不得夸大。

经验检索失败不使无关低风险任务自动停工：返回原恢复结果并将 experience.status 标为 unknown，不把缺建议伪装成“没有相关经验”。已有 Blockers 不得被建议覆盖。

### S4. Strict gate interface

合同 opt-in required_capabilities 增加 rule-execution/v1；规则字段 rule_execution={schema:1, rules:[...]}。规则元素：rule_id, experience_ref|null, severity(advisory|load-bearing), applies_at(现有阶段枚举数组), trigger_id, checker_id, checker_version, observation_source_id。ID 均非空唯一；checker_version 为非空字符串。

已有规则 experience_ref=null：权威来自合同发布者的明确选择，不要求把现有授权规则重新伪装成新经验。新经验规则引用 {experience_id, revision, store_root}，必须当前 approved 且属于本 workspace。

gate 新增 rule_runtime 参数；未启用 capability 时不读经验/动作库，原有行为不变；启用后缺 runtime 是 unknown 并阻断当前阶段选定的承重规则，不以行为适用性尚未确定为由放行。

rule_runtime 提供 observe(task, stage, source_id)、applies(rule, observation)、check(rule, observation)、verify_experience(ref) callable。observe 输出 {status,codes,coverage:complete|partial|unknown,scope,observed_at,expires_at,source_refs,payload}；applies 输出 {status:applicable|not_applicable|unknown,codes,source_refs}；check 与 verify_experience 输出 pass/fail/unknown envelope。库重新验证引用完整性和时效，宿主负责可信采集及规则语义。

上述回调均遵守 S2 的 2A 边界契约；observe.status 使用 pass/fail/unknown。非法或异常结果不能形成 pass/not_applicable 的依据。

报告增加 rules=[{rule_id,status:pass|fail|unknown|not_applicable,codes,source_refs}]、coverage。先按合同 applies_at 确定当前阶段选定规则，再判断行为适用性；不得以行为适用性未知为由跳过规则。缺来源、部分覆盖、未知适用性不得 not_applicable；可信 complete 观察 + 有依据的不适用裁定才能 not_applicable。明确 fail 即使其他部分 unknown 仍是 fail。当前阶段选定的 load-bearing 规则只有 pass 或有充分依据的 not_applicable 可以放行；其他结果均阻断，令总 gate passed=false。advisory 仅警告。原有 gate 的失败不得被新规则结果覆盖。

```text
当前阶段选定的承重规则
  |-- 有充分依据证明不适用 -> not_applicable，可继续
  |-- 适用且检查通过       -> pass，可继续
  |-- 明确违反             -> fail，阻断
  `-- 其余情况             -> unknown，阻断
```

公开 gate 验收必须分别覆盖：缺观察源、覆盖不完整、行为适用性未知均 passed=false；有充分依据的不适用与适用且通过为正向对照。不同阶段的未选定规则不运行行为适用性检查。以上为 1A 已确认的判定语义，不是已运行的测试结论。

规则“必须派发”的触发形态是声明的受控修改动作，而不是“有派发记录”。观察显示发生受控修改而缺派发/前置验证为 fail；没有覆盖完整性证明为 unknown。没有动作记录不等于没有动作。

同一次 gate 使用锁定的合同与规则版本；外部观察/验证期间记录变化，在最终 verdict 前重验版本摘要，变化则 unknown/INPUT_CHANGED，不使用旧绿。批准后争议/撤回会让已有合同引用在下一次 gate 阻断。

## Acceptance, TDD and independent oracles

先冻结行为判据及公开接口，不预定测试数。每个纵向切片：一个真正失败的行为测试 -> 最小实现 -> 回归检查；不得由执行者自行降低判据。结构调整在后续审核阶段进行。

第一片只用合同明确选定的已有规则，不依赖建经验库：缺执行证据阻断 handoff -> 提供真实文件证据与可信观察适配器 -> 放行。随后按下列顺序推进：

1. 缺失/错误/过期证据与恒 pass checker 的已知反例自测；正向对照不误报。
2. 有受控修改无派发为 fail；无观察覆盖为 unknown；完整不适用场景才 not_applicable。
3. S1 候选保存、跨进程查询、范围过滤、重复/冲突/写入失败。
4. S2 验证、批准、版本变更、争议、撤回及其对 S4 已选规则的影响。
5. S3 明示能力不足、经验不可用不污染恢复、默认零额外读取。
6. 完整分发包的公开 CLI/API 冒烟及 Agent 动态验证。

每项期望从预先定义的案例事实推导，不能从被测实现生成。正向样本、违规样本及修复样本来自独立夹具。测试自己的内部函数或只断言内部调用次数不算行为验收。文件/时间/宿主系统适配器可替代，内部存储与判定逻辑不得用恒 pass mock 代替端到端证据链。

2A 公开接口验收：经 store.review/approve/revoke 与 gate 覆盖各新回调的非法返回（None、布尔值、缺字段、非法枚举、畸形引用）、普通异常及超时信号，断言稳定错误码；用 store.get 确认失败转换未改变历史状态，用 gate 确认承重规则 passed=false。保留合法成功结果与明确 fail 的对照，确认不自动重试、不泄露异常正文。超时信号归一化测试不等于任意 callable 的强制终止测试；无需为此新增进程框架。以上是冻结的验收要求，不是已运行的测试结论。

checker 自测通过只证明声明样本，不证明任意谎报均可检测。缺少 checker 自测证据不得把该检查器称为已验证；新经验晋升的反例材料应覆盖它所依赖的 checker。

隔离动态场景：三把尺子缺自测且错误推断已有；新单未检查欠账；违规记录缺失；工单不写行号的合规对照；直接修改绕过派发。测试检查行为与公开 verdict，不通过关键词计数断言“做过检查”。不得在 Agentic-Dev 中造故障或执行生产动作。

## Cost and outcome validation

未启用时经验文件读取0、模型调用0，保留必要身份/证据检查。资源计量通过公开诊断统计或文件系统/模型适配器边界采集，不绑定内部 helper 调用次数。query 输出限额不代表 token。

工具验证、Agent 动态验证、自然验证分别报告。Agent 动态验证必须实际使用完整包，记录模型/推理强度、输入、工具轨迹、总 token(可得时)、额外回合、误用/漏检；先前配对基线与新版本用相同任务、模型及设置。未经用户批准不运行收费/生产 Eval。无真实 Agent 运行只报告工具验证完成，不能宣称规则执行问题已解决。

至少一个新任务找到适用旧经验并避免重复探索；错误或过期经验不被信任；无批准晋升被阻断。自然验证待后续真实任务，不要求等待才能合入工具，但 overall 状态应为 implementation_verified / agent_verified / naturally_verified 分项，不能合并为已证明经济有效。节省幅度未知，不设捏造百分比。

## Files, distribution and rollback

新增 scripts/context_experience.py、src/managing_long_task_context/experience.py、rule_execution.py；复用现有文件 evidence 解析，不重写身份/证据系统。共用存储代码唯一维护源，scripts/sync_context_tools.py 生成包内副本并用测试校验一致。

修改根 SKILL.md（Strict 维护源）、skills/context-lite/SKILL.md、对应 CLI/gate、sync scripts、两个 skill-package.json。新增 assets 机器 JSON Schema 与 examples 完整调用；Lite 若新增 references，必须显式纳入 payload_roots。测试只放四个已确认 seams 及分发契约，不预设固定数量。

版本计划 Lite 1.3.0 / Strict 0.7.0；旧 API 默认兼容。完整包必须包含实现/Schema/示例/相关测试与一致 manifest；构建、校验、外部目录公开入口冒烟通过。不依赖仓库 cwd 或全局 Python 导入。

回退保留经验库与证据，不降级已启用任务为无规则模式。未知 capability 的旧包必须拒绝该新合同；无法证明旧包拒绝时禁止将该旧包用于启用任务。回退需明确目标包和任务范围，不修改业务项目。

原规划交付顺序：审核本规格 -> 确认最终稿 -> 独立脱敏/质量 gate -> 立项归档 -> 明确派发确认。当前用户已另行批准六张工单开发；外部独立规格审核仍记未完成，不以执行 Agent 报告替代。当前写入限本项目开发和测试工件；提交、安装、合并、推送、自然项目接入分别授权。

## Effort and open execution gates

估算而非承诺：人工团队5–8人日（规则闭环2–3，经验与晋升2–3，Lite/分发/验证1–2）；Agent开发+主控审核约1–2工作日，不含自然观察等待。新接口须在实现前依 schema 示例和独立审核修正，修正若改变批准/覆盖/阻断语义须重新用户确认。

独立审核重点：是否仍有调用者自证漏洞，默认路径是否负担过重，四个公开接口是否可测试，未知能力能否绕过，批准与验证是否混同。审核分数不是业务效果证明。
