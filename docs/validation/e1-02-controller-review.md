# E1-02 主控复验（本地源码阶段验收通过）

主控独立案例先冻结在 `e1-02-controller-cases.json`；只在临时目录运行，不接真实宿主、不执行业务、不计模型稳定性。#18 仍阻塞。

最新状态：2026-09-15T09:32Z，E1-02 源码机制验收通过，允许进入 #18；以下过程中的“未验收／阻塞”是保留的历史。完整包发布仍阻塞于 E2，非全仓全绿。

## 开发中行为红：直接写约束尚未接入

命令：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 docs/validation/e1_02_controller_probes.py -q`

实际第二次运行：7 项测试、0.173 秒、退出 1、9 个 subtest/测试失败。W04 每个入口使用新的隔离任务，防错误接受后的状态污染后续案例；第一次试跑未隔离所有入口的结果不用作独立分母。

- W01、W02、W03、W07、W08 通过当时实现下的探针；不是最终集成验收。
- W04：publish_contract、record、checkpoint 未抛异常；其余 5 入口因不存在的 item／未声明 truth source 阻断，但不是 HANDOFF 身份门禁，因此不能算 fencing 通过。原始断言：`ContextError not raised` 或 `'HANDOFF' not found in ...`。
- W10：已有 prepared 工件但移除该临时任务权威日志后，record 未抛异常，发生不应接受的旧模式写入。原始断言 `ContextError not raised`。
- W05/W06/W09 的正式主控运行待合法 child／cancel seam 完成，不计入上述运行数量。

这是执行者正在实现中的已有缺口，不是对未交付代码的最终缺陷率。主控不放宽预期；待写入钩子完成后复跑。错误放行计量仅能确认上述 3 个直接写成功及缺日志后 1 次写入；其他 5 个入口不是成功写入，不能误报为全部 8 个错误放行。

## 首单正例的兼容演进

主控修改 `test_handoff_protocol.py` 的两条 prepared 后裸写正例，添加 `handoff_test_authority.py` 中独立合成 child policy。身份使用注册对象，核对实际授权文件内容、固定任务/合同/代次/存储，许可仅覆盖原两个测试的 observation statement 和已登记 item ID；不反射任意调用为 pass。原有“可继续进展”和“宿主核验不持写锁”断言不变。变更不追改 E1-01 历史验收 hash。

## 接口审核的修正

主控拒绝将 prepare 内容检查简化成两个 pass 字段，要求复用 #16 完整核验结构和真实内容正反例。执行者的首次缺函数红仅记 API scaffold 缺失，不算行为红。所有 authorizer 在锁外，cancel 后保留协议身份约束，独立 policy 必须收到 normalized arguments 而不只是 digest。

## 写入口接入后的独立复验

执行者通知接口稳定后，主控独立运行新 probes 13/13（0.157s）、原首单套件28/28（0.554s）、原独立探针10/10（0.048s），均退出0。不是最终验收，剩余AC仍在执行者补测。

继续按既有 AC5/8 检查发现两处真实错误放行，先写公共 seam 反例再运行：

- W08b：合法 child 本次 authorizer 读取授权后改变已存 record.controller_generation，返回旧观察；事实文件未改变但交接记录已不匹配，直接 record 未拒绝。
- W10c：prepared 权威事件保留，交接目录移至同一隔离目录的其他名称，snapshot 恢复为 prepare 之前的缓存；裸 record 仍接受。旧缓存不能证明协议从未启用。

两项预期均为 ContextError、无新增事件，不引入新的控制策略。15测试运行0.154秒、退出1、13通过2失败，两项均为 `ContextError not raised`。只说明新构造的2个负例错误接受2/2，不是总体错误率。已回交执行者修复，#17未验收、#18仍阻塞。

两项修复后主控第二次稳定复跑15/15（0.181s）；全回归434项31.345秒，433通过，仅E2分发比较失败。该计数包括并发模块导入TestCase造成4项重复发现，已通知执行者改用模块导入，不能计为4项不同新覆盖。之后新增W05b：取消后模拟不一致宿主结果 `role=child,purpose=contract_publish`，程序必须拒绝；16项0.215秒全部通过。W05b首次运行已通过，没有声称捕捉到行为红。写入故障、竞态和剩余原AC尚待最终交付，#17仍未验收。

## 最终复验发现提交恢复分支绕过输入检查

执行者首次完整交回后，主控目标42/42（0.718s）、独立17/17（0.321s）、首单独立10/10（0.047s）。进一步按原AC7实测：正常prepare一次后，保持record/request_id、将调用参数workspace_root改为另一个真实临时目录、不传authorizer/verifier；返回 `pass / confirmed_committed`。这不是新增副作用，但把不同输入错误放行了。

原因是输入校验错误也进入历史提交恢复。已通过同一执行者窄修：只有本次完成校验并真正进入commit hook后的异常才可恢复；校验失败不得借历史成功变pass。要求保留fsync后snapshot失败的恢复正例，并加prepare/cancel错workspace/package负例。主控W03b已固定，#17尚未结单。

## 最终独立验收（最后窄修复之后）

执行者已由宿主确认 completed 并停止写入；主控独立运行：

| 检查 | 实际终态 |
|---|---|
| E1-02 自有＋首单目标集 | 44/44，0.775 秒，退出0；16个自有测试＋28首单测试，无导入TestCase造成的重复计数 |
| E1-02 主控公开入口探针 | 18/18，0.346 秒，退出0 |
| E1-01 主控独立探针 | 10/10，0.050 秒，退出0 |
| 全回归 | 440项，31.954秒，退出1；439通过，唯一 `test_distribution_matches_maintained_sources` 的核心源码／分发副本比较失败 |
| E0 manifest固定校验 | 输入pass，0.028秒，退出0；产品矩阵/模型/自然使用仍NOT_RUN |
| 新鲜Darwin进程、完整合法8MiB三点fixture | 1测试包含3点，0.199秒，峰值RSS 68,878,336 bytes；低于128MiB测量预算，不是内存硬限额 |
| diff格式 | `git diff --check` 退出0 |

复跑命令沿用执行合同及上文。RSS方法同E1-01：新Python进程只运行合法日志8MiB三点，取 `resource.getrusage(RUSAGE_SELF).ru_maxrss`（Darwin bytes）。未运行真实模型，token、缓存成本、模型重试成本均 UNKNOWN；业务动作0。

18项主控方法内的终态断言：26个指定负例/子例错误接受0/26；6个正向观察错误阻塞0/6（正常prepare、同请求幂等、cancel、合法child进展、两个legacy边界追加）。准备夹具的前置成功不重复计入分母；多个断言不是多个模型执行。先前2/2和错workspace的错误放行保留历史，不以本次0覆盖。

AC1–9依据逐项核对执行者报告和源码，再以上述独立运行验证。核心增加的是薄入口、写前/锁内复核及严格读取/提交复用；运行编排留在handoff模块。原来的两个裸writer正例升级为独立合成child身份，不删安全断言。重复JSON、旧snapshot、缺目录、错误权限及恢复掩盖错误输入等发现均有明确拒绝证据。

范围结论：本单准备／取消和八入口约束符合本地源码合同，允许后继开发；E2分发失败是原合同预先保留的阶段依赖，不修改它、不称全绿。完整激活、连续多轮交接、激活后的当前主控/child身份关系及真实新进程恢复由#18承担，不能用本单结果声称这些已实现。真实宿主、自然项目、收益和生产启用均未验证。

验收时SHA256：

- core：`4dcac6ed1a40c348adf5cc050f86f61ec782c7817541a44995407e8e56c8824f`
- handoff：`c9ddf7e010a6c95c28d5df12d9e4d0c94fb6eb8029d3a03b667a06e701d1bd1c`
- writes tests：`e069f47bd82253e6bbc35e4ba4bdd6591c54bc440b8528c255ffa1e3fd0204d5`
- concurrency tests：`87de8df694fac1498b5b9449f6c98df34ca85e05cbb586c1542480fd527256dd`
- root probes：`c2f7e1bbb593a58633d08a0e8d84bfeaec7c43bc4c83d926cf13c35f5b485dd5`

原7项用户文件再次逐项shasum均与原值一致。未安装、未提交/合并/推送/部署。后继修改不追改本次历史hash。
