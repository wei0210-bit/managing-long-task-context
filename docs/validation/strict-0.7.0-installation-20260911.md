# Strict 0.7.0 全局安装记录

日期：2026-09-11；依据：用户新授权“全局安装，提交部署”。
安装阶段状态：**全局 Strict 安装并复验完成。**
后续授权：用户已确认将已回归的前序依赖源码一并提交并推送 main，Lite 不全局升级。
下文未提交/待确认描述是安装结束时的历史快照，不是对后续发布状态的断言；
最终提交和远程读回凭据另存 `.scratch/strict-release-20260911/`，以实际 Git 记录为准。
本记录不改写上轮本地修复报告的历史边界。

## 安装身份

- Codex 实体目录：`/Users/zhaowei/.codex/skills/context-strict`。
- Claude 现有软链接：`/Users/zhaowei/.claude/skills/context-strict`，指向同一实体目录，未重建。
- 新版本 `0.7.0`；manifest SHA256：
  `7129fe28a04e6a010623fca82a1967cbd05ceff077f751c4dfe34751dcd525a3`。
- 45 文件 source tree SHA256：
  `4d1ded220b2af13d753f029d3cb3251eb9aebf76310411f00fc63b73c3138bb9`。
- source_revision 为实际本地候选身份
  `local:strict-independent-validation-20260911-final-review-fix`，不是尚未产生的 Git 提交。
- 安装方式：完整候选先复制到目录外暂存并核验；旧目录重命名为备份，再替换完整新目录。
  无逐文件覆盖；已安装后的诊断失败时安装脚本会恢复旧目录，本次未触发回滚。
- 旧版 `0.6.0` 完整备份：
  `/Users/zhaowei/.codex/skill-backups/context-strict-0.6.0-20260911-release`。
  备份 manifest 仍为 `cbb8b1beff19e5a58c095c947d4bf1713a528b8a25082e019a015bd867d9f92f`。
- 全局 Lite 仍为 `1.2.0`，前后完整包核验均通过，同一 manifest：
  `7a6f2f1d6d2314cce8607b59f4ac05777b0cd032a115b0f1a811edbaac4c1252`。

## 前置与安装后验证

冻结验收和替换脚本在 `.scratch/strict-release-20260911/`。
原始 argv/cwd/退出码/输出在 `.superpowers/sdd/strict-independent-validation/`：

| 工件 | 实际结果 |
| --- | --- |
| `release-preflight-identity.json` | 已审核16个集成哈希、Strict45文件、冻结规格/审查、Lite11源码文件一致 |
| `release-preflight-tests.json` | 363/363，0跳过，26.670秒 |
| `release-historical.json` | 原Git目录历史兼容1/1，0.142秒；合计364项不同测试 |
| `release-preflight-doctor.json` | 安装前候选完整诊断及正反例烟测通过 |
| `release-install.json` | 新旧整包核验、Codex完整doctor、公共16测试、三分支示例、Claude完整doctor全部通过 |
| `release-lite-before.json` / `release-lite-after.json` | 全局Lite完整包hash未变 |

安装后验证使用新进程和显式已安装包 PYTHONPATH，运行目录 `/private/tmp`；
不是从仓库源码导入来冒充全局安装成功。烟测只使用临时合成状态。
未修改生产项目、真实任务合同、context-binding.json，也没有执行真实业务动作。

## 提交与发布边界

本地 `main` / HEAD `3e954ebaf484f79dffd897079bdee012529dd9a3` 未改变，index为空。
只读核实远程 `wei0210-bit/managing-long-task-context` 仍为 private，默认 `main`，
远程 main 同为该 SHA；本次尚未 push，也没有创建公开release或发布至包注册表。
仓库无已确认的应用/服务器部署入口；本次部署解释为全局Skill安装及批准源码发布。

待确认：完整 Strict 0.7.0 依赖前序经验库/规则执行改动，同步脚本与 Lite 前序源码联动。
没有将这些改动擅自全部提交，也没有仅提交本轮局部文件而制造缺依赖版本。
散落 ` 2` 副本、观察草稿、项目任务状态和临时证据不默认纳入。

## 使用与未知项

新 Skill 在下一轮可被发现；已经运行的 Python 进程需要重新启动才能导入新代码。
项目内独立复制的旧包不被这次全局安装更新。
绑定旧 manifest 的任务需要逐项核验迁移；重启不能自动授权改绑。
要求独立验收的旧合同若缺可信宿主回执，将按新门禁阻断。
真实宿主身份适配、生产独立性、自然项目效果、真实模型稳定性及 Token 收益仍未知。

本轮按 Context Strict 完整包/身份原则和 finishing-a-development-branch 的新鲜回归门槛执行。
skill-installer 的下载脚本不支持覆盖已存在目录，故使用本地已审核完整包及可恢复替换，
不从远程下载一个未验收的不同版本。
