# 升级验证补充（2026-09-10，C20 执行前冻结）

不改变原 19 项 gold。新增 C20：模型 envelope 的 repo_revision 与合同一致，
但实际隔离工作区 HEAD 已移动，预期 unknown，不允许完成。
检查器必须实际读取工作区 Git HEAD，不能用 envelope 的版本字段自证。
fixtures 使用固定 author、时间、内容创建隔离 Git 仓库，两组使用相同输入；禁止任何远程操作。

测量修正：最初 C04 的 PermissionError 注入遗漏了 macOS 临时路径的真实路径解析；
修正为 resolve 后比较，再执行基线。最初输出不计有效基线。
基线与候选还统一了生成时间和时间观察边界；最终机器结果只使用这套固定输入。
这两处修正没有修改 gold，不能用早期探索结果和最终候选混算收益。

旧核心测试中，缺失时间、删除证据、过期/范围不符的 fail 断言按用户明确要求迁移到 unknown；
保留 passed=false 和原始错误码，同时验证 raw_status=fail。不是把阻断改成放行。
