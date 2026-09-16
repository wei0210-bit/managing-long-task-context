# 真实路径验证素材记录

这里保存从任务开始时前瞻登记、按关键事件追加的验证素材。记录器只解决“从现在开始留下什么原件和边界”，不自动证明：

- 真实原生宿主已经完成自动接管；
- Strict/Lite 对自然项目有因果效果；
- token 或费用已经下降。

即使素材齐全，`status` 的三项 `claims` 仍固定为 `UNKNOWN`；后续必须由独立评估按原始证据和可比较样本得出结论。

## 记录目录

每个观察使用独立 `observation_id`：

```text
observations/<observation_id>/
├── observation.json
└── events/
    ├── <event_id>.json
    └── ...
```

元数据和事件均先完整写入临时 inode，再以排他链接发布；记录器不会覆盖已有 ID：完全相同内容返回 `duplicate`，同 ID 不同内容返回 `EVENT_ID_CONFLICT`。这能防并发与崩溃造成的半写文件，但不是 WORM：拥有目录写权限的操作者仍可删除或替换文件。文件 SHA-256 只是当前内容收据；需要抗篡改审计时，必须把收据提交到受保护的 Git/远端日志或签名系统。

## 开始一条观察

先复制并填写 [observation-start.template.json](observation-start.template.json)，在任务执行前运行：

```sh
python3 scripts/real_validation.py start \
  --root "$PWD/docs/validation/real-evidence/observations" \
  --input /absolute/path/observation-start.json
```

`project.revision` 必须保留真实 revision；dirty 工作区不能写成 clean。Strict/Lite 必须记录完整安装路径、版本和 manifest SHA-256。`execution` 保存模型、推理强度和稳定配置引用；`comparison` 保存比较组与冻结任务定义引用，拿不到就明确填 `null`。拿不到稳定宿主 session 或身份收据时同样填 `null`，不能用聊天标题或模型自报代替。

## 追加关键事件

按事件类型选择模板。不要逐轮抄聊天；只记接管操作、任务验收、provider usage 和账单成本等承重事件：

```sh
python3 scripts/real_validation.py record \
  --root "$PWD/docs/validation/real-evidence/observations" \
  --observation-id OBS-YYYYMMDD-NNN \
  --input /absolute/path/event.json
```

- [boundary-event.template.json](boundary-event.template.json)：记录尚未开始、阻塞或 unknown 的边界。
- [native-control-event.template.json](native-control-event.template.json)：每次真实 `create/transfer/continue/archive` 操作一条；记录自动/人工触发及触发收据。`succeeded` 必须同时有源/目标 session 和六项宿主检查；自动成功还必须有自动触发原件引用。
- [task-outcome-event.template.json](task-outcome-event.template.json)：自然项目结束或中断时记录验收、额外回合、重试和人工纠正。正常完成、失败、未触发和中断都要连续登记，不能只挑成功案例。
- [usage-event.template.json](usage-event.template.json)：保留 provider 原始 token/cache 口径与收据引用；单轮或部分窗口不得写成全任务总量。
- [cost-event.template.json](cost-event.template.json)：保留币种、金额、覆盖范围、是否含重试及归因状态；估算不得冒充账单。

`source_refs` 只放可定向读取的稳定原件引用，不粘贴凭据、Cookie、Authorization、原始提示词或个人数据。记录器拒绝常见敏感字段名，但这不是完整泄密扫描。

## 查看当前素材状态

```sh
python3 scripts/real_validation.py status \
  --root "$PWD/docs/validation/real-evidence/observations" \
  --observation-id OBS-YYYYMMDD-NNN
```

`material_available` 只说明相应类型的结构化素材已出现：

- native：至少一条字段完整、明确为自动触发且带触发原件引用的成功宿主事件；人工 transfer 不计作自动接管素材；
- natural：至少一条自然项目的明确 pass/fail 验收结果；
- token/cost：同一观察至少有 usage 与 cost 各一条。

它们都不等于结论。自然效果需要跨观察的冻结任务/对照，token/费用收益还需一致模型、推理强度、计量边界、重试范围和 provider 账单。

## 当前起点

`OBS-20260916-RECORDING-001` 已登记本记录能力启用时的边界：Strict 0.8.0 包身份已核验；可信原生宿主 bridge、稳定 session 身份、完整 token 与账单收据均未取得，所以三项结论不变。
