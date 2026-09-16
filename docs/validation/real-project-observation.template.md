# 单任务观察记录（模板，不是实测结果）

机器可校验、在记录器 API 内排他发布且不主动覆盖（非 WORM）的前瞻素材优先使用
[`scripts/real_validation.py`](../../scripts/real_validation.py) 和
[`real-evidence/`](real-evidence/README.md) 内的 JSON 模板。本 Markdown 继续用于人工复核叙述，不能替代 provider/宿主/验收原件。

- observation_id / task_id：unknown
- 项目绝对路径 / 仓库 revision（含 dirty 情况）：unknown
- 观察起止 UTC / 原始事件时间：unknown
- 采样方式：prospective 或 retrospective；当前 unknown
- Skill 人工选择：Lite / Strict / 未启用 / unknown
- 完整包路径 / skill_version / manifest hash：unknown
- 身份核验记录路径（不能据此声称已加载）：unknown
- 会话加载证据路径 / 实际 API 或 validator 调用证据路径：unknown
- 模型 / 推理强度 / 会话标识：unknown
- 任务目标 / 完成条件的原件引用：unknown

## 关键事件（有事件才追加，不逐轮填）

| 事件与时间 | 当时适用规则及预期行为依据 | Agent 原始判断 | checker 原始结果 | 实际动作 | 复核结论 | 原件引用 |
| --- | --- | --- | --- | --- | --- | --- |
| unknown | unknown | unknown | unknown | unknown | unknown | unknown |

复核结论：正确放行 / 正确阻断 / 漏拦 / 误拦 / 未触发 / unknown。
原件引用使用绝对路径或带 revision 的仓库路径；不复制长日志、凭据或个人数据。
未读取、不可读取、未覆盖的部分明确写 unknown；冲突保留双方引用，不用新摘要覆盖旧证据。

## 任务结果与成本

- 最终结果与验收原件（完成 / 未完成 / 中断 / unknown）：unknown
- 人工纠正 / 重复探索 / 额外回合 / 重试次数及依据：unknown
- usage 原件 / 计量起止边界 / 是否含重试和工具调用后的后续模型轮次：unknown
- input tokens / output tokens / cache read / cache write（保留提供方原始口径，避免重复加总）：unknown
- 总耗时 / 可辨识的 Skill 维护耗时及依据：unknown
- 仅字符数、没有 usage 或无法分离成本时：unknown，不填 0，不计算节省比例
- 主控复核人 / UTC / 定向读取的原件 / 未覆盖部分：unknown
- 是否需要隔离复现 / 具体问题：unknown

记录任务整体成本不等于已证明 Skill 开销；真实观察不等于因果性收益。

## E6 可选本地计量补充（未采集即 unknown）

- usage 事件 ID / session ID / provider / model / delta 或 cumulative / cache 计量口径：unknown
- 原始 input / output / cache read / cache write 与 source_ref：unknown；cache 是否已含在 input：unknown
- 当前窗口 sample ID / observed_at / expires_at / window / used / reserve / growth / basis：unknown
- safe_point / task_complete / execution_unknown / milestone：unknown；不以缺字段默认安全
- 本地摘要是否完整可核查、是否仅观察集总量、是否已证明全任务覆盖：unknown
- 去重 previous 由哪个宿主自有记录保存、是否跨 session 错用：unknown
- 真实模型 token、价格/费用、重试成本、Skill 归因、自然项目收益：unknown；不得用字符数填补
