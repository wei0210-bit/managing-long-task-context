# E1-04 主控审查：门禁组合及旧包隔离机制

状态：2026-09-15 主控源码范围验收通过。E1 四单完成；不等于完整包可发布。只限 E1；不发布、不安装、不提交或改生产。

## 最终主控结果（两执行者停写后）

| 检查 | 实测 | 退出码 |
| --- | --- | --- |
| E1 全部针对性测试 | 72/72，8.646 秒（含矩阵 24 子案例，非额外 24 test methods） | 0 |
| 本单主控 C01–C04 | 4/4，0.095 秒 | 0 |
| E1-03 主控反例 | 17/17，0.760 秒 | 0 |
| E1-02 主控反例 | 18/18，0.349 秒 | 0 |
| E1-01 主控反例 | 10/10，0.053 秒 | 0 |
| 全回归（显式完整旧包，未 skip 迁移） | 468 项中 467 通过，38.661 秒；唯一 `test_distribution_matches_maintained_sources` 失败 | 1 |

唯一失败仍为 E1 core 与旧分发副本不同，由 E2 处理；没有新增回归失败。禁止同步副本求绿或将此报告称为全包发布验收。针对性与全回归并行执行，耗时不是独占性能基线。所有工具进程均已收取最终退出结果。

本单未改产品源码，仅新增测试/夹具/复验记录。源码 SHA 与 #18 一致；原 7 项用户文件 SHA 未变，main HEAD 仍为 `0f5898e19b4951c661edce1f7db80f95cc1b2ecc`；`git diff --check` 通过。无安装、提交、合并、推送、部署。

### 最终测试指纹

- `tests/test_handoff_gate_combinations.py`：`45202d0827cc3474212207e999e3ca95fab8a37d1db8419f42cbabf12cd0897d`
- `tests/handoff_gate_fixtures.py`：`b65522157b8ea2ca006f55736a96f9526c68203cdcc8c44c503ebb1b75b65b9e`
- `tests/test_handoff_migration.py`：`99fd03c8c25bd63112770f1c413bf3d7fcc9fcc485e580f20d15b5768b5f75e0`
- `tests/handoff_migration_fixture.py`：`2b645c0e4a6203425b807f3468b1e930e7d3748bc6b93742abf8517965351cd0`
- `docs/validation/e1_04_controller_probes.py`：`4d3f25702287df40b0c6d753e49bad60c223caed30b7ddeb7eab2891725b93f9`

### 判定与分母

- 矩阵接管：错误放行 0/16（依据丢失 8 + 核验后真实变化 8），错误阻塞 0/8（有效接管）。三开关均真正写入封印合同并检查。
- 业务完成：有效证据 8/8 允许；剥除证据 8/8 阻断；另有明确业务阻塞 1 项、伪造/缺失/同主体/过期验收 4 项均阻断。接管 pass 不等于业务完成。
- 独立主控 C01–C04：错误放行 0/4，错误阻塞 0/3；completion 查询保持日志不变。
- 本地迁移机制类比：错误放行 0/4，错误阻塞 0/2；另有旧库绕过风险复现 1/1，不与安全正例混算。主控另行单跑 6/6，1.024 秒。
- 同代码测试多次运行观察一致；属于合成确定性程序机制，不是独立模型稳定性。模型原始判断、真实 token/缓存/费用和自然任务收益 UNKNOWN。没有业务重试；重复 prepare 为特意设计的幂等性调用。

### 可复跑命令

```sh
MLTC_LEGACY_PACKAGE=/private/tmp/mltc-review-baseline.GYDdVc/context-strict PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_handoff_gate_combinations test_handoff_migration test_handoff_activation test_handoff_process_recovery test_handoff_writes test_handoff_concurrency test_handoff_protocol -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 docs/validation/e1_04_controller_probes.py -q
MLTC_LEGACY_PACKAGE=/private/tmp/mltc-review-baseline.GYDdVc/context-strict PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /opt/homebrew/bin/python3.12 -m unittest discover -s tests -q
```

换机器需指定实际 Python 及完整冻结 0.7.0 包路径。未提供 `MLTC_LEGACY_PACKAGE` 的迁移 class 显式 skip，不计为验证；提供错误包直接失败。旧包完整 45 文件由 setUpClass 调现有校验器核验，不只比较 manifest 自身。

E0 冻结文件仍保留原始 NOT_RUN；24 项等价状态映射的实际执行结果另存 [矩阵记录](e1-04-executor-runs.json)，不改写冻结输入。真实宿主级 E0-172–177 仍 NOT_RUN，[迁移记录](e1-04-migration-runs.json) 只表示隔离本地机制。

## 冻结依据

- E1-04 合同 SHA256：`4f33bb0f711e877d370b76faeae9ffa57d11fa661c0bf70f093602e5555e7624`。
- E0 manifest：`435e407c064b32a7d5012e0161c9b2e7bddc38c8d70ce42e12659102e7f52a7b`；本轮再校验 pass，0.028689 秒。此命令仅验证输入，不等于执行产品场景。
- 主控 C01–C04：[冻结预期](e1-04-controller-cases.md)，SHA256 `e4c9e5103b89f53715cf09e8195aed142d01c4b43af2815dd6c5ef88300ecfd5`。
- 源码延续 #18：core `c78af79aabb5fe130db217cc0f69ea4eaa055df37e69cae1d54b730d6b436a2f`；handoff `c8a459278158a18ff4e563a1cd69663e2c598b54f6236942d67184a5bc22ed9f`。

## 真实审查发现（不得改写为产品原本失败）

1. 组合夹具最初将显式 `validation_resolver=None` 替换为真实 resolver，将空 evidence_map 替换为有效证据，反例会失真。要求使用 sentinel / `is None`，主控直接公开调用 gate 绕过包装器。
2. 手写 E0 ID 与三开关组合错位。要求直接消费冻结 cases.json 的 stimulus，仅以 expected 做比较，不能从预期拼装产品回执。代次从 E0 7 映射到隔离夹具 0，明确比较增量，并非原始 ready-state 的逐字重放。
3. 迁移夹具原先直接写 safe status，要求在 authorizer 内按当前进程状态和登记计算，不依赖之前观察或自报状态。
4. 旧包仅校验 manifest 自身不够；复跑必须由已有包校验器完整验证。固定机器临时路径改为显式外部旧包参数，提供错误路径时失败，未提供时明确 skip，不能计绿。
5. 绕过证明不能仅检查历史中存在任意 item-recorded；必须对照 prepare 后新增事件及真实旧 child 的 item_id。

## 主控先行结果

`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 docs/validation/e1_04_controller_probes.py -v`

4/4，0.085 秒。接管成功后：缺独立 resolver、缺 rule runtime、空业务证据均阻断；待复核 Truth Sources 状态不会因接管而消失。三个完整正例允许完成；completion 查询不改 events，不重复激活。待两执行者停写后再进行最终复跑。

## 未验证与边界

真实 Codex／Claude 宿主 E0-172–177 仍 NOT_RUN。旧库不会理解新 fence，必须先有可信退出和防重启能力，不能直接启用真实迁移。完整分发包仍有 E2 同步依赖，不能称全回归全绿。模型原始判断、token、缓存及生产收益 UNKNOWN；本地程序重复不算模型稳定性。
