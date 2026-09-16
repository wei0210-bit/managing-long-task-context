# E1-03 主控复验（源码范围验收通过；E2发布保持阻断）

## 最终独立复验

两执行者已停写后，主控实际复跑以下命令（Python `/opt/homebrew/bin/python3.12`，`PYTHONDONTWRITEBYTECODE=1`；针对性和root脚本使用 `PYTHONPATH=src:tests`）：

| 命令主体 | 实际结果 |
|---|---|
| `-m unittest test_handoff_activation test_handoff_process_recovery test_handoff_writes test_handoff_concurrency test_handoff_protocol -q` | 63/63，7.294秒，exit0 |
| `docs/validation/e1_03_controller_probes.py -q` | 17/17，0.704秒，exit0 |
| `docs/validation/e1_02_controller_probes.py -q` | 18/18，0.341秒，exit0 |
| `docs/validation/e1_01_controller_probes.py -q` | 10/10，0.047秒，exit0 |
| `PYTHONPATH=src ... -m unittest discover -s tests -q` | 459项，458通过，37.384秒，exit1；仅预先声明E2分发副本同步失败 |
| `tests/handoff_spec.py tests/fixtures/handoff --expected-manifest-sha256 435e407c064b32a7d5012e0161c9b2e7bddc38c8d70ce42e12659102e7f52a7b` | 输入校验pass，0.029秒；180场景产品执行仍NOT_RUN |
| `git diff --check` | exit0 |

针对性与全回归并行运行，耗时不是无竞争性能基准。原7项用户文件hash再核对未变。完整旧0.7.0包再次校验45文件/16导出通过，manifest为 `3d3e4f44b454adaa358d69c4e75eec4bbaa2ecedcb5d84abfdc6b34e33e50cc7`。
源码/hash：core `c78af79aabb5fe130db217cc0f69ea4eaa055df37e69cae1d54b730d6b436a2f`；handoff `c8a459278158a18ff4e563a1cd69663e2c598b54f6236942d67184a5bc22ed9f`；activation tests `f0c831ce6dca0139aaf26be03ae96fbba3ac61f157749bd1f49d2c48e9c3b49f`；process tests `5b93b9f351c5619ffef360b8160b119f11586287a92094640d02e39169427a20`；root probes `2fa53df08fd668345b376efe0cb123ac7cdea4f55d812134d29a3b05a5fa2c19`。

AC1/2由独立注册目标、缺核验、假主体、时效及文件/包/record变化反例覆盖；AC3/6由11项真实Python进程套件（包括always cleanup和不同request竞争）覆盖；AC4由root目标/旧source/原child/取消child覆盖；AC5由真实public child写、独立delta观察、4个否定子例且合法进展不回滚覆盖；AC7由当前check与历史commit分离及20次只读、新进程恢复覆盖；AC8由两次0→1→2、历史查询与取消后新准备覆盖；AC9由既有门禁回归覆盖。E1-04将继续做特性组合及旧包迁移隔离验证，本单不冒充已完成后继。
root独立集内明确拒绝的终态子例19个，错误放行0/19；正常激活/幂等/大日志/目标写/child跨activate及cancel的6个正向观察，错误阻塞0/6。fixture setup不计，历史提交可读与20次查询另记，不把它们扩大为模型稳定性分母。真实模型原判/token/自然项目收益UNKNOWN。

结论：#18只按已冻结本地源码机制范围验收，可继续#19。不是全包绿，不安装/提交/合并/推送/部署；真实宿主、掉电、E0全量产品矩阵及经济收益仍未验证。以下保留全部中间失败与修复历史。

## 冻结输入与范围

执行合同 v1.2 SHA256 `eaa683e375ac8922a8ee0a16cf19a0dcc94468d9df6742daab927c76d2baee87`；九项验收不降级。主控独立案例 `e1-03-controller-cases.md`，初始hash `41ec9afca42eee69a4aea5384000e9b80fa79d3b03dd70b4640178e20ea79bfd`；初始8测试脚本 `e1_03_controller_probes.py`，hash `c249c1772e4bd0a9e5704db502415e11647d99f69ec3019348ccb503e0d221e0`。
全部为隔离合成机制验证，模型/自然项目/token/真实宿主身份均未运行。E2分发副本同步失败保留，不安装/提交/发布。

## 首个公开 activate 绿色检查点的独立复跑

命令：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 docs/validation/e1_03_controller_probes.py -q`
实际：8项，0.115秒，exit1，6通过/2失败；不是最终验收。

- A01：独立注册目标身份正常7→8、仅1激活、重复文件字节/mtime不变，通过。
- A02/A03/A04/A05：缺授权/核验器、非注册身份、错误主体引用/自填label/过期、核验后证据变、非法代次、重复错误工作区，现有子例通过。
- A06：激活后basis变化，当前unknown正确，但历史commit被错误清为unknown，失败。
- A07：激活后无verifier只读查询，当前unknown正确，但历史commit被错误清为unknown，失败。20次确定性查询不是模型稳定性证明。

两条失败送回执行者，保持原冻结预期，待状态分离实现后复跑。

## 旧断言准确化

主控实读 `tests/test_handoff_writes.py` 原 `test_any_activated_control_event_fences_direct_writes_before_authorizer`：输入是没有prepared的 HO-OTHER-001，而且代次未+1，属于非法控制历史，不是合法已激活状态。只将方法名改为 `test_unknown_handoff_activation_fences_writes_before_authorizer`、错误消息改为unknown handoff；原“authorizer零调用/事件不变/抛错”全部保留。合法activated目标写入由新测试证明，不能删除旧安全反例。

## 尚待核验

AC2 record自身在commit前重新读取；AC3真实竞争/幂等；AC4新旧controller与child；AC5可信增量及再变阻断；AC6真实进程中断/新进程恢复；AC7分离；AC8连续交接；全部回归。未经这些验证不结单、不派#19。

## 第二检查点与测试所有权

补齐原AC2/7内两项反例（record核验后变更、重复请求不以旧pass冒充当前有效），共10项，0.143秒，exit1，8通过/2失败。record变化已拒绝；缺verifier查询已保留已提交和正确代次8。仍失败：basis变更后的status误清提交事实；相同请求重放仍给旧check pass。保持预期，已送回修复。当前实现中间态，不与最终统计混计。
源码执行者确认移交尚未创建的 `tests/test_handoff_process_recovery.py`、`tests/handoff_process_fixture.py`、专用process报告给新 `/root/e1_03_process_tests`（Terra-high，无历史）；后者只验AC3/6真实进程边界，不修改源码。主控继续独立源码审查及根探针；共享核心仍单一writer。

## 第三检查点与真实故障红

主控复跑10项0.135秒全过；新增核验回执在commit时过期反例后11项0.265秒全过。只是这些机制子例通过，非#18验收。
独立进程执行者实测（主控待整套复跑）：fsync前OSError后子进程rc0、pass/confirmed_committed/gen1，fresh新进程也读成committed/gen1；`os.fstat(fd)`与events的dev/ino确认故障注入位置。完整换行已flush但尚未刷盘，可读被错误用作持久提交证明。
按主计划H12与最小内部实现边界，批准合同v1.3（hash `1b8aa9154f36e7495c27d598a3ea0bf666dc9fe599dbab18f7cb824ab2ee7e04`）：仅三控制事件在原锁内temp fsync再atomic发布canonical log，旧普通append不变，不新增状态库/schema。准确边界为发布前旧权威可读→确认未提交，发布后→确认提交；来源不明仍unknown。记录原反例与新实现测试分别计量，不将调整注入点伪装原实现通过。额外有界复制和回归待测，尚未实现验收。

## 第四检查点（仍未验收）

先后独立实证并修复：包manifest在host核验期间被改仍错误激活；合法child自己的session引用被错误要求等于controller。原预期保持，两个真实行为红留在调用记录中。主控当前16项，0.965秒，exit0；hash `7d777a9113a830652f625d04f7b4d62317b08431d1d9a52684a60ab39ed90f1e`。
新增原子发布预算边界：完整合法log为8MiB−64KiB可激活，8MiB满log因最终结果超限拒绝、任务文件不变。单独新Python运行前者0.328237秒，Darwin进程峰值RSS121,323,520 bytes；包含解释器、fixture构建、重复读取与测试，低于128MiB参考值，不是硬cap或Skill独立增量，不能与先前只读样本直接相减得收益。
主控真实进程独立复跑当时9项，8.563秒，exit0。随后执行者补了失败路径的always cleanup和不同request ID竞争，共11项；这些最新修改尚待主控最终整体复跑。两请求仍是同一合法synthetic target，不能称真实两个宿主身份认证完成。
待最后AC5增量可信正反例与取消后child连续性，再统一冻结源码/hash、执行全套最终复验。重复小改只跑相关单测，不每次重复整套子进程测试。

主控补取消后child原scope正例后17/17（0.641秒）；不以角色恢复为由撤销未撤销的子任务许可。AC5首个正例虽跑绿，代码审核发现 verify_delta 只反射request回执，未独立绑定本次public writer实际事件；因此**不接受该绿结果作为AC5有效验证**，要求保存实际前后log与确切event，再独立比对。另外要求程序先拒绝带blocking/blocker/supersedes的承重delta，不能靠host把它标成nonbearing。上述送回，不改验收标准。
