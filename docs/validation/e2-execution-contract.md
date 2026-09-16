# E2 执行合同 v1.1：完整包身份与源码树外接续

用户在 E1 收口后明确授权“E2开始”。沿用已审核 E2 单票范围与公共边界，不重新设计协议。主控冻结验收，Terra-high 新上下文执行；先红后绿，主控最终独立复验。

## 基线、所有权与限制

工作区 `/Users/zhaowei/Desktop/David/project.nosync/managing-long-task-context`；main HEAD `0f5898e19b4951c661edce1f7db80f95cc1b2ecc`。E1 已有未提交源码/测试及用户文件，全部保留。core SHA256 `c78af79aabb5fe130db217cc0f69ea4eaa055df37e69cae1d54b730d6b436a2f`；handoff `c8a459278158a18ff4e563a1cd69663e2c598b54f6236942d67184a5bc22ed9f`。E1最终468项467通过，唯一分发副本落后失败。

单一执行者拥有：`skill-package.json`、`pyproject.toml`、`scripts/sync_context_strict_skill.py`、`tests/test_distribution.py`、新 `tests/test_handoff_distribution.py`、必要薄 `tests/handoff_distribution_fixture.py`、根 `SKILL.md`、新 `references/handoff.md`、新 `examples/short_session_handoff.py`、`.github/workflows/ci.yml`、`docs/validation/e2-executor-report.md`/`e2-executor-runs.json`。允许在 core 显式受控模块登记、公开导出/dispatcher/BoundContext 和 truth_sources 的 capability 允许表做必要接线；runtime_identity.py 仅必要身份接入。产品 handoff 状态机、旧安全策略、E0预期和旧E1测试只读，有真实缺口先交主控裁决。

Strict生成目录仅用已有同步脚本生成，不手改副本。同步脚本会重写同字节的Lite工具及根generated模块：保持内容无diff，不扩大Lite功能或改公共工具。E1测试/支持夹具按实际导入依赖加入复制清单；不得漏其依赖后用skip求绿。分发专用测试可留开发仓库，完整包至少有可执行新入口示例与自包含协议测试；避免包内测试反向依赖开发根、另造包构建递归。

新能力使用本地候选版本0.8.0（skill/package/pyproject一致），不声称已经发布。工作树构建 source_revision 必须明确为未提交候选，不能把dirty内容冒充Git HEAD原包。旧0.7.0完整冻结包不改。禁止E3+、全局安装、改生产、业务执行、新付费调用、git提交/合并/推送/部署；不触发远程CI。CI定义可以修改、本地模拟执行。

## 验收（先冻结，分片红绿）

1. 五个公开入口 prepare/validate/activate/cancel/status 均真实可导入，声明、`__all__`、dispatcher及已有BoundContext对应入口不漏activate；合同可显式声明`short-session-handoff/v1`，旧合同不自动启用或降低门禁。版本0.8.0与声明一致。
2. handoff模块进入现有导入期身份基线。完整包在源码树外的新Python进程，`runtime_identity`和full doctor通过；真实加载路径全部在指定包。仅移除handoff文件、仅篡改文件（manifest不变）必须使完整包核验失败；错package root、导入后换manifest必须使runtime身份不通过。沿用分层身份契约：轻量identity仅比较路径/加载manifest，不把它称为内容hash核验；调用链启动以full doctor验证完整内容。不扩展为每轮全包扫描，不另造身份框架。
3. 已有check-source→build→verify链路对Strict全包通过。新module/API/文档/example/自包含test与依赖进入声明和同步；用实际删模块/缺路径/声明不符反例证明检查变红。同步前后旧副本失败转绿，独立清单一致性测试保留。
4. 源码树外仅通过完整包运行实际临时文件示例：身份校验→真实合同→prepare→validate→activate→status；另任务cancel，重复activate保持一条激活/代次不重复，完成仍由旧gate决定。至少有效传递通过、缺可信host/伪造pass阻断、依据核验后变化阻断、错误包拒绝。host明确synthetic，回调读真实内容及固定注册身份/授权，不反射request即pass。
5. 简短根SKILL只加启用边界和按需入口，不注入计划/长协议。references说明参数、身份/授权来源、check_status与commit_status分离、未知不重试、旧包不能自动迁移、在途child授权与业务验收独立。未适配Codex/Claude自动切换、占用阈值提醒、常驻调度保持未开放，不能宣称E2已实现。示例安全临时目录，自清理，无CLI/网络/安装业务动作。
6. CI显式运行非零新分发测试及构建包新入口smoke/反例；构建位置在checkout外，PYTHONPATH只指向包，默认环境不能偷用源码。本地执行等价链路，报告远程CI NOT_RUN；不声称本机测试等于Linux实证。
7. 所有旧E1针对性、四套主控probe、完整回归无新增失败，旧分发失败已消除。显式提供冻结旧包跑迁移类比（6项不skip）。Lite check-source/build/verify/full doctor不退化，Lite内容保持无改。所有测试数/skips与真实运行结果分开。
8. 报告基线红、每次红绿、实际命令/退出码/耗时、最终完整包manifest/hash/source_tree_hash、源码与生成身份及文件清单；模型原判/token/生产收益UNKNOWN。仅闭合本地E2，不安装或发布。

## 接口检查点与交付

开始写实现前先给主控一段简短具体提案：五入口遗漏位置、capability登记位置、身份如何覆盖新模块、打包复制的最小依赖、源码树外例子与反例如何不伪造host证明、CI非零执行方式。主控确认后才实现；无需再向用户索要“继续”。问题需扩范围先停该部分，继续无依赖工作。

建议实际命令：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_handoff_distribution test_distribution test_runtime_identity -v`；完整包用现有 `scripts/skill_package.py` 构建到新mktemp目录并记录完整指纹。工具进程必须收取退出结果，不能发出命令即称通过。先有行为断言失败再最小修补；入口不存在/导入失败不是独立行为红证据。

## v1.1 主控兼容性裁决

v1 SHA256 `f510980b08a35575c6c758421ea2d7b17fba6951aae8a44d86f9d79d88111983`。只读检查发现 `tests/test_handoff_process_recovery.py` 把解释器固定为 `/opt/homebrew/bin/python3.12`，Linux CI无法使用。额外允许原执行者仅在该文件增加 `import sys`、将 `PYTHON` 设为 `sys.executable`；不改测试行为/断言/故障点，须复跑原11项。这是E2 CI可运行性接线，不开放旧安全语义修改。其他v1验收不变。
