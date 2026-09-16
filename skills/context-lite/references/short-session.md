# Lite 短会话接续

此流程只为已选用 Context Lite 且已完成完整包身份绑定的低风险任务提供
只读交接材料；它不继承聊天、隐藏推理、权限、凭据、连接、进程或控制权。

1. 由旧会话对候选 NOW 运行 `flush`。保存输出的 `now_sha256`；它是本次交接
   固定的 NOW 字节版本，不是第二个事实库。
2. 新 Python 进程只带完整包、已绑定的工作区／context root／task ID，运行
   `cold-check --expected-now-sha256 <sha256>`。任一身份 hard stop、坏指纹、
   读取失败或两次有界读取不一致，均只返回 unknown，不交付材料正文。
3. 新会话将材料当作待独立观察的清单：逐项重新观察目标、Acceptance、状态、
   决定、在途项、Blockers、唯一 First action 和稳定刷新映射。不要执行任何
   `refresh_ref` 或 `recovery_ref`；尤其不要重试 unknown 的 in-flight 项。

材料中的 `history_inheritance: unknown`、`semantic_verification: pending` 和
`archive_allowed: false` 是固定边界。文档指纹、格式合法或程序冷读取不构成模型
冷启动、语义核验、任务完成或归档许可。交接不是 `finish`：任务仍继续时保留旧
会话与 NOW；仅在任务真正结束时才按原 finish 流程处理。
