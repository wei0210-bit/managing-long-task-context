# E6 主控审核（本地验收通过，真实收益未验证）

冻结合同SHA74be2152547da2fd8ebd4bbfc169805cdfb41de2d7d898a32797399c957ccf9a，主控案例SHA093796ac7ac0a5ff249e91803d3ced8e44fa35704eccf9020385909af29d4b0b。
主控只调用公共计量/压力入口，以合成字面量刺激独立核验；不读模型历史/真实账单。

## 第一轮实际红例

命令：`PYTHONDONTWRITEBYTECODE=1 /opt/homebrew/bin/python3.12 docs/validation/e6_controller_probes.py -q`。
12个方法，4 failures+5 errors（含一个方法多个畸形字段subtest）；0.003秒。失败方法包括：
- 当前窗口已达阈值且安全点，却因milestone=false不提醒，连带重复/关键变化正例失败。
- 过期分支优先于task_complete/execution_unknown，错误建议milestone。
- mode/cache_accounting/basis为JSON数组/对象触发TypeError，不是稳定unknown。

主控静态补查有界读取/迭代与空usage误作零，已派同一执行者修复；空usage补第13个方法。没有改冻结字面量预期洗绿。CLI真实I/O和最终计量/内存结果待执行者与主控集成复验。

## 第一轮修补结果

执行者17/17，主控格式化新文件后复跑17/17（0.198秒）、13/13独立probe（0.001秒）。独立reviewer e6_usage_review（Terra-high）只读审核通过，并用定向刺激核对计量、冲突、阈值及优先级；未以程序测试宣称真实模型稳定。
本地3个全新Python进程：1000条合成usage聚合0.00543–0.00581秒；20次pressure判断0.000287–0.000298秒，每轮只1次notify；进程RSS峰值25067520–25165824字节。usage时间仅函数调用，不含输入构造和启动；RSS为整个Python进程，不是Skill增量占用。计费token/真实费用/产品收益均null。
这些数字只适用于此合成负载；最终完整集成验收与未验证边界另列，不能用局部绿跳过整体审核。

## 最终收口

整批审核后补齐首次到期通知状态、UTC上下界溢出、缺量里程碑及有效basis门；非法累计/畸形basis不借缺量降级。最终usage23/23、主控E6 13/13和F1/F5 2/2；整批550/550，包外Strict62/62、Lite43/43，独立复审闭合。完整指纹、最终资源计量、旧候选暂缓原因见 [最终主控验收](e4-e6-controller-review.md)。本地计量/建议完成，真实token收益、模型稳定性和自然项目效果仍UNKNOWN，不把早期数字当最终源码测量。
