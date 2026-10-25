# Sprint 3 受限回放工程状态

更新：2026-10-26（Asia/Singapore）。PR#76已由owner合并，S03-01/03已接受；下表保留S3交付范围，S03-02估值补充见[Sprint4状态](sprint-04-status.md)。S02-03真实访谈仍为0，完整family/trial生命周期未完成，不宣称整体市场验证完成。

| 故事 | PR#76已接受的交付 | 剩余边界 |
| --- | --- | --- |
| S03-01 / Issue#7 | 原生无关ReplayPort/不可变DTO/strict schema、盘口与时钟预检、Nautilus1.231.0 adapter、显式能力声明、固定单位/排序和结构化错误；CLI经监督worker调用 | 只支持EUR/USD内置单限价买单；任意策略、其他资产/账户、checkpoint和强隔离不在本批 |
| S03-02 / Issue#8 | 输入→决策→订单/命令receipt→两次partial fill→真实缓存持仓/现金/费用；同刻源引用与首次决策分歧可定位 | 尚无通用mark/realized/unrealized净收益评价合同，不能以账务快照替代研究命题评价，故事继续开放 |
| S03-03 / Issue#9 | 固定原创golden、十独立进程完整语义重复、原始run与子进程耗时、环境/模块/制品hash、+1ns已知输入控制的可读diff | 只为该fixture原始基线，不代表冷机、撮合吞吐、真实市场校准或产品性能 |

实际操作见[回放指南](../replay.md)、[合同](../contracts/replay-v1.md)及[十次基线](../research/sprint-03-replay-baseline.md)。代码依赖向内，native类型只存在infrastructure私有桥接；SDK/CLI共享application用例，worker不接收catalog路径或策略源码。

## 关键验收证据

- 价格/数量增量与notional用精确整数有理数预检；重建book，拒绝跨流、空/交叉盘口、非法删除、重同步、duplicates/gaps、未知/倒退receive及不支持的资产。缺native时预检仍可先完成。
- public SimulationModule撮合前钩子建立源引用，避免fill先于market callback时误引用上一条；同刻输入保持capture顺序。
- 两次partial在回调中分别持仓1/2、cash9999/9998、费用1/2；Money实际量化及理论fee差额可见。全局Decimal context变化不改变所测trace。
- EOF分别保留开放单和pending submit/cancel，即使订单FILLED仍可有pendingcancel。原生callback被吞掉的错误注入必须抛出执行失败，不能发布completed。
- 监督进程覆盖缺依赖/版本、超时、输出越界、异常结果与错误输入绑定；核心和native安装分开验收，sdist→wheel后以`-I`运行CLI，避免源码路径掩盖打包问题。
- 环境/spec/data不同明确标为非严格paired；固定channel顺序的首差异不冒充全局因果首差异。

本批完整测试数字及CI链接随PR记录。已知native Pandas弃用警告保留可见，未修改第三方代码或联系上游。人工工时未登记，不用AI墙钟时间冒充专项人力投入。

## 下一条纵向路径

先定义受支持的mark与净收益、失败/未完成评价规则，把ReplaySpec与冻结研究协议及trial身份作版本化绑定，再进入S4的export/verify闭环。现有`execution_ready=false`不能靠一个override flag绕过；真实访谈和高级holdout账本继续按各自证据验收。当前公开CLI仅提供可信本地qualification，不接收Agent绕过协议的授权请求。
