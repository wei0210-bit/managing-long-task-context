# 核心结构只读审计

日期：2026-09-15。范围：根 `src/managing_long_task_context/__init__.py` 的静态结构、关键共享状态、近期相关提交、代表性既有回归。未修改实现、运行环境或生产状态。此文件为按需证据，不是第二份开发计划；计划见 [short-session-handoff.md](../superpowers/plans/short-session-handoff.md)。

## 基线与结论

- HEAD：`0f5898e19b4951c661edce1f7db80f95cc1b2ecc`，main。
- 核心 SHA-256：`ffa6420ff08115cfea3c011ddfd026a7cb074be5bb9756b16aabe1bd162e0f96`。
- 4,742 行，204,619 Unicode 字符；AST 顶层函数 126 个、顶层类 3 个。本轮较早的行首 grep 计数没有覆盖 async 定义，不能替代 AST 数字。
- 同文件具名函数之间静态去重调用边 313 条。动态回调、属性调用、跨模块调用和运行分支未完整建模，不能当成完整运行调用图。
- Python 3.12 标准入口运行五组既有测试：228/228，通过，测试框架报告 8.485 秒。不是全库测试，不是生产可靠性、真实 Agent 稳定性或 token 收益证明。

**判断：维护复杂度已值得控制，但本次没有证明“文件长导致执行退化”。** 新协议独立薄模块、旧核心仅必要接入；不做全量重构。现有门禁顺序和二次核验属于承重逻辑，不能仅凭相似代码判定为冗余。

## 结构与热点

| 函数 | 起始行 | 函数跨度行数 | If／IfExp 节点数 | 判断 |
|---|---:|---:|---:|---|
| `_evaluate_completion_criterion` | 3691 | 274 | 38 | 完成证据判定集中，修改须保持每项结果与整体 gate 一致 |
| `_gate_core` | 3456 | 233 | 37 | legacy 路径兼容与验收组合集中 |
| `_audit_core` | 2789 | 186 | 25 | 多类完整性检查集中，不能以统一错误处理隐藏具体阻塞 |
| `_independent_validation_check` | 4027 | 160 | 32 | 身份、版本、时间、证据绑定密集，不能只迁文件不验证行为 |
| `_validate_contract_shape` | 448 | 141 | 36 | 封印前判据入口，变更会影响发布及恢复 |
| `_plan_brief_from_view` | 2363 | 139 | 9 | 摘要职责相对可识别，未来如触及可先评估纯选择／渲染部分 |

跨度包括函数中的空行和注释。If 节点包括嵌套语句，不包括全部布尔短路、循环或异常分支；**不是正式圈复杂度**，不代表错误概率或需要拆成多少函数。

高复用入口：`_paths` 有 22 个同文件具名调用者，`_load_committed_task_view_locked` 有 13 个，`_read_json` 有 11 个，`_append_event_locked` 有 9 个。这里的“调用者”不是执行次数；没有内部调用者也不表示公开 API 未使用。

最近 12 次修改核心的提交中，除独立验收和运行身份外，多个修复涉及 truth gate、锁失败降级、事件尾部统计和判定时点：`6181806`、`ce1310c`、`e1ce122`、`a9d8d91`、`ec415e3`。这提示新代码接入要重点保护这些边界，不是这些历史问题当前仍存在的证据。

## 调用关系与共享状态

```text
gate（最终证据／授权／时效复核）
  -> _gate_with_rules（基础门禁 AND 规则，不替换基础失败）
     -> _gate_without_rule_execution（受控路由／锁边界）
        -> _gate_core（legacy）
        或 _truth_gate_entry_locked -> _gate_truth_enabled（truth）
              -> _evaluate_completion_criterion -> 独立验收／证据检查

brief -> 已提交任务视图 -> 选择／预算 -> packet
                 ^
合同、记录、audit、gate 共用存储／事件／快照机制
```

按代码区域静态分组，audit/truth/gate 区域向 completion/independence/rules 区域有 3 条具名调用边，反向有 6 条。它们是当前单文件内职责之间的双向联系，不是现有 Python 模块循环导入错误；直接按行段机械拆文件会把隐含联系变成导入问题。

共享状态人工核对：`_PROCESS_LOCKS_GUARD` 与 `_PROCESS_LOCKS` 位于第 124-125 行，`_process_lock_guard` 第 215 行按任务根路径写入锁表。锁不是全项目只用一把，但不同功能对同任务共用它。不得在新模块复制一份锁表或在已持有非重入锁时盲目再调用加锁接口。静态脚本首轮仅查方法调用而漏掉下标赋值，已人工及 AST 下标补查订正；未据其空结果宣称“无共享状态”。

运行身份另有导入时快照，全局捕获在包末尾显式注册模块；新模块需要同步登记。项目事实主要位于任务文件／事件，不因为共享 Python 模块就自动跨任务合并；仍需工作区绑定与锁回归证明隔离。

门禁中的多次观察不能一刀切删除：`gate` 在所有回调之后重新检查本地 file 证据、合同、部分上下文和独立验收时间；`_gate_with_rules` 对规则来源重新核查；truth 路径核对事件尾部。它们防的是检查过程中事实改变，不是简单重复。把这些合并成“一次读取供全流程复用”可能降低安全性。

## 测试与边界证据

| 套件 | 方法数 | 本次结果 | 覆盖的相关领域 |
|---|---:|---|---|
| test_context | 81 | PASS | 合同、记录、摘要溢出、完成证据及回调输入保护 |
| test_truth_sources | 100 | PASS | 事件恢复、快照差异、锁、回调期间原件／合同变化 |
| test_independent_validation | 16 | PASS | 身份、时效、旧证据、truth 与独立验收交互 |
| test_rule_execution | 14 | PASS | 规则与基础 gate 组合、来源变化、合同回调与死锁反例 |
| test_runtime_identity | 17 | PASS | 运行包身份、绑定、受控导入时期变化 |

计数单位是 unittest 测试方法，不是 subTest 数量。代表性测试包括 `test_completion_callbacks_cannot_mutate_sealed_requirements_or_callers`、`test_completion_tail_detects_mark_during_evidence_callback`、`test_completion_tail_detects_contract_update_during_callback`、`test_checker_contract_change_blocks_without_deadlock`、`test_manifest_change_during_controlled_module_import_never_reports_pass`。测试名和源码被直接核对；未计算语句或分支覆盖率，不把没有直接函数名引用视为没有测试。

失败尝试如实保留：初次用系统 Python 3.9.6 和 stdin 自写 runner，81 个 context 测试通过后 truth 套件失败，出现 `FileNotFoundError: .../<stdin>`，并有后续线程错误。Python 版本低于项目 `>=3.10`，macOS spawn 也无法重建 stdin 入口。该次运行不作为产品通过／失败基线；未修改测试，改用已有 Python 3.12 的标准 `-m unittest` 后得到上表结果。

有效复跑命令（仓库根）：

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_context test_truth_sources test_independent_validation test_rule_execution test_runtime_identity -q
git log -12 --oneline -- src/managing_long_task_context/__init__.py
shasum -a 256 src/managing_long_task_context/__init__.py
```

可复跑静态摘要（只解析源码，不 import 项目；计数定义同上）：

```bash
/opt/homebrew/bin/python3.12 - <<'PY'
import ast, collections, pathlib
p = pathlib.Path('src/managing_long_task_context/__init__.py')
s = p.read_text(); t = ast.parse(s)
fs = [n for n in t.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
names = {n.name for n in fs}
calls = {n.name: {x.func.id for x in ast.walk(n) if isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id in names} for n in fs}
fanin = collections.Counter(x for cs in calls.values() for x in cs)
print('lines/chars/functions/classes/edges', len(s.splitlines()), len(s), len(fs), sum(isinstance(n, ast.ClassDef) for n in t.body), sum(map(len, calls.values())))
for n in sorted(fs, key=lambda n: n.end_lineno-n.lineno, reverse=True)[:8]:
    print(n.name, n.lineno, n.end_lineno-n.lineno+1, sum(isinstance(x, (ast.If, ast.IfExp)) for x in ast.walk(n)))
print('fanin', fanin.most_common(8))
for n in fs:
    for x in ast.walk(n):
        if isinstance(x, ast.Assign):
            for v in x.targets:
                if isinstance(v, ast.Subscript) and isinstance(v.value, ast.Name) and v.value.id.isupper():
                    print('global-subscript-write', n.name, x.lineno, ast.unparse(v))
PY
```

## 处理建议与未验证项

1. 当前升级：采用 CEO-D10 薄模块边界；共用旧事件／锁，不改变旧 API、门禁顺序或未启用任务语义；新增模块的身份、分发和隔离包执行一起验证。
2. 存量核心：不自动重构。以后确有修改需求时，先评估纯摘要选择／渲染等较明确边界；完成门禁和存储路径等高耦合部分应在特征测试及跨功能回归保护下单独评审。这里只给候选，不增加当前开发批次。
3. Agent 阅读：正常运行保持 API＋brief，开发时按入口和调用依赖读取；这个索引是导航而非截断相关代码的硬上限。未采集真实使用轨迹，不能断言所有项目都已按此执行。

没有得到：全库覆盖率、真实并发负载、长期进程锁表增长、真实 Agent 读取量、模型错误率、token 或费用收益。本次未确认新的功能缺陷；228/228 只能说明这些既有案例在本环境通过，不能排除未覆盖问题。
