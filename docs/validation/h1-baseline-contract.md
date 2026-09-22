# H1 执行合同 v1：基线归档与 0.8.1 增量移植

发布者：调度会话（Cursor / Claude）。日期：2026-09-22。执行者：sonnet-xhigh-executor。
本合同冻结；执行者不得修改目标、范围、禁止项、交付物或验证项。现场与合同冲突时停下，带证据汇报。

## 现场事实（发布者已核实）

- 仓库：`/Users/zhaowei/Desktop/David/project.nosync/managing-long-task-context`，当前分支 `main`，HEAD `0f5898e`。
- `origin/main` HEAD `f61eabb`，领先本地 main 14 个提交（`git rev-list --left-right --count main...origin/main` → `0 14`）。已 fetch。
- `origin/main` 上 Strict 版本 0.8.0、Lite 1.4.0，含 phase-1（`host_codex_native.py`、`host_claude_native.py`、`scripts/context_usage.py`、`scripts/handoff_preflight.py` 等）。
- 主工作树有大量已修改/未跟踪文件。经逐文件比对，其中绝大部分是 origin/main 已合并内容的**旧快照**（比 origin/main 少代码），只有以下内容是工作树独有、尚未进入 origin/main 的 0.8.1 增量：
  1. `references/bot-pipeline-handoff.md`（新文件，origin/main 不存在）。
  2. `SKILL.md` 第 3 行 description 中新增的 `(including bot-to-bot pipelines)` 与 `that carry \`.prime/context/<task-id>/\` paths` 两处措辞。
  3. `SKILL.md` 新增的 `## Multi-bot / assistant pipeline handoff (shared truth)` 一节（含 `### Required handoff field`、`### Recommended handoff pack (minimum)`、`### Relation to brief() / gates` 与 `See also references/bot-pipeline-handoff.md`）。该节在工作树 SKILL.md 中位于 `## Hard stops` 之前。
  4. `skill-package.json` 的 `required_paths` 中新增 `"references/bot-pipeline-handoff.md"`。
- 工作树中的 `__init__.py`、`host_codex_cli.py`、`host_records.py`、`test_distribution.py`、`.github/workflows/ci.yml`、`scripts/sync_context_strict_skill.py` 相对 origin/main 都是**旧版本**，不含任何需要保留的增量。
- 三个 macOS 复制残留：`assets/experience-validation.schema 2.json`、`examples/experience_review 2.py`、`src/managing_long_task_context/experience 2.py`。
- 已安装全局包 `~/.codex/skills/context-strict` 为 0.8.1，`source_revision=local:context-strict-0.8.1-bot-pipeline-handoff-20260921`，由本脏工作树构建，缺 phase-1 功能。本合同**不**触碰它。
- 本机默认 `python3` 为 3.9；CI 用 3.12，路径 `/opt/homebrew/bin/python3.12`。所有验证用 3.12。
- 沙箱内 `git init` 会失败（无法创建 `.git/hooks`），测试必须在非沙箱环境运行。

## 目标

1. 把当前脏工作树完整、无损地保存到归档分支。
2. 从 `origin/main` 建新分支，把上述 4 项 0.8.1 增量移植上去，版本号定为 **0.8.2**（0.8.1 已被另一份内容不同的安装包占用，不得复用）。
3. 清除三个 ` 2` 残留。
4. 全部验证通过后提交到新分支。**不推送。不安装。不改 `~/.codex`、`~/.claude`、`~/.cursor`。**

## 范围（允许修改）

- Git 分支操作（新建 archive 分支、新建工作分支、提交）。
- 新分支上的：`SKILL.md`、`references/bot-pipeline-handoff.md`、`skill-package.json`、`pyproject.toml`、`scripts/sync_context_strict_skill.py`，以及由 `scripts/sync_context_strict_skill.py` 生成到 `skills/context-strict/` 下的对应文件。
- 删除三个 ` 2` 文件（新分支上它们本就不该存在；archive 分支保留原样）。
- R1 起：`tests/test_distribution.py`，仅限修订 R1 写明的那一行黄金清单同步。

## 禁止

- 不推送任何分支；不创建 PR；不打 tag。
- 不修改、不删除、不重装 `~/.codex/skills/*`、`~/.claude/skills/*`。
- 不修改 `origin/main` 已有的其他文件（除上面列出的 5 个源文件及其同步产物）。特别是不得把工作树旧版本的 `__init__.py`、`host_*.py`、`ci.yml`、`test_distribution.py` 覆盖到新分支。
- 不修改 `docs/validation/`、`CONTEXT.md`、`SESSION-HANDOFF-20260916.md`、`方案对话内容.txt` 的内容；不把它们提交到工作分支。
- 不修改任何测试的断言来让它通过。R1 允许同步 `tests/test_distribution.py` 的 `COPIED_FILES` 黄金元组一行，仍禁止改任何 `assert*`。
- 不在合同外“顺手”修任何发现的问题；发现了写进报告的“留给后续”。
- 不修改本合同。

## 执行步骤（实现细节可调，结果不可变）

1. 记录开工前状态到报告：`git status --porcelain | wc -l`、`git rev-parse HEAD`、`git rev-parse origin/main`。
2. 归档：`git checkout -b archive/main-worktree-0.8.1-snapshot-20260922`；`git add -A -- . ':!.claude' ':!.cursor' ':!.prime' ':!.venv' ':!.superpowers' ':!.scratch' ':!.worktrees'`；从索引移除 `.DS_Store`、所有 `__pycache__/`、`*.egg-info/`、`skills/context-strict/build/`（`git rm -r --cached`，不删工作树文件）；提交，信息 `archive: main worktree snapshot before rebasing 0.8.1 delta onto origin/main`。三个 ` 2` 文件**要**进 archive（原样保存）。
3. 切换：`git checkout -b codex/strict-0.8.2-usage-hardening origin/main`。此时 archive 里有而 origin/main 没有的文件会从工作树消失，这是预期。
4. 恢复只读材料为未跟踪状态（不加入索引）：`git restore --source=archive/main-worktree-0.8.1-snapshot-20260922 --worktree -- docs/validation docs/superpowers/plans/short-session-handoff.md CONTEXT.md SESSION-HANDOFF-20260916.md 方案对话内容.txt references/bot-pipeline-handoff.md`。确认 `git status` 中这些为 `??`，且 ` 2` 文件不存在于工作树。
5. 移植：
   - 把 `references/bot-pipeline-handoff.md` 加入索引（它是要提交的）。
   - 在 `SKILL.md` 中应用增量 2 和 3：description 两处措辞；在 `## Hard stops` 之前插入 Multi-bot 一节，内容与 archive 分支中 `SKILL.md` 该节逐字一致（用 `git show archive/...:SKILL.md` 取原文）。不得删改 origin/main 中 `### Session migration` 等其他内容。
   - `skill-package.json`：`skill_version`、`package_version` 改 `0.8.2`；`required_paths` 加入 `"references/bot-pipeline-handoff.md"`（放在 `"references/handoff.md"` 之后）。保留 origin/main 的其余条目与格式。
   - `pyproject.toml`：`version = "0.8.2"`。
   - `scripts/sync_context_strict_skill.py`：`COPIED_FILES` 加入 `Path("references/bot-pipeline-handoff.md")`（放在 `Path("references/handoff.md")` 之后）。
6. 运行 `python3.12 scripts/sync_context_strict_skill.py`，确认 `skills/context-strict/` 下生成的 `SKILL.md`（`name: context-strict`）、`skill-package.json`、`pyproject.toml`、`references/bot-pipeline-handoff.md` 与源一致。
7. 跑完整验证（下节）。
8. 提交：只提交 `SKILL.md`、`references/bot-pipeline-handoff.md`、`skill-package.json`、`pyproject.toml`、`scripts/sync_context_strict_skill.py` 及 `skills/context-strict/` 下的同步产物。提交信息 `feat: port bot-pipeline handoff reference onto main and bump to 0.8.2`。提交后 `git status --porcelain` 中只应剩 `??` 的只读材料（docs/validation、CONTEXT.md 等）和 `.DS_Store`。

## 验证合同（每项单独报告 PASS/FAIL，附命令原文与输出关键行）

工作目录均为仓库根。`PY=/opt/homebrew/bin/python3.12`。

| ID | 检查 | 通过标准 |
|---|---|---|
| V1 | `git log --oneline -1 archive/main-worktree-0.8.1-snapshot-20260922`；`git ls-tree -r --name-only archive/... \| grep -c ' 2\.'`；`git ls-tree -r --name-only archive/... \| grep -Ec '^(\.claude\|\.cursor\|\.prime\|\.venv\|\.superpowers\|\.scratch\|\.worktrees)/\|__pycache__/\|\.egg-info/\|\.DS_Store'` | archive 分支存在；第二条输出 `3`（三个 ` 2` 文件在 archive 中）；第三条输出 `0`（无本地状态/缓存目录混入） |
| V2 | `git merge-base --is-ancestor origin/main HEAD && echo ok` | 输出 `ok`（新分支基于 origin/main） |
| V3 | `git diff --stat origin/main..HEAD --name-only` | 只列出：`SKILL.md`、`references/bot-pipeline-handoff.md`、`skill-package.json`、`pyproject.toml`、`scripts/sync_context_strict_skill.py`、`skills/context-strict/SKILL.md`、`skills/context-strict/skill-package.json`、`skills/context-strict/pyproject.toml`、`skills/context-strict/references/bot-pipeline-handoff.md`。多一个或少一个都 FAIL |
| V4 | `git show origin/main:src/managing_long_task_context/__init__.py \| diff -q - src/managing_long_task_context/__init__.py` | 无输出（`__init__.py` 与 origin/main 完全一致，证明旧代码没被带回来） |
| V5 | `ls "src/managing_long_task_context/experience 2.py" "examples/experience_review 2.py" "assets/experience-validation.schema 2.json" 2>&1 \| grep -c 'No such file'` | 输出 `3` |
| V6 | `grep -c 'Multi-bot / assistant pipeline handoff' SKILL.md skills/context-strict/SKILL.md` 与 `grep -c 'Session migration: one mode' SKILL.md` | 前者两文件各 `1`；后者 `1`（origin/main 内容保留） |
| V7 | `$PY -c "import json;d=json.load(open('skill-package.json'));print(d['skill_version'],d['package_version'],'references/bot-pipeline-handoff.md' in d['required_paths'])"` | 输出 `0.8.2 0.8.2 True` |
| V8 | `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD/src $PY -m unittest discover -s tests 2>&1 \| tail -3` | 末行 `OK` 或 `OK (skipped=N)`；`Ran` 数 ≥ 501；0 failures，0 errors |
| V9 | 包外构建与核验（两个包）：`T=$(mktemp -d); for s in context-lite context-strict; do $PY scripts/skill_package.py check-source --source skills/$s && $PY scripts/skill_package.py build --source skills/$s --destination $T/$s --source-revision git:$(git rev-parse HEAD) > $T/$s.json && H=$($PY -c "import json,sys;print(json.load(sys.stdin)['manifest_sha256'])" < $T/$s.json) && $PY scripts/skill_package.py verify --package $T/$s --expected-manifest-sha256 $H --expected-source-revision git:$(git rev-parse HEAD) && (cd $T && PYTHONPATH=$T/$s/src $PY $T/$s/scripts/context_doctor.py check --mode full --package-root $T/$s); done` | 每个包的 check-source、verify、doctor 输出均含 `"status": "pass"`；context-strict 的 verify 输出 `skill_version` 为 `0.8.2` |
| V10 | `(cd $T && PYTHONPATH=$T/context-strict/src:$T/context-strict/tests $PY -m unittest discover -s $T/context-strict/tests 2>&1 \| tail -3)`；`(cd $T && PYTHONPATH=$T/context-lite/scripts:$T/context-lite/tests $PY -m unittest discover -s $T/context-lite/tests 2>&1 \| tail -3)` | 两者末行均 `OK`，且 `Ran` 数 > 0（与 origin/main 的 CI 步骤一致） |
| V11 | `git status --porcelain \| grep -v '^??' \| grep -v '.DS_Store'` | 无输出（提交后没有遗留已修改/已暂存文件） |
| V12 | `git branch -r --contains HEAD` 与 `git log origin/main..HEAD --oneline \| wc -l` | 前者无输出（未推送）；后者 `1`（恰好一个新提交） |

## 交付物

1. 归档分支 `archive/main-worktree-0.8.1-snapshot-20260922`。
2. 工作分支 `codex/strict-0.8.2-usage-hardening`，恰好一个新提交。
3. 报告文件 `docs/validation/h1-baseline-report.md`：开工前状态、每步实际命令、V1–V13b 逐项结果（PASS/FAIL + 输出关键行）、未做/跳过/遗留项、“留给后续”的发现。不得报总体完成如果任一 V 为 FAIL。

## 修订 R1（2026-09-22，发布者签发；执行方不得再自行扩大）

**触发**：首轮执行 V8 FAIL。执行方正确停止并汇报，未改测试。发布者已独立核实：
`tests/test_distribution.py:17` 维护一份独立的 `COPIED_FILES` 黄金元组，第 163 行与第 197 行
断言它必须与 `scripts/sync_context_strict_skill.py` 的 `COPIED_FILES` 完全相等。该黄金清单是
分发内容的独立期望（双人复核机制），新增分发文件时本就必须同步更新。原合同漏列该文件，
与“不修改测试”的禁止项冲突。责任在发布者。

**修订内容**：

1. 范围新增 `tests/test_distribution.py`，且**仅限**以下一处改动：在其 `COPIED_FILES` 黄金元组中，
   紧接 `Path("references/handoff.md"),` 之后插入一行 `    Path("references/bot-pipeline-handoff.md"),`。
2. 仍然禁止：修改该文件中任何 `assert*` 语句、删除或重排其他条目、修改任何其他测试文件。
3. V3 的期望文件列表由 9 个改为 10 个，新增 `tests/test_distribution.py`。
4. 新增 V13 / V13b（见下表）。
5. 提交处理：把该改动并入既有提交（`git commit --amend`，提交信息不变），保持“恰好一个新提交”，
   V12 的期望不变。仅当 HEAD 提交作者是本轮执行者、且未推送时才允许 amend。

| ID | 检查 | 通过标准 |
|---|---|---|
| V3（替换） | `git diff --name-only origin/main..HEAD` | 恰好 10 个文件：原 9 个加 `tests/test_distribution.py`。多一个或少一个都 FAIL |
| V13（新增） | `git diff origin/main..HEAD -- tests/test_distribution.py \| grep -c '^+'` 与 `\| grep -c '^-'` | 新增行计数为 `2`（含 `+++` 头），删除行计数为 `1`（仅 `---` 头）；即净增恰好一行，且该行为 `    Path("references/bot-pipeline-handoff.md"),` |
| V13b（新增） | `git diff origin/main..HEAD -- tests/test_distribution.py \| grep -E '^[+-]' \| grep -c 'assert'` | 输出 `0`（没有触碰任何断言语句） |
| V8（重跑） | 同原标准 | 末行 `OK` 或 `OK (skipped=N)`；0 failures，0 errors |
| V9、V10（重跑） | 同原标准 | 因提交被 amend、HEAD 改变，必须用新 HEAD 重跑 |

## 失败与停止条件

- `git checkout -b ... origin/main` 因未跟踪文件冲突而失败：不要 `git clean -f`。先确认 archive 提交已包含该文件，再删除工作树中该文件后重试。若 archive 未包含，停下汇报。
- V8 出现任何 failure/error：不修测试、不修源码，停下附完整失败输出汇报。
- V3 多出文件：查明来源；若是同步脚本额外生成，停下汇报，不得自行扩大提交范围。
- 任何步骤需要网络、sudo、修改 `~` 下文件：停下汇报。
