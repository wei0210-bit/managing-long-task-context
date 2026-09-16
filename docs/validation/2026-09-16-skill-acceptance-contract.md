# 隔离包使用验收（运行前冻结）

日期：2026-09-16。范围：现有 review-fix Strict 0.8.0 / Lite 1.4.0 完整候选。
只新增本地验证工件，不改产品、不全局安装、不提交/推送，不调模型或业务接口。
所有动态记录均为明确的合成案例，在临时目录执行；不是自然项目证据。

## 验收及预期

1. 两包 manifest 与上一轮持久收据完全一致；每个分发文件与候选源码一致；完整 verify / doctor 均 pass。不符则停止使用该包。
2. Lite：flush → 显式绑定 → 新进程 cold-check，正确提取目标、阻塞、First action 与 unknown 在途项；semantic_verification 必须 pending，archive_allowed 必须 false。
3. Lite：同一输入重复读取三次 material 一致，NOW 字节不变；仅证明程序一致性。
4. Lite：错误 NOW hash、错误工作区、缺失 NOW 均不返回 material；未知在途动作不重试。
5. Lite：原件改变而 NOW 不变时，cold-check 仍只是材料读取，不应声称已核验原件。此案例揭示语义观察仍须执行者落实，不算自动 stale 门禁。
6. Strict：完整包公开示例 prepare → validate → activate，以及 cancel 通过；重复 activate 不追加事件。宿主为固定合成注册表，不是 Codex/Claude 接管。
7. 既有包内 handoff activation / records / CLI / 两种 native，以及 Lite handoff 测试均无失败、无跳过。CLI 执行假命令夹具；native 控制仍 unknown。

## 计量及判断

逐命令保存 argv、cwd、退出码、stdout、stderr、单调时钟耗时；记录完整包hash。
动态 Lite 返回码预计为：正常0；坏hash2；错工作区1或2；缺失NOW1或2。
错误放行/阻塞仅按本轮公开路径的材料释放案例统计，不能外推为任务完成率。
真实模型判断、冷启动复述、实际token、缓存计费、生产可靠性均 NOT_RUN/UNKNOWN。
无新产品差异时不重复全量561项；定向包内验证用于此次验收，旧全量证据保持原日期。
