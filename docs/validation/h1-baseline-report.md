# H1 基线归档与 0.8.2 移植执行报告

执行代理：sonnet-xhigh-executor。执行时间：2026-09-22。

## 一、开工前状态

| 项目 | 值 |
|---|---|
| HEAD（local main） | `0f5898e19b4951c661edce1f7db80f95cc1b2ecc` |
| origin/main HEAD | `f61eabb449e6e2a831472170240578326a936c8f` |
| git status 变更文件数 | 155 |
| 当前分支 | main |

## 二、各步实际执行命令

### 步骤2：归档

```
git checkout -b archive/main-worktree-0.8.1-snapshot-20260922
git add -A -- . ':!.claude' ':!.cursor' ':!.prime' ':!.venv' ':!.superpowers'
git rm --cached .DS_Store
# 追加：git rm -r --cached .superpowers（用 GIT_INDEX_FILE 临时索引 + git commit-tree 修正）
git commit -m "archive: main worktree snapshot before rebasing 0.8.1 delta onto origin/main"
```

**注**：`.superpowers/sdd/...` 已在 origin/main 中跟踪，git add 的 `:!.superpowers` 路径排除无法阻止它。后用 GIT_INDEX_FILE + commit-tree 方式重建 archive 提交、移除 `.superpowers`，使 V1c=0。

### 步骤3：切换工作分支

```
git checkout -b codex/strict-0.8.2-usage-hardening origin/main
```

### 步骤4：恢复只读材料

```
git restore --source=archive/main-worktree-0.8.1-snapshot-20260922 --worktree \
  -- docs/validation docs/superpowers/plans/short-session-handoff.md CONTEXT.md \
  SESSION-HANDOFF-20260916.md 方案对话内容.txt references/bot-pipeline-handoff.md
```

**偏差**：origin/main 中已跟踪的 `docs/validation/2026-09-16-*.md`、`CONTEXT.md`、`docs/superpowers/plans/short-session-handoff.md`、`docs/validation/real-project-*.md` 被 archive 内容覆盖，导致 V8 中 `test_scn_02`、`test_reg_09` 失败。随后执行 `git restore` 恢复这些 tracked 文件到 HEAD，修复了这两个测试的失败。

### 步骤5：移植

1. `git add references/bot-pipeline-handoff.md`
2. Python 脚本修改 `SKILL.md`：description 两处措辞；Hard stops 之前插入 Multi-bot 节
3. Python 脚本修改 `skill-package.json`：版本 0.8.2；required_paths 加入 `references/bot-pipeline-handoff.md`（在 `references/handoff.md` 之后）
4. Python 脚本修改 `pyproject.toml`：version = "0.8.2"
5. Python 脚本修改 `scripts/sync_context_strict_skill.py`：COPIED_FILES 加入 `Path("references/bot-pipeline-handoff.md")`（在 `references/handoff.md` 之后）

### 步骤6：运行同步脚本

```
/opt/homebrew/bin/python3.12 scripts/sync_context_strict_skill.py
```
输出：`Synchronized Context Strict to .../skills/context-strict`

### 步骤8：提交

```
git add SKILL.md skill-package.json pyproject.toml scripts/sync_context_strict_skill.py \
  skills/context-strict/SKILL.md skills/context-strict/skill-package.json \
  skills/context-strict/pyproject.toml skills/context-strict/references/bot-pipeline-handoff.md
git commit -m "feat: port bot-pipeline handoff reference onto main and bump to 0.8.2"
```

提交哈希：`5665eef7e63871f52d44616b34e9134e76211bbb`

## 三、V1–V12 逐项结果

| ID | PASS/FAIL | 关键输出 |
|---|---|---|
| V1a | **PASS** | `5a0b19e archive: main worktree snapshot before rebasing 0.8.1 delta onto origin/main` |
| V1b | **PASS** | `3`（三个 ' 2' 文件在 archive 中） |
| V1c | **PASS** | `0`（无本地状态/缓存目录；archive 提交经 commit-tree 修正移除 .superpowers） |
| V2 | **PASS** | `ok` |
| V3 | **PASS** | 恰好 9 个文件：SKILL.md、pyproject.toml、references/bot-pipeline-handoff.md、scripts/sync_context_strict_skill.py、skill-package.json、skills/context-strict/SKILL.md、skills/context-strict/pyproject.toml、skills/context-strict/references/bot-pipeline-handoff.md、skills/context-strict/skill-package.json |
| V4 | **PASS** | `no diff`（__init__.py 与 origin/main 完全一致） |
| V5 | **PASS** | `3`（三个 ' 2' 文件均不存在于工作树） |
| V6 | **PASS** | SKILL.md:1、skills/context-strict/SKILL.md:1；`Session migration: one mode` 保留 1 次 |
| V7 | **PASS** | `0.8.2 0.8.2 True` |
| V8 | **FAIL** | `Ran 665 tests in ~94s — FAILED (failures=2, skipped=1)` |
| V9 | **PASS** | context-lite 和 context-strict 的 check-source/verify/doctor 均 `"status": "pass"`；context-strict skill_version=0.8.2 |
| V10 | **PASS** | context-strict: Ran 496 tests OK；context-lite: Ran 64 tests OK |
| V11 | **PASS** | `git status --porcelain \| grep -v '^??' \| grep -v '.DS_Store'` 无输出 |
| V12 | **PASS** | 未推送（`git branch -r --contains HEAD` 无输出）；恰好 1 个新提交（wc -l = 1） |

### V8 失败详情

**失败原因**：合同内部矛盾——禁止修改测试 × 要求向 `scripts/sync_context_strict_skill.py` 添加 `bot-pipeline-handoff.md` × V8 必须通过，三者不可同时满足。

**两个失败用例**：
1. `test_copy_lists_match_and_include_each_truth_source_file_once` (test_distribution)
2. `test_dist_02_preflight_is_listed_exactly_once_in_independent_and_sync_lists` (test_distribution)

**失败根因**：`tests/test_distribution.py` 硬编码 COPIED_FILES 黄金集，以 `assertEqual` 断言与 `scripts/sync_context_strict_skill.py` 中的 COPIED_FILES 相等。我们在 sync 脚本中添加了 `references/bot-pipeline-handoff.md`，但测试黄金集未更新（合同未将 `tests/test_distribution.py` 列入允许修改范围，且明确禁止修改测试断言）。

**关键输出**：
```
AssertionError: Tuples differ at element 18:
PosixPath('references/host-codex-cli.md') != PosixPath('references/bot-pipeline-handoff.md')
Second tuple contains 1 additional element.
FAILED (failures=2, skipped=1)
```

**包外 V10 测试（560 项）通过**：包外测试不使用根目录的 `tests/test_distribution.py`，因此均通过。

## 四、未做/跳过/遗留项

1. **V8 = FAIL（未解决）**：合同未将 `tests/test_distribution.py` 列入修改范围，无法在不修改测试的前提下使 V8 通过。需要调度会话修订合同，将 `tests/test_distribution.py` 加入允许修改范围并更新其 COPIED_FILES 黄金集，然后重新执行 V8。

2. **archive 分支修正说明**：archive 分支 commit 从 `88c37a1` 修正为 `5a0b19e`（通过 commit-tree 移除 `.superpowers` 目录），这是实现细节调整，结果符合合同 V1 验收标准。

3. **步骤4 副作用**：`git restore --source=archive --worktree -- docs/validation` 覆盖了 origin/main 中已跟踪的多个文件（2026-09-16-* 等），需要额外执行 `git restore` 还原。合同步骤 4 的 git restore 命令范围过宽，建议后续仅 restore 非 origin/main 已跟踪的文件。

## 五、留给后续（首轮；已被 R1 关闭）

- `tests/test_distribution.py` 的 COPIED_FILES 黄金集需要更新，加入 `Path("references/bot-pipeline-handoff.md")`，放在 `Path("references/handoff.md")` 之后。这是唯一能使 V8 通过的路径，需调度会话授权修改该测试文件。

## 六、修订 R1 执行记录（2026-09-22）

执行代理：sonnet-xhigh-executor。发布者已签发 R1，允许且仅允许同步 `tests/test_distribution.py` 黄金元组一行。

### 现场确认

- 开工时 HEAD：`5665eef7e63871f52d44616b34e9134e76211bbb`（未推送；`git branch -r --contains HEAD` 无输出）。
- 作者：`wei0210-bit <wei850210@gmail.com>`（上一轮执行者）。
- 工作树已有且仅有一行未提交改动：在 `Path("references/handoff.md"),` 之后插入 `Path("references/bot-pipeline-handoff.md"),`。未再改该文件，未改任何 `assert*`。
- `git diff` 仅此一行；`plus=2`（含 `+++` 头）、`minus=1`（仅 `---` 头）；`assert` 触碰计数 `0`。

### 提交处理

```
git add tests/test_distribution.py && git commit --amend --no-edit
```

- 未使用 `--no-verify`。未推送。未改 git config。
- 新 HEAD：`c9e9932216d050eb09dfd9d0cb9ee4412c55f204`
- 提交信息保持：`feat: port bot-pipeline handoff reference onto main and bump to 0.8.2`
- 工作树提交后只剩 `??` 只读材料与 `.DS_Store`。本报告保持未跟踪，未加入提交。

### R1 后 V1–V13b 逐项结果

| ID | PASS/FAIL | 关键输出 |
|---|---|---|
| V1a | **PASS** | `5a0b19e archive: main worktree snapshot before rebasing 0.8.1 delta onto origin/main` |
| V1b | **PASS** | `3` |
| V1c | **PASS** | `0` |
| V2 | **PASS** | `ok` |
| V3 | **PASS** | 恰好 10 个文件：原 9 个加 `tests/test_distribution.py` |
| V4 | **PASS** | `no diff` |
| V5 | **PASS** | `3` |
| V6 | **PASS** | SKILL.md:1、skills/context-strict/SKILL.md:1；`Session migration: one mode` 保留 1 次 |
| V7 | **PASS** | `0.8.2 0.8.2 True` |
| V8 | **PASS** | `Ran 665 tests in 95.332s` / `OK (skipped=1)` |
| V9 | **PASS** | context-lite / context-strict 的 check-source、verify、doctor 均 `"status": "pass"`；context-strict verify `skill_version`=`0.8.2`；source_revision=`git:c9e9932216d050eb09dfd9d0cb9ee4412c55f204` |
| V10 | **PASS** | context-strict: `Ran 496 tests in 57.380s` / `OK`；context-lite: `Ran 64 tests in 8.437s` / `OK` |
| V11 | **PASS** | `git status --porcelain \| grep -v '^??' \| grep -v '.DS_Store'` 无输出 |
| V12 | **PASS** | `git branch -r --contains HEAD` 无输出；`git log origin/main..HEAD --oneline \| wc -l` → `1`（`c9e9932 feat: port bot-pipeline handoff reference onto main and bump to 0.8.2`） |
| V13 | **PASS** | `^+` 计数 `2`；`^-` 计数 `1`；净增一行 `    Path("references/bot-pipeline-handoff.md"),` |
| V13b | **PASS** | `assert` 触碰计数 `0` |

### R1 未做/跳过/遗留

- 无跳过的合同验证项。
- 未推送。未安装。未改 `~/.codex` / `~/.claude`。
- 首轮遗留的 V8 黄金清单不同步已由 R1 关闭。
