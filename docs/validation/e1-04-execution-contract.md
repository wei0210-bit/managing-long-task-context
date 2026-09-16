# E1-04 执行合同 v1：原有门禁组合与隔离旧包迁移

状态：#18经主控源码验收已关闭；本单#19验收与所有权先冻结。只完成E1，不进入E2+。Terra-high新上下文执行，主控独立审查。

## 基线与不可扩大范围

工作区 `/Users/zhaowei/Desktop/David/project.nosync/managing-long-task-context`，main HEAD `0f5898e19b4951c661edce1f7db80f95cc1b2ecc`，有已验收但未提交E1源码和用户文件，全部保留。
E1-03固定core SHA256 `c78af79aabb5fe130db217cc0f69ea4eaa055df37e69cae1d54b730d6b436a2f`，handoff `c8a459278158a18ff4e563a1cd69663e2c598b54f6236942d67184a5bc22ed9f`。主控63/63、root17/17+18/18+10/10；全回归459项458通过，唯一E2分发副本同步失败。不是全包发布通过。
固定E0输入manifest `435e407c064b32a7d5012e0161c9b2e7bddc38c8d70ce42e12659102e7f52a7b`；不得改expected、schema或测试输出伪造通过。
真实旧0.7.0完整包 `/private/tmp/mltc-review-baseline.GYDdVc/context-strict`，manifest `3d3e4f44b454adaa358d69c4e75eec4bbaa2ecedcb5d84abfdc6b34e33e50cc7`，source revision为上述Git HEAD；重新verify后才用于隔离Python进程。不是仅改一个版本字段的假旧包。
禁止安装、提交/合并/推送/部署、改生产、执行真实业务或新付费模型调用；不改distribution目录、E0输入、用户文件。真实Codex/Claude宿主迁移与禁止旧writer重启属于E3+，不得以合成宿主标host-level场景通过。

## 所有权及接口检查点

可新增 `tests/test_handoff_gate_combinations.py`、`tests/test_handoff_migration.py`、必要薄夹具 `tests/handoff_gate_fixtures.py`/`tests/handoff_migration_fixture.py`，自己的 `docs/validation/e1-04-executor-report.md`、`e1-04-executor-runs.json`。
源码和旧测试暂只读：发现真实缺口时先报具体公开输入/预期/实际/最小diff提案，主控裁决后才改既有源码，不能以扩写提示词、重造gate/adapter框架解决。使用已有gate/evidence resolver/policy及handoff API；不引入产品 `migrate_task`，它是E0测试动作名。
先提交简短fixture/矩阵消费提案后实施：三开关对应真实合同字段和实际调用；独立身份、业务证据、规则与Truth Sources如何真实验证；同一时钟；旧包隔离如何证明实际加载及当前process状态。禁止只读expected产生结果或把host自报JSON当核验。

## 冻结验收

1. E0-148～171共8组三开关×3场景逐项实际运行，24项，不跳过计绿。把truth_sources/rule_execution/independent_validation真正发布进合同并核对封印内容；每组valid具备可核查当前依据；invalid_basis缺承重依据；changed_after_check在完整检查回调后真实改依据再提交。检查check/commit、generation变化、events及旧业务gate，无静默关闭开关。
2. 接管成功不等于完成。每个valid组合在移交后调用原completion gate，充分真实合成证据可通过；剥除业务证据则必须阻断。另以完整的阻塞说明为接管依据，接管可pass但业务gate保持阻断；不把所有业务阻塞都当接管失败。
3. 至少专项覆盖模型自报pass、伪造checker结果/无实际核验、旧证据、失效或同主体独立验收；旧门禁依旧拒绝。复用已有专项fixture/public API，不重写证据解析器；条目/回执要关联当前合同、workspace、版本和真实临时内容。不能只做JSON形状测试。
4. 旧包迁移的本地机制类比在隔离目录/真实Python进程执行：实际旧包加载证明（module路径、manifest），旧writer活动、退出未知、观察后重启均不得启用协议；可信测试host实际观测该受控进程安全退出、且受控launcher不再允许该旧身份启动时，可仅prepare一次、代次不涨；重复相同请求不重复启用。所有进程有屏障/退出证明/always cleanup，不用sleep猜测。
5. 必须直面旧包不认识新fence：不能把当前库拒绝裸writer说成旧库也已被限制。证明原旧包仍能绕过新API的隔离风险时，保持真实宿主迁移关闭、明确E3+退出/防重启条件；不在本单造生产launcher。E0-172～177标为host-level，未做真实宿主适配时仍NOT_RUN，另列本地机制类比结果，不混淆层次。
6. 全部既有E1针对性、三套root probe及必要全回归无新失败；唯一E2分发差异继续保留。旧task无handoff保持行为，handoff失败无激活写入，合法child记录不被回滚。若源码已满足，只交覆盖证据，不为升级加代码。

## 验证和交付

隔离临时目录，真实文件与标准库Python，宿主明确synthetic；TDD以行为失败为红，缺API/导入不是有效红。输出每个matrix case的冻结ID、实际输入、预期与实测、事件/代次、业务gate、运行状态，不读取expected构造产品报告。历史红与修复后绿分开保存；临时路径无需泄露任何生产内容。
建议命令：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_handoff_gate_combinations test_handoff_migration -v`。
最终主控统一跑全部测试；小改只跑相关案例，不重复每次全回归。报告错误放行/阻塞数量及分母、程序重复一致性、真实进程/耗时/重试；模型原判/token/自然使用未知就写UNKNOWN，不把程序重复称模型稳定性。
完成本地可验证工作后停写，主控复验；需要E2+/真实宿主能力时报告边界，不要求用户反复“继续”，也不越权实现。既定E1范围的本地开发/验证完成与尚未开放的生产能力分开收口。
