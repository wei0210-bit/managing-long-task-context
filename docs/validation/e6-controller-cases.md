# E6 主控独立案例（实现完成前冻结）

均为合成观察，不以实现自报数值为期望。公共summarize_usage/evaluate_pressure与CLI为测试seam。

| ID | 刺激 | 预期 |
| --- | --- | --- |
| U01 | included输入100，read40，write10，output20 | 输入总100，输出20，总120；cache不重复加 |
| U02 | separate输入100，read40，write10，output20 | 输入总150，输出20，总170 |
| U03 | cumulative同session输入100→150，输出20→30，两快照均included | 只最终180，不累计300 |
| U04 | 两session，同event_id但分别真实独立记录 | 不串session；若不支持同局部ID明确unknown，不默默丢一份 |
| U05 | 同session同event_id不同输出，或累计输入倒退 | unknown且不得给貌似完整的总计 |
| U06 | 所有计数0但有完整来源/范围 | 允许观测范围为0，费用和Skill归因仍未知 |
| U07 | 布尔计数、缺cache口径、NaN、重复JSON键 | unknown/拒绝，无完整总计 |
| P01 | C1000 U700 R200 G100，安全点未完成 | prepare；U699不触发，U701触发 |
| P02 | 累计token100000但无current-window读数 | 不据此判高占用；unknown或标明里程碑降级 |
| P03 | 同一有效观测20次，传回上次state | 最多一次notify，无写/模型/brief/重建 |
| P04 | 同sample ID改内容 | 冲突unknown；不得用去重丢风险 |
| P05 | 新sample改变预算/安全性 | 重新评估；旧dedup不能挡住变化 |
| P06 | task_complete=true；另设execution_unknown=true | 不开空会话；未知在途defer，零业务/宿主调用 |
| P07 | 超期、未来、wrong-session previous | 不借旧或别的session读数做精确判断 |
| B01 | CLI超1MiB/超1000条、非regular、不可读、非法UTF8 | 有界unknown/拒绝，不扫描其它目录，不执行source_ref |

每组可包含多个字面量子断言。报告实际方法/子断言分母，不把重复20次当20个模型案例。最终程序耗时是本地观测开销，不是任务总耗时或token收益。
