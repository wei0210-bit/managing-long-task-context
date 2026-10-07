# 接手材料（收尾验证中断二，2026-10-07 03:46 UTC）

只写路径与标识，不复述状态；状态以任务库与 Orca 为准。

- 协调者工作区：/Users/zhaowei/orca/workspaces/managing-long-task-context/context-skill-for-Orca
- 任务库：<协调者工作区>/.prime/context，任务 CLOSE-A、CLOSE-B
- 固定包：/Users/zhaowei/orca/workspaces/managing-long-task-context/.pinned-packages/context-strict-017aa63（manifest bf7688fedac119d299416bae8856cdb4a7e832086dca4d0f8520fe48b21886df）
- Orca Run：run_b7ed73396b54
- worker 报告路径模板：<worker 子工作树>/.context-reports/<task_id>/<dispatch-id>.json；子工作树位于 /Users/zhaowei/orca/workspaces/managing-long-task-context/ 下，名称为任务 id 的小写
- 协作规程：<协调者工作区>/references/orca.md（入账与去重、接手两节）
- 恢复入口：`scripts/context_status.py`（见 SKILL.md 与 references/orca.md 的只读入口表）
