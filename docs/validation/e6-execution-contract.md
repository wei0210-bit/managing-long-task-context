# E6 v1 — 无额外模型调用的观测与计量（派发前冻结）

范围：仅本地工具/合成验证、已有观察台账增量。真实宿主/模型/自然项目结论仍NOT_RUN；不启动收费评估，不读完整业务聊天，不改外部项目。E7现有代表性预算未触发，不能提前建索引。
执行Terra-high，主控及独立reviewer验收；不派子Agent，不提交/安装/发送。

## 文件/接口

维护源 `scripts/context_usage.py`，测试 `tests/test_context_usage.py`，按需说明 `references/context-usage.md`，报告 `docs/validation/e6-executor-report.md`。两份既有real-project-observation文档只追加新阶段字段和未验证状态，不覆盖旧内容。主控分发到完整包并登记声明。
两个纯函数公开seam：`summarize_usage(events)`、`evaluate_pressure(sample, previous=None, *, now)`；CLI只接受显式本地JSON输入，无扫描、轮询、模型、brief或事件重建。标准库，不建常驻服务或第二权威状态库。

## 先冻结数据口径（不得自行猜提供方usage语义）

usage输入是带来源的规范化观察列表，每项含 `event_id/session_id/task_id/provider/model`、`mode`(delta/cumulative)、`input_tokens/output_tokens/cache_read_tokens/cache_write_tokens`、`cache_accounting`(included/separate)、`source_ref`、`observed_at`。计数非负整数且非bool；必需计数缺失unknown不补0。session包含主/子各自记录，不因相同task合并去重。included表示input已含两类cache，两类和不能超过input；separate表示input未含cache。delta按唯一事件加总；cumulative同session取单调快照最后值、不把每轮累计相加。重复相同event_id同内容不重计，异内容冲突unknown；同session混合mode/provider/model/计量口径或累计回退unknown。总计只在完整可核查输入时提供，不把局部数冒充全任务成本。source_ref只是出处，输入非自动可信、不是计费账单证明。估算与实测标签分开，费用/全任务覆盖/Skill归因未知则null；不抓当前价格。

pressure输入必须标明 `session_id/sample_id/observed_at/expires_at/window_tokens/used_tokens/reserve_tokens/growth_tokens/basis`，basis=current-window或estimate；不能接受cumulative作为当前占用。另要求布尔字段 `safe_point/task_complete/execution_unknown/milestone`；缺失或错误类型不能默认安全。每实例只保留最后观察，由宿主传previous；没有previous不承诺跨进程去重。`window-used <= reserve+growth`触发prepare建议，非自动接管。未知/过期/非法读数回退显式安全里程碑信号；任务完成不新开空会话，非安全节点或执行结果unknown输出defer。输出decision/reason/estimated/dedup_key，不产生权限或执行动作。20次同样sample无重复notify；同sample异内容冲突unknown，关键内容变化不得被冷却时间掩盖。返回previous可供调用方自有局部记录，不写Strict承重事件。

## 冻结验证

M1 正常delta、cumulative、included、separate及多session固定字面量期望；不双算cache。
M2 缺计数/负数/bool/重复异内容/累计回退/同session混用/坏时间/未知模式=>unknown，无假总计。
M3 重复20次不增长总数；输出总量不是当前窗口读数，压力判定禁止混用。
P1 占用低于/等于/高于预算边界；仅等于及高于prepare；正例非全部阻断。
P2 过期/未来/跨session previous/窗口变化/伪造basis/缺量=>unknown或明确milestone降级，不认为低占用。
P3 安全点/任务完成/在途动作unknown优先控制提醒建议，绝不自动启动/终止/归档。
P4 相同输入20次notify只首次；关键变化重新评估、各session独立。
R1 CLI输入上限1MiB/1000记录，重复JSON键、NaN、非法UTF8、非regularfile、超限unknown，不执行引用，不吞未知行继续报完整。
R2 实际本地时间与可取得的进程峰值内存分别记录；模型tokens、真实费用、重试成本无计量就UNKNOWN，不由开发Agent消耗倒推产品收益。

命令 `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_context_usage -v`。先RED再GREEN，原始关键输出落报告，全部合成数据明确synthetic。不得用fixture预期作为实现返回。
