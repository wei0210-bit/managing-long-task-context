# E2 主控独立复验

状态：2026-09-15主控本地E2验收通过。当前合同v1.1，SHA256 `0f4237d22db440b61c596a37c3fda3242ab7324f3263f696f9dcf53ba5295827`；只批准E2，不安装或发布。

## 最终结果（执行者停止源码写入后）

| 主控验证 | 实测 | 退出 |
| --- | --- | --- |
| 全回归，显式旧0.7.0包，无skip | 473/473，47.164秒 | 0 |
| E2分发/身份＋全部E1针对性 | 101/101，16.902秒 | 0 |
| 最终候选P01–P05/P07独立反例 | 6/6，1.171秒 | 0 |
| 源码树外完整包的activation/protocol | 36/36，0.739秒 | 0 |
| E1-01主控 | 10/10，0.054秒 | 0 |
| E1-02主控 | 18/18，0.393秒 | 0 |
| E1-03主控 | 17/17，0.843秒 | 0 |
| E1-04主控 | 4/4，0.101秒 | 0 |
| 源码树外实际完整包示例 | prepare/validate通过，activate/status/cancel确认提交，代次1、激活事件1、重复日志字节不变，0.260秒 | 0 |

原分发副本差异真实消除，没有删除断言求绿。全回归与针对性并行，时耗不是独占性能基准。根E1探针合计49/49，未将它们重复算进473项全回归。

### 完整候选身份

主控独立构建：[Strict 0.8.0完整包](/private/tmp/mltc-e2-controller.rGw7ow/context-strict)。51个文件，21个Python导出，check-source/build/verify/full doctor均通过，source_revision为`candidate:dirty-worktree-0.8.0`，不是已提交HEAD产物。

- manifest SHA256：`51331cb7ea3edb2c120d1f1a5efa76dff32d79edd7644a1f0f98312ab0817165`
- source_tree SHA256：`5ecbef6bf1d08c7dd75e5e39d7efba3764bcd092475039c14ebb33fa32297d1a`
- core SHA256：`7460e51f2e70594f3eb1be78e12fca0ffb803193d5647a9ac950ebda4b6447f6`
- handoff SHA256：`c8a459278158a18ff4e563a1cd69663e2c598b54f6236942d67184a5bc22ed9f`（E1状态机未修改）
- root probe SHA256：`2f59f82a005bd8d58d899ff10ee13a58d74a775d0e8eb5ba91f6e319258782d4`

执行者先前52文件候选 `/private/tmp/mltc-e2-candidate.fBNwjX/context-strict` 的manifest `d34feec15f01eb905148a56645de08f5f705dac70900b08b790ab524887c223e` **已撤回，不得安装或作为最终证据**。它仍带有依赖开发仓库的测试副本。只精确移除了本轮误生成的Strict目录内那一份测试，根测试保留；新包manifest明确不含该开发测试。旧候选不覆盖，保留复核历史。

Lite内容无diff，仍1.3.0；主控另建11文件包并check-source/build/verify/full doctor通过。manifest `f29a0fcad73346e74769ec2328ba69dbcc9b6d108af44ade7eb093c2b5906b49`，tree `455356074351867386d707230612f5c704e5d564c87329b897ff70d0c53299e7`。临时目录可被系统清理；以工作区源码、声明及复跑命令为可重建依据，不把临时路径当永久发布地址。

### 验收映射与成本

1. 五公开入口、dispatcher、BoundContext、capability登记和0.8.0声明一致；包外真实调用BoundContext的prepare/validate/status与dispatcher的activate，旧合同不自动加capability。绑定缺失或路径覆盖返回unknown/not_attempted，不猜路径。
2. P07只预载包外真实handoff模块即RUNTIME_PATH_MISMATCH，证明覆盖不止core；P02/P03完整包篡改/缺文件阻断；P04/P05错根/导入后替换manifest阻断。P01有效包允许。此组六项错误放行0/5、错误阻塞0/1；这是合成程序反例，不是模型稳定性。
3. 新module/reference/example与自包含activation/protocol/helper进入复制清单/声明。两个独立清单一致性及旧文档/API检查均通过。生成副本只经已有同步脚本；Lite无内容改动。
4. P06真实包外生命周期及36项协议/激活测试通过，含缺可信verifier、伪造引用、检查后证据变化；业务完成仍由旧gate独立判定，E1-04矩阵仍通过。
5. 根SKILL仅增加6行（10359→10832字节，增473字节），2182字节协议说明按需加载；未把计划注入运行提示。字节不是token。引用明确禁止伪造授权，未实现真实宿主自动切换。
6. CI新增显式非零分发测试和包外smoke，复用已构建的Strict包，不重复构建同一包。本地执行等价step及非零计数检查通过；没有触发远程CI，Linux运行未验证。
7. 原7个用户文件SHA未变；E0 manifest固定输入再校验通过0.028906秒。E0冻结文件中的NOT_RUN不被本轮改写；E0真实host迁移仍NOT_RUN。
8. `/usr/bin/time -l`尝试读取RSS时被沙箱拒绝（sysctl kern.clockrate），计量包装器退出1；随后普通示例重跑退出0。不得把包装器失败记为验收通过，RSS记UNKNOWN。模型输入/缓存/输出token、真实模型原判、付费收益与生产效果均UNKNOWN。只做合成幂等请求，无业务重试。

### 复跑

```sh
MLTC_LEGACY_PACKAGE=/private/tmp/mltc-review-baseline.GYDdVc/context-strict PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /opt/homebrew/bin/python3.12 -m unittest discover -s tests -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests /opt/homebrew/bin/python3.12 -m unittest test_handoff_distribution test_distribution test_runtime_identity -v
MLTC_E2_PACKAGE=/private/tmp/mltc-e2-controller.rGw7ow/context-strict PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 docs/validation/e2_controller_probes.py -v
```

重建时用现有 `scripts/skill_package.py check-source --source skills/context-strict`，再build至**不存在的新临时子目录**，source_revision明确候选，按build回执的manifest/hash执行verify。源码树外以`PYTHONPATH=<包>/src`运行`<包>/examples/short_session_handoff.py`；该示例先full doctor，失败时不进入_flow。包内测试另加`<包>/tests`到PYTHONPATH。需要旧包类比时必须显式提供完整冻结0.7.0包；缺环境变量导致的skip不能冒充本次473/473。

## 基线与已查明缺口

2026-09-15，main HEAD `0f5898e19b4951c661edce1f7db80f95cc1b2ecc`，保留E1未提交工作及原7个用户工件。计划v0.28 hash `5b0d9c8cdfd38713bdb60b2faa3283c15c78937f3ac3ba18a435c45de248cb90`通过核对，再按新授权更新v0.29。

主控先复跑原 `test_distribution_matches_maintained_sources`：1项，0.016秒，测试退出1（shell后续只读命令退出0不代表测试通过）。失败确为core与Strict副本字节不同。

静态实查：activate缺少公开导出/dispatcher接线，BoundContext缺新入口；handoff未纳入导入期身份基线；合同允许capability列表未登记short-session-handoff/v1；同步清单/声明未覆盖新module与完整新链路。原E1行为测试已验收，不重写协议。

额外发现旧进程测试写死Homebrew Python，Linux CI无此路径。v1.1明确批准仅换sys.executable与import，不改11项故障断言。其余E1测试和状态机不开放修改。

## 分层验证

主控预期已在 [P01–P06](e2-controller-cases.md) 冻结，独立脚本 `e2_controller_probes.py` 不导入执行者测试夹具。先用真实冻结0.7.0包只验证P04/P05边界：2/2，0.270秒；这是旧身份机制复核，不是0.8.0验收或TDD红例。

轻量runtime identity保持只比加载路径与加载manifest，full doctor/verify负责内容哈希。文档不能把前者说成完整证据核验，也不为本次接线改成每轮全包扫描。工作树产物source_revision必须标候选；未来真实CI清洁checkout仍用git:$GITHUB_SHA。

## 尚未验证的后续能力

真实宿主、Linux远程CI、模型判断/token/自然效果均未验证；安装、提交、推送、合并、部署未执行，Git HEAD不变。E3+尚未授权，不能将E2包完整性等同自动rollover已可用于生产。

测试方法偏差如实保留：执行者最先记录的缺方法AttributeError/缺示例为装配失败，并非行为TDD红；未虚构红先于绿。旧0.7与0.8对capability的对比是事后基线对照。最终以主控公开接口运行、负例和完整回归完成验收；不声称本轮每项都严格完成行为TDD时间顺序。
