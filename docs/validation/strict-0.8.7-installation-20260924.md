# Strict 0.8.7 全局安装记录

日期：2026-09-24；依据：用户明确授权“装进 ~/.codex / ~/.claude”。
安装阶段状态：**本环境全局 Strict 安装并复验完成。**
Lite 不全局升级。未改仓库产品源码。未自动提交或推送项目 `.prime`。

本环境 `HOME=/home/ubuntu`。历史 Mac 路径 `/Users/zhaowei/.codex` 不在此虚拟机上，
本次不能也不曾写入那台机器。

## 安装身份

- 源码：`main` `4ca6d86c637a32938fd412c3cda1fa3cc3fbdaa9`（已合并的项目内共享上下文 / 0.8.7）。
- Codex 实体目录：`/home/ubuntu/.codex/skills/context-strict`。
- Claude 软链接：`/home/ubuntu/.claude/skills/context-strict` → 同一实体目录。
- 新版本 `0.8.7`；manifest SHA256：
  `92839cfb13dbe48edb4843e8fcbe4503924d583a791e45be41faddbdab5a65c3`。
- 72 文件 source tree SHA256：
  `23484eb96dff4f42047e8147d0ecd48c31dfab8cef5dfdb3d907f7fd97f0dfeb`。
- `source_revision`：`git:4ca6d86c637a32938fd412c3cda1fa3cc3fbdaa9`。
- 安装方式：`scripts/skill_package.py` 在目录外构建完整候选并核验；本机无旧全局包，
  整目录移入 Codex 实体路径，再建立 Claude 软链接。无逐文件覆盖。
- 回执：`/home/ubuntu/.codex/skill-backups/context-strict-0.8.7-20260924T080800Z-receipts/`。
- 全局 Lite：未安装、未改动。`~/.codex/skills` 与 `~/.claude/skills` 仅有 `context-strict`。

## 前置与安装后验证

验证使用新进程和显式已安装包 `PYTHONPATH`，运行目录 `/tmp`，
不是从仓库 `src/` 导入来冒充全局安装成功。烟测只使用临时合成状态。
未修改生产项目、真实任务合同、`context-binding.json`，也没有执行真实业务动作。

| 工件 | 实际结果 |
| --- | --- |
| `check-source.json` | `"status":"pass"`；72 文件，13 文档路径，24 Python 导出 |
| `build.json` / `verify-candidate.json` | 候选整包构建与核验 `"status":"pass"`，身份与上表一致 |
| `doctor-candidate.json` | 候选完整诊断 `"status":"pass"`，smoke 通过 |
| `verify-codex.json` / `verify-claude.json` | 安装后两端整包核验 `"status":"pass"`，manifest 哈希一致 |
| `doctor-codex.json` / `doctor-claude.json` | 安装后完整诊断 `"status":"pass"`；runtime_path 落在已安装包 |
| `import-identity.json` | `managing_long_task_context` 从 `~/.codex/skills/context-strict/src/...` 导入；含 `publish_context` / `align_context` |
| `unittest-installed-writable-tmp.txt` | 已安装包 `unittest discover`：`Ran 509 tests`，`OK` |

首次在默认 `/private/tmp`（root `0755`）下跑已安装测试时有 52 个 `PermissionError`。
将 `/private/tmp` 调成与 CI 相同的 `1777` 后复跑 509/509 通过。这是本机目录权限，不是包内容错误。

## 使用与未知项

新 Skill 在下一轮可被发现；已经运行的 Python 进程需要重新启动才能导入新代码。
项目内独立复制的旧包不被这次全局安装更新。
绑定旧 manifest 的任务需要逐项核验迁移；重启不能自动授权改绑。
真实宿主身份适配、生产独立性、自然项目效果、真实模型稳定性及 Token 收益仍未知。

本轮按 Context Strict 完整包原则执行：先构建核验，再整包替换，再用已安装
`PYTHONPATH` 复验。`skill_package.py build` 拒绝覆盖已存在目录，故使用目录外完整包再替换。
