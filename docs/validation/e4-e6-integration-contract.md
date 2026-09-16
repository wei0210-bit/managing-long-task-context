# E4-E6 主控集成验收（执行前冻结）

完整包本地验收，不安装/提交/发布。源工作区 `.worktrees/short-session-remaining`；E3根工作区副本保留为基线。源码变化逐文件复核，不能用HEAD diff混淆E1-E3。

1. E4两个新增模块、按需说明及测试纳入既有Strict同步清单、required_paths和import-time runtime identity；只声明native-host-capability-report，不声明真实自动接管支持。完整包中缺文件、篡改、外部导入均不通过。
2. E5 Lite候选升级1.4.0，references加入payload roots；新增helper/docs/测试纳入包。原validator tests的项目路径需要包兼容入口，不能只复制无法运行的测试。Root旧validator、router、identity、experience测试保留。
3. E6工具单一源scripts/context_usage.py复制到两个包；工具/按需说明/测试纳入声明和同步检查，不复制第二实现。只声明local-usage-accounting/context-pressure-advisory，不声称自动调度或token收益。
4. source-check/build/verify/full doctor在源码树外执行；固定source_revision=candidate:dirty-worktree-0.8.0-E4-E6（Lite1.4.0），记录manifest/source tree hash。新入口单独实际调用并有非零测试数。
5. 旧0.7.0完整包显式注入：`MLTC_LEGACY_PACKAGE=/private/tmp/mltc-review-baseline.GYDdVc/context-strict`。最终`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src /opt/homebrew/bin/python3.12 -W always::ResourceWarning -m unittest discover -s tests -q`；全发现数、失败、skip、警告与耗时分别记录。不能把未找到测试作为绿。
6. 完整包确认后本地CI等价步骤执行；远程CI不运行/不宣称通过，保持no push。既有完成/授权/状态机不改。
7. 全文件diff/行尾、E0manifest、原用户文件检查；两份观察文档仅有本批授权追加，其余用户原件不变。
8. 机制/真实模型/自然使用三层单列。E4真实宿主未接入、E6效果未计量是明确未完成，不以本地拒绝路径/压力建议/程序重复冒充整个产品完成。
9. 保留分支和未提交工作区，不自动Git合并。根CONTEXT指向候选与报告，用户无须再说“继续”才能完成剩余不依赖外部证明的本地工作。

远程工单上传当前被权限审查因内部payload拒绝；不重试绕过，不影响本地工单执行。需要远程记录时再集中请求明确授权。
