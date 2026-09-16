# E1-03 执行者报告

冻结合同：v1.3，SHA256 `1b8aa9154f36e7495c27d598a3ea0bf666dc9fe599dbab18f7cb824ab2ee7e04`。

本执行者实现并测试了公开 activation/status seam、严格控制投影、控制事件原子发布、身份连续性及 AC5 增量核验。所有宿主均为本地 synthetic 注册对象；真实宿主、掉电、业务动作、模型/token 收益均为 UNKNOWN。

| AC | 本执行者证据 |
| --- | --- |
| 1–2 | target subject_session_ref、完整 verifier/authorizer、record/package/reference 短锁复核；bearing 变更为 unknown/not_attempted。 |
| 4 | controller 与 child 主体分离；child 仍受 work_item/scope/purpose 约束。 |
| 5 | `test_registered_child_progress_delta_can_cross_activation_verification` 通过真实 public `record` 保存 child 事件观测；缺 verify_delta、错误 digest、delta 后承重变化、blocking observation 四反例均不激活，合法 child event 不回滚。 |
| 7–8 | status 独立重放历史提交；连续两次 activate 0→1→2；取消后原 controller 可 prepare 新记录，错误 source/generation 拒绝。 |
| 6 | 已移交 process 执行者测试；其报告与测试为独立所有权，未在此重复声称。 |

本执行者最后命令：

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_handoff_activation -v`

实际：8 tests，退出 0，约 0.76 秒。`git diff --check` 退出 0。

验收时 SHA256：handoff `c8a459278158a18ff4e563a1cd69663e2c598b54f6236942d67184a5bc22ed9f`；core `c78af79aabb5fe130db217cc0f69ea4eaa055df37e69cae1d54b730d6b436a2f`；activation tests `f0c831ce6dca0139aaf26be03ae96fbba3ac61f157749bd1f49d2c48e9c3b49f`。

此前 59 项目标集已通过，但在本报告之后又新增 AC5 参数化反例，因此它不是最终全量验收；交主控进行一次独立完整回归。E2 分发差异未改。
