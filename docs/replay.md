# 受限 L2 回放与轨迹比较

当前交付是S3的引擎验收路径：从真实封存dataset，经稳定ReplayPort运行内置策略，得到可追溯的输入、决策、订单、成交与账户轨迹。它不执行`FrozenProtocol v1`、不加载策略源码、不评价研究claim，也不解封确认集。完整研究协议执行与证据包流程仍由后续故事实现。

## 安装与运行

核心安装仍无第三方运行时依赖。需要原生回放时显式安装固定的可选引擎；首次动态库加载可能明显慢于随后运行，超时预算包含这部分时间。

```sh
uv sync --locked --extra nautilus
TW_REPLAY_DATA=$(uv run --locked --extra nautilus tickwitness import-events replay-partials.jsonl --input-root examples --store .local/data --id-only)
mkdir -p .local/replays
uv run --locked --extra nautilus tickwitness replay-dataset "$TW_REPLAY_DATA" replay-spec.json --input-root examples --store .local/data --timeout-seconds 60 > .local/replays/baseline.json
uv run --locked --extra nautilus tickwitness compare-replays baseline.json baseline.json --input-root .local/replays
```

命令输出是规范JSON加一个终止换行，可以直接重定向为结果文件；comparison接受此编码或无终止换行的canonical文件。失败时stderr输出JSON错误，stdout不发布半份结果。`execution_status=incomplete`是成功记录了一次未完成回放，其CLI退出码仍为0；调用方必须检查status/completeness，不能只看进程退出码。

也可给`replay-dataset`传`--engine-python /absolute/environment/bin/python`，指向**可信且已安装同版本TickWitness及可选引擎**的独立环境。解释器是owner配置，不是远程作业或不可信插件入口；保留venv路径，不能用解析symlink后的基础Python替代它。包与引擎版本不匹配或不可导入会明确失败，不静默切换引擎。

## 明确支持的首个profile

| 项目 | 当前支持与拒绝规则 |
| --- | --- |
| 引擎 | `nautilus-trader==1.231.0` stable v1，固定语义ID；不自动使用v2/latest |
| 数据 | 单一`(source, instrument, session)`，instrument严格为`EUR-USD`，一份初始snapshot后接delta/trade；不会把BTC等价格悄悄改名为EUR |
| 单位 | EUR/USD、显式price/size increment，最多8位规范小数；整数ticks/lots映射前检查价格、数量与派生notional范围 |
| 时钟 | `receive_order_v1`：已知非递减receive_time，event_time<=receive；native双时间映射到receive，原event/receive保留在trace；**不认证UTC或真实延迟** |
| 顺序 | 按原capture order，保留相同receive时刻的输入列表顺序；每条输入有dataset identity、line与capture_seq引用 |
| 盘口 | L2_MBP，重建后两侧非空且不锁盘/交叉；缺口、重复、重同步、未知时间、空delta及删除不存在档位均在native启动前拒绝 |
| 策略 | 仅内置`single_limit_buy_v1`：指定capture触发一笔post-only限价买单，可在首次成交后请求取消剩余量；不执行任意源码 |
| 账户 | 单EUR/USD、USD MARGIN/NETTING、leverage 1，显式起始现金与maker/taker费率；不是多资产保证金模型 |
| 资源 | 输入<=8MiB且<=10,000条；worker时限1..60秒（默认60），结果<=16MiB、stderr<=64KiB；不声称内存硬配额 |

完整schema及值边界见[Replay v1合同](contracts/replay-v1.md)。这些限制是验收过的profile，不是全市场支持矩阵。该直接dataset入口面向可信本地开发者，不能当成Agent探索接口；原有[协议读取](research-protocols.md)的confirmation拒绝政策保持原语义。

## 从输入核对到现金与持仓

公开的`SimulationModule.pre_process`在撮合前绑定源capture；成交回调即使早于策略的行情回调，也能引用真正触发它的输入。native内部批次ID与来源sequence/trade ID分别保存，不把引擎生成ID冒充原始交易所证据。

原创partial fixture的两次成交分别为1 lot、100 ticks，maker费率1%，每次实际费用1 USD。回调内缓存持仓依次1、2，USD现金依次9999、9998，累计费用1、2。保证金账户开仓名义本金不会像现货买入那样直接从cash total扣除；locked/free/total分别记录。

价格与数量转换使用精确整数/有理数验证，adapter的十进制计算使用独立context，避免调用方全局Decimal精度改变结果。**native MakerTakerFeeModel内部使用f64 notional并生成USD两位精度Money**；fill trace同时保存实际费用、精确理论费用和差额，不能将它描述为原生全Decimal执行。当前没有实现一个跨账户通用净收益评价器。

## 终止与错误

每个submit/cancel有独立命令receipt记录。数据结束时：

- 有未确认命令：`incomplete / pending_commands_at_data_end`，包括订单已经FILLED但取消仍在途的情况。
- 没有在途命令但还有开放挂单：`incomplete / input_exhausted_with_open_orders`。
- 全部输入处理完成、订单终结且无在途命令：`completed / input_exhausted`。

不会追加虚构行情推进未来命令。callback失败、native异常、worker崩溃或无效结果都不能退化成completed；没有研究finding或“未找到反例”的判定。

| 退出码 | error.code示例 |
| --- | --- |
| 2 | `invalid_replay`、`unsafe_input`：规格、时钟、单位、盘口或路径不受支持 |
| 3 / 4 | 原dataset完整性/I/O失败或身份不存在 |
| 6 | `engine_unavailable`：可选依赖缺失、版本不匹配或worker不可用 |
| 7 | `engine_failure`、`engine_timeout`、`engine_output_limit`、`engine_invalid_result` |

worker使用窄JSON IPC、独立临时工作目录、Python`-I`、进程组终止和输出监督。该边界处理可信内置策略的崩溃与预算，不是恶意Python沙箱、网络隔离或多租户安全证明；root catalog只在父进程以只读方式访问，worker不接收store路径。

## 比较与原始基线

comparison先报告engine/version/semantic、环境、spec和dataset/hash的条件差异，再给出轨迹中第一处差异的JSON Pointer、channel ordinal与双方源事件引用，另列首次决策差异。不同条件的运行不能被标成严格同条件对照；不同channel的固定比较顺序不等于全局因果先后。

同fixture十次独立进程的原始耗时、golden语义输出和已知输入变化控制见[S3回放基线](research/sprint-03-replay-baseline.md)。重复一致只说明当前条件下的已测fixture；原始run包含预检、初始化/懒加载等成本，不是产品吞吐、P99或纯撮合性能。

原生集成由独立的Ubuntu24.04/macOS15、CPython3.12 CI检查；核心仍在Python3.12–3.14矩阵运行。其他native平台/版本仅在相同契约通过后扩展。源码包包含原创examples，wheel安装后的CLI由独立工作目录实跑验证。引擎继续保留LGPL-3.0-or-later许可，项目原创代码Apache-2.0；optional不代表免除分发义务。
