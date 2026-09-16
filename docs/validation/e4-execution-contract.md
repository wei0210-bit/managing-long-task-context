# E4 v1 — 原生宿主能力边界（派发前冻结）

授权：用户要求剩余计划连续执行；不安装、不提交/合并/推送、不改生产，不启动真实付费宿主任务。
工作区：`.worktrees/short-session-remaining`，分支 `codex/short-session-remaining`。基线为E3当前未提交源码快照，不是Git HEAD。
执行：Terra-high；独立复核：主控及非执行者。禁止执行者派子Agent。

## 能力实查与范围裁决

当前Codex原生工具支持同父树spawn/list/send/followup/interrupt/wait，未暴露可核验的主控身份、全局写入排他、跨父接管、归档和无历史证明。Claude原生工具未在当前宿主暴露。工具schema不是宿主端到端证据。
因此不编造provider API或签名凭证。此单交付两个窄的原生能力适配入口和受限路径说明：可读能力盘点/限制；涉及控制权的操作明确unsupported/unknown且零调用、零任务写入。实际接管支持仍未完成，须可信宿主桥提供证据后再实现，不能用全阻断宣称业务验收完成。

## 冻结接口与所有权

- `src/managing_long_task_context/host_codex_native.py`：`capabilities()` 返回静态、带来源/证明层级的结构结果；`request_control(operation)` 对 start/resume/takeover/archive 等受控操作返回明确未知及缺失能力，不调用工具。
- `src/managing_long_task_context/host_claude_native.py`：相同窄接口，Claude原生未可用单独说明。不得复制handoff状态机、伪接线CLI或创建通用bridge框架。
- `tests/test_handoff_codex_native.py`、`tests/test_handoff_claude_native.py`、`references/host-native.md`。
- 执行报告：`docs/validation/e4-executor-report.md`，记录红/绿命令原始关键输出、文件清单、局限。主控拥有生成同步、package/runtime_identity/CI接线。

## 冻结验收（均为本地机制，非真实宿主）

1. 两原生路径分开报告；Codex同父树可寻址是schema声明而非实测trusted能力；Claude不可用不借用CLI结果。
2. `capabilities()`成功返回可读限制，反复20次语义一致、无文件/模型/宿主调用；返回对象修改不污染后续结果。
3. 控制操作未能证明identity、fencing、clean-history或parent-survival时必须未知/unsupported；不能返回执行成功、完成、接管或归档通过。
4. 未知操作和恶意/畸形参数明确拒绝；不可把模型填入pass、署名、路径或ID作为能力依据；不得执行字符串。
5. 旧E3 ledger/handoff功能不改，两个入口不得自行新建任务状态；不继承父聊天作为新会话证明。
6. 两个模块各有正例（能力盘点）及负例（控制拒绝），禁止将负例全部阻断称为接管正确放行。
7. 说明人工交接需要的文件/当前任务身份和旧会话保留规则：成功核实接续前不归档唯一入口、不重派未知在途动作；不承诺自动切换。

命令：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_handoff_codex_native test_handoff_claude_native -v`。
先可调用保守stub、行为测试真实红，再逐片绿；import缺文件不是行为红。冻结预期不得洗绿。
若发现真实可信原生入口，不擅自扩做，先向主控报证据。真实host/model/natural验证全部NOT_RUN，token收益UNKNOWN。
