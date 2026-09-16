# E2 主控验证冻结

在执行者实施前冻结；复用E2合同，不重造验收器。所有操作限新临时目录；生产、已安装包只读。

| ID | 公开刺激 | 必须出现的结果 |
| --- | --- | --- |
| P01 | 完整候选包从源码树外加载 | full verify/full doctor/runtime_identity通过；五入口导出及handoff受控路径在该包内；版本0.8.0，工作树来源不冒充已提交HEAD |
| P02 | 复制候选包，仅篡改handoff.py，保持manifest | complete verify失败，不以轻量identity替代内容核验 |
| P03 | 复制候选包，移除handoff.py | complete verify失败；不计导入异常本身为完整安全证明 |
| P04 | 加载包A，却传另一完整包B作package_root | runtime_identity非pass，错误路径被识别 |
| P05 | 已加载包A后，修改manifest来源并换成B的manifest | runtime_identity非pass，旧加载会话不能自称新包 |
| P06 | 只靠候选包的实际例子调用交接链 | 真正prepare/validate/activate/status/cancel与重复请求符合合同；缺可信回调/核验后变化拒绝；不触发业务或调用真实宿主 |
| P07 | 仅handoff模块从包外真实文件预加载，其余模块从指定包导入 | runtime_identity拒绝运行路径不符，证明新模块确实纳入覆盖，不只检验core路径 |

包外运行的subprocess使用sys.executable、显式PYTHONPATH且cwd在独立临时目录。根测试不能从项目夹具回填缺失包能力。完整回归须显式旧包跑迁移类比，记录非零数量/skips；真实宿主和远程CI仍NOT_RUN，token未知。
