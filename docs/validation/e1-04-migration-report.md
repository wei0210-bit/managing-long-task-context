# E1-04：真实旧包隔离迁移本地机制验证

时间：2026-09-15。范围仅限临时目录、标准库 Python 子进程与已冻结的旧包；未安装、未提交、未合并、未推送、未部署，未调用模型、真实业务或真实 Codex／Claude 宿主。

## 冻结输入与方法

在每次运行前以当前工作区的 `scripts/skill_package.py verify` 核验：

- package：`/private/tmp/mltc-review-baseline.GYDdVc/context-strict`
- manifest SHA-256：`3d3e4f44b454adaa358d69c4e75eec4bbaa2ecedcb5d84abfdc6b34e33e50cc7`
- package/skill version：`0.7.0`
- source revision：`git:0f5898e19b4951c661edce1f7db80f95cc1b2ecc`
- verify：通过，45 个文件、10 个文档路径、16 个 Python exports。

测试使用当前 `sys.executable` 加 `PYTHONPATH=<verified-old-package>/src` 独立 import。运行者必须通过 `MLTC_LEGACY_PACKAGE` 显式提供完整旧包；缺失时仅本文件的旧包测试 skip，路径/manifest 错误则 fail。`setUpClass` 另调用现有 `skill_package.py verify`，要求完整 45 文件核验通过。父测试核对 child 的 PID 与 `Popen.poll()/wait()`；child 输出的 `module.__file__` 位于该旧 `src`，且自己计算的 manifest SHA 与冻结值一致。FIFO 只用于已观察 phase 的屏障，未用 sleep 推测时序。child 创建后立即注册 `addCleanup`，清理顺序为 kill（如仍存活）→ wait → stdout reader join → pipe close。

`prepare_handoff` 是被测 current core 的唯一写入口。所有负例均实际调用它；测试 host 的 `authorize()` 在回调当下从父进程保存的 PID、`poll()` 与受控 launcher 登记重新观察，并在不满足条件时拒绝 grant。source／target／authorization/basis/artifact 均为同一临时 task scope 的真实文件和 SHA，不从 request 回显 pass。

## 结果

| E0 ID | 刺激与父进程实测 | host 判定 / core 实测 | 事件与代次 | 本地机制结论 |
| --- | --- | --- | --- | --- |
| E0-172 writer_active | 真实旧 child 已加载，PID 仍 `poll=None`，FIFO 未释放 | host `fail`；实际 public `prepare_handoff` 为 `unknown`，未获 grant | prepared=0，generation=0 | 不启用 |
| E0-173 exit_unknown | child 已 `wait()` 为 0，但无可信退出／防重启条件 | host `unknown`；public prepare `unknown` | prepared=0，generation=0 | fail-closed，不启用 |
| E0-174 writer_restarted | PID-A 已 0；同 identity 被受控 launcher 实际启动为 PID-B，`poll=None` | host `fail`；public prepare `unknown` | prepared=0，generation=0 | 观察后重启仍不启用 |
| E0-175 direct_api_invalid_identity | child 退出为 0 且 launcher 已登记封禁；传入未登记 runtime identity | host `fail`；public prepare `unknown` | prepared=0，generation=0 | 安全退出不替代身份绑定 |
| E0-176 verified_safe_migration | child `wait()==0`，launcher 在该观察后封禁同 identity | host `pass`；public prepare `pass / confirmed_committed` | prepared=1，generation=0 | 仅本地机制类比中可 prepare |
| E0-177 duplicate_migration | 对同一 request 重调 public prepare | `pass / confirmed_committed` 的幂等回执 | prepared 仍为1，generation仍为0 | 无重复启用 |

补充隔离风险：先按 E0-176 在 current core 写入 prepared，再启动一个**不经测试 launcher**的真实旧 0.7.0 Python child。该 child 的实际 `legacy.record()` 返回 pass，且 current events 出现 `item-recorded`。这证明旧包不认识新 fence；它不是“当前库拒绝裸 writer”的替代证明。受控 launcher 仅能拒绝通过它自己的启动请求，不能构成产品／OS 级防重启承诺。

首个定向运行曾有 1 个夹具失败：测试错误地要求已经封禁的受控 launcher 仍启动“绕过风险” child。修正为明确不经 launcher 的独立旧 child 后，源码未修改；这不是产品红例或源码缺口。完成回调时独立计算 PID／拒启／登记身份与完整包复核后，两次定向运行均为 6/6 通过，分别 1.068 s 和 1.049 s。没有 `MLTC_LEGACY_PACKAGE` 时仅本组 class skip（0 cases，skipped=1）；这不构成迁移验证。`git diff --check -- tests/test_handoff_migration.py tests/handoff_migration_fixture.py docs/validation/e1-04-migration-report.md docs/validation/e1-04-migration-runs.json` 退出 0。

## 层级与未决边界

E0-172～177 的 `required_test_level` 仍是 `host`，因此六项 E0 原始场景均为 **NOT_RUN**。本报告的结果只叫“local mechanism analogy”，不能证明真实 Codex／Claude 的退出观察、身份登记、旧 writer 禁重启或迁移能力；这些仍是 E3+ 宿主适配门槛。模型原判、token、自然使用均为 **UNKNOWN**。未以本地 Python 重复推断生产稳定性或成本收益。
