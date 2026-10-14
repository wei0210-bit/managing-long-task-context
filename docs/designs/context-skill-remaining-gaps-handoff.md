# 交接：Context Skill 剩余差距（G1–G4）

- 交接时间：2026-10-14
- 交出方：会话 context-skill-for-orca-32（office-hours 与 plan-eng-review，只写评审文档，未改代码）
- 接手方：协调会话 eb629ee5（David 2026-10-14 点选「交给协调会话 eb629ee5（推荐）」）
- 基线：main `851a7db`（PR #86，Strict 1.0.0）

## 先读

1. `docs/designs/context-skill-subtraction.md` 的「剩余差距（基线 `851a7db`，2026-10-14）」一节：G1–G4 的范围、现状与仍有效的决定。
2. 同一文件末尾「Decision ledger」：D3、D6、D7、D8、D9、D11、D12 的已定范围；D2、D4、D5、D10 已失效。
3. 测试计划：`~/.gstack/projects/wei0210-bit-managing-long-task-context/zhaowei-main-eng-review-test-plan-20261014-081310.md`（其中 ci_evidence 与 accept 相关项随 D2、D10 失效，检索与 R-004 相关项仍有效）。

## David 已定

- 方案方向：B「三类清单真删」（大部分已由 #86 完成）。
- 知识层：context 的积累用文件完成，再加搜索引擎式全文索引（D7、D11）。
- 全局规则的执行控制要改，但只对声明了 CI 全量的项目放宽（office-hours 点选与 D4 判定方式）。
- CI 加 macOS 作业（D3 = A）。
- 检索提前单独做（office-hours 点选）。

## 仍需 David 直接授权

- G1：两份全局规则共享段「验收深度四层」与「每轮修复 AC 回归清单全过」的改写。
- G2：CI 内容改动（回归步骤、macOS 作业、超时上调）；R-004 下限写进命令；任何回归条目的改写或退役。

## 建议的第一步

在 `851a7db` 上对 G1–G4 重跑 `/plan-eng-review` 的受影响部分，重点是 G1 的「CI 全量」声明放在哪里（常设授权文件已删），以及 1.0.0 中验收证据以什么形式登记进账本。G3 只读、不碰执行控制，可单独先行。

## 本会话留下的文件

- `docs/designs/context-skill-subtraction.md`（未跟踪）、本文件（未跟踪）。
- `~/.gstack/projects/wei0210-bit-managing-long-task-context/zhaowei-main-design-20261014-004222.md`（跨会话副本，开头有基线变化警示）。
- `.context-lite/ctx-subtraction-review/NOW.md`（被 Git 忽略）。
