# S01-01：NautilusTrader 可行性报告

检查日期：2026-10-25。状态：**受限可行性试验已执行；正式 adapter、L2 假设搜索及产品支持矩阵尚未验收**。项目入口见 [README](../../README.md)。

本报告把信息分成三类：**本机实测**、**官方发布/API/源码证据**和**尚未验证**。同机的微型合成试验不能替代真实行情、跨平台认证、性能基准、独立人类复核或生产发布门。

## 1. 版本选择与安装证据

本次固定 **NautilusTrader 1.231.0 stable / v1 Cython API**。PyPI 列出该 stable 版本发布于 2026-08-02；同时列出 `2.0.0rc7`（2026-10-15）的预发布。官方 `latest` 安装页明确说明它面向 v2，而默认不带 `--pre` 的安装仍落在 v1，二者 Python API 不兼容。本轮不安装 v2，不从 `latest` 示例推断 v1 行为。[PyPI 1.231.0](https://pypi.org/project/nautilus-trader/1.231.0/)、[官方安装说明](https://nautilustrader.io/docs/latest/getting_started/installation/)

| 项目 | 核实结果 | 证据等级 |
| --- | --- | --- |
| Python 元数据 | `>=3.12,<3.15` | 官方 PyPI + 本机 dist-info |
| stable wheel 矩阵 | CPython 3.12/3.13/3.14；Linux glibc 2.35+ x86_64/aarch64、macOS 26+ arm64、Windows amd64，共 12 个 wheel | 官方发布文件列表；非全部实测 |
| 本次 wheel | `nautilus_trader-1.231.0-cp312-cp312-macosx_26_0_arm64.whl` | 官方发布文件 + 本机 WHEEL tag |
| 本次环境 | CPython 3.12.14；macOS 27.0.1；arm64 | 本机实测 |
| 安装 | 官方 PyPI、仅二进制 wheel；15 个依赖版本；未使用源码构建 | 本机实测 |
| v2 | 当前 `latest` 文档和 rc API 属另一条版本线；未安装、未执行 | 官方文档 / 未验证 |

上述 macOS 下限来自所选 **v1 wheel tag**；不能用当前 v2 文档中的一般平台表降低它。没有 Intel macOS wheel 或其他 ABI 的本轮验证。产品计划中的 Python/平台组合，不因这些发布文件存在而自动成为已认证支持组合。

本次 wheel 的官方 PyPI SHA-256 为 `ed9304cbedeccd03e157c89b1e9acc3c9c35785f3bc2a114e4ea2e262a051890`。发布文件大小为 156,041,405 字节。这是官方发布元数据；本轮完成了安装和导入，未另行完成 release attestation 的独立验证。[保存的发布元数据](../../research/spikes/nautilus/results/pypi-1.231.0-metadata.json)

环境与 uv 缓存位于 `/private/tmp/tickwitness-s01-nautilus/`；根 `.venv`、`pyproject.toml` 及用户全局包未改动。沙箱中的官方 PyPI DNS 请求失败后，通过已授权的联网执行完成下载。没有下载大型行情集；fixture 完全由代码生成。

## 2. 原创合成 fixture 与手算结果

策略固定为：收到第 0 条 quote 买入 1000 EUR，收到第 3 条 quote 卖出 1000 EUR。EURUSD 价格精度 5 位，零费用、无随机滑点，初始 USD 现金 10000，保证金账户，杠杆 1。每个 bid/ask 档显示 10000 单位流动性；本次不测试深度消耗、部分成交或队列。

时间从合成 epoch `1700000000000000000 ns` 开始，每条相隔一秒。`ts_event == ts_init` 是 fixture 的构造条件，不是测得网络延迟或交易所时钟关系。

| quote 序号 / 相对秒 | bid | ask | 策略动作 |
| --- | --- | --- | --- |
| 0 | 1.00000 | 1.00002 | 买入 1000 |
| 1 | 1.00005 | 1.00007 | 无 |
| 2 | 1.00015 | 1.00017 | 无 |
| 3 | 1.00010 | 1.00012 | 卖出 1000 |
| 4 | 1.00002 | 1.00004 | 无 |
| 5 | 1.00000 | 1.00002 | 无 |
| 6 | 1.00000 | 1.00002 | 无 |

**本机实测：** baseline 下成交价为买入 `1.00002`、卖出 `1.00010`，现金 `10000.08 USD`。手算 `(1.00010 − 1.00002) × 1000 = 0.08 USD`，与引擎账户报告一致；最终仓位关闭。

额外设置 `insert_latency_nanos=1_500_000_000`、`base_latency_nanos=0` 后，相同策略与行情得到买入 `1.00017`、卖出 `1.00000`，现金 `9999.83 USD`，手算净变化为 `−0.17 USD`。这是 **COUNTERFACTUAL_STRESS：额外订单延迟压力**。它不是与全部历史观测相容的队列解释，也不能支持“结论不可识别”判定。

**关键粒度限制：** 在本轮 v1 配置中，延迟订单分别在第 2 秒、第 5 秒行情 step 才处理，使用相应 step 的行情；不是自动插入第 1.5 秒、第 4.5 秒的独立撮合事件。固定版本源码中的命令队列、`_has_pending_commands` 与 venue settling 路径解释了该行为。后续适配必须把事件推进和定时器约定写入语义契约；不能只填“延迟 1.5 秒”就假设得到连续时间撮合。[v1 engine 源码](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/nautilus_trader/backtest/engine.pyx)

脚本与完整小型结果见 [spike 目录](../../research/spikes/nautilus/README.md)。该例子专为手查构造，正负结果不是市场策略收益或搜索算法有效性证据。

## 3. Trace：拿得到什么，仍需自己记录什么

| 所需信息 | 本轮获取方法 | 结论 |
| --- | --- | --- |
| 输入事件 | `Strategy.on_quote_tick` 保存实际收到的 quote 与两个时间字段 | 7 条回调全部取得；原始输入与数据版本清单仍需平台自己维护 |
| 策略决策 | 原创策略在 `submit_order` 前显式记录 input ordinal、时钟、side、quantity、client order ID | 两次决策取得；不是引擎自动解释任意策略私有推理 |
| order 生命周期 | `on_order_event` | 每次运行 6 个事件：两组 Initialized → Submitted → Filled |
| fill | `on_order_filled` | 两笔 side/qty/price/commission/liquidity side/时间取得 |
| 账户变化 | `generate_account_report` 及 cache account | 初始、持仓保证金、平仓现金快照取得；不是逐笔交易所现金流水 |
| 仓位 | cache positions 的关闭状态 | 本例最终关闭，可与手算配对 |

上述回调与报告由已安装 v1 的 API 及源码核对。事件的 UUID、引擎 run/instance ID 未进入语义轨迹；input ordinal、确定性 client order ID、业务字段和模拟时间保留。金额、价格、数量及纳秒时间使用十进制字符串，避免展示层大整数精度损失。[v1 Strategy 源码](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/nautilus_trader/trading/strategy.pyx)、[v1 Trader 源码](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/nautilus_trader/trading/trader.py)

**本机实测：** 每次脚本执行构造两个全新 baseline engine，保留两份完整语义结果，逐字段相等；两份 canonical JSON 的 SHA-256 均为 `43bc7df6c6c76b6604e021756f7817fbbfa844d3ad76d50f27f64303e4d0a0d7`。canonical 方法为键排序、UTF-8、固定紧凑 JSON 分隔符；随机 ID、墙钟耗时及日志排除。证据为 [运行结果](../../research/spikes/nautilus/results/macos-arm64-python312.json) 的 `baseline`、`baseline_repeat` 与 `determinism`。

范围仅为固定解释器、版本、机器、配置和合成输入的语义重复性，不声称跨进程调度、跨 CPU、跨平台或不同底层依赖逐位确定。两个 baseline 加一次压力运行不是性能 benchmark。引擎执行时出现 `Timestamp.utcnow` 的上游 Pandas4Warning；本轮没有报错中止，但应视为依赖升级兼容工作的输入。

## 4. 队列、延迟与自定义场景能力

本节除明确标注实测项外，是固定 v1 的源码/API 证据，不是行为认证。[安装 API 与源码哈希清单](../../research/spikes/nautilus/results/installed-api-inventory.json)

| 能力 | 固定 v1 证据 | 边界与本轮状态 |
| --- | --- | --- |
| 命令延迟 | `LatencyModel`，base + insert/update/cancel 纳秒字段；`add_venue(latency_model=...)` | insert 路径已实测；update/cancel、feed/ack 延迟未实测。模型不自动表示行情接收时间、交易所内部响应或全链路实测分布 |
| 固定撮合模型 | `FillModel` 的 limit fill/slippage 概率和 seed | 本例显式使用概率 1/0；未验证概率模型统计性质。该 v1 实现使用 Python `random.seed`，单个 seed 不等于封闭所有随机源 |
| 深度消耗 | `add_venue(liquidity_consumption=...)` | 参数存在，本例订单规模不足以测试其边界；不能假设模拟成交改变了真实历史市场 |
| 队列跟踪 | `queue_position=True`，需要 `trade_execution=True`；下单时读同侧深度，随后按 trade 与价位删除推进；状态保存在私有队列结构 | 本轮没有 L2/trade fixture。它是一种队列假设，不提供真实订单级撤单位置；开关存在不证明能无侵入注入任意两种撤单分配解释 |
| 自定义 fill | `FillModel.get_orderbook_for_fill_simulation` 可返回自定义模拟 book | 可作为后续扩展试验；未验证 Python override、与 queue/liquidity 的相互作用及所需 trace 完整性 |
| 外部数据场景 | `add_data` 支持输入序列，按 `ts_init` 排序；也有 streaming iterator | 平台可构造合法数据变换，但必须自己核验因果、序列和来源约束。任意改 timestamp 不是历史接收证据 |
| 自定义模拟模块 | `SimulationModule` 生命周期与 process 扩展点 | API/源码存在；未实测，不宣称能替代撮合引擎所有内部扩展 |

尤其需要单独验证：在不修改引擎私有对象、不伪造 L2 观测的条件下，是否能表达两种有证据依据的撤单位置分配，并取得逐步 queue-ahead 轨迹。当前证据不足以回答；S01-01 的 L1 成功不能算 S6 的 L2 可识别性验收通过。[v1 FillModel](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/nautilus_trader/backtest/models/fill.pyx)、[v1 LatencyModel](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/nautilus_trader/backtest/models/latency.pyx)、[v1 SimulationModule](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/nautilus_trader/backtest/modules.pyx)

## 5. Checkpoint 与恢复：不得混淆的三件事

固定 v1 的 `BacktestEngine.reset()` 将状态重置到起点，同时保留已加载组件、数据和 venue；它用于重跑，不是恢复任意中点。`run(streaming=True)` 保持一个活进程跨数据批次前进，不等于跨进程持久化 checkpoint。[v1 engine](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/nautilus_trader/backtest/engine.pyx)

Actor/Strategy 的 `save/on_save`、`load/on_load` 提供用户组件状态保存接口；没有证据表明它们自动包含 matching engine 的订单簿、排队数量、inflight commands、所有时钟定时器、RNG 和执行状态。`dump_pickled_data/load_pickled_data` 保存/装入的是数据流，不是完整 engine 状态，而且会执行 pickle 反序列化，不能作为 TickWitness 的不可信证据导入格式。[v1 Actor](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/nautilus_trader/common/actor.pyx)

**未验证：** 中点导出、关进程、另一进程恢复后与 uninterrupted run 等价。首个 adapter 若选择此引擎，应默认从冻结输入重跑；不要在 S01-01 后承诺分叉 checkpoint、廉价前缀复用或完整恢复。将来若实现，需有包含未成交订单、延迟命令和定时器的专项等价测试。

## 6. 许可与发行边界

PyPI 与安装包 `License` 字段为 **LGPL-3.0-or-later**；上游源码与二进制不因调用它而自动成为 TickWitness 的 Apache-2.0 代码。本轮只安装官方 wheel，提交原创策略、fixture、探测代码和小型结果，没有复制库源码或二进制。[固定版本 LICENSE](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/LICENSE)

后续建议保留为可选依赖，经独立环境安装，并在发行清单列明上游版本、许可与来源；修改、复制或再分发 wheel/镜像时应单独检查对应许可义务与 notice。核心无需安装引擎即可进行自己的领域和契约测试。当前试验不是最终软件分发兼容性结论。

## 7. 决策与下一步门槛

**条件式 Go：** 以 1.231.0 为固定候选继续完成可信本地、L1 小订单、显式订单延迟压力与可追踪现金的适配契约。理由是安装成功、必要回调可获得、账户与手算一致，且已有固定输入的语义重复证据。

**未通过的门：** L2 撤单位置相容解释、可观察 queue-ahead 状态、部分成交、手续费精度、跨流乱序与同时间戳规则、中点跨进程 checkpoint、Linux/其他 Python wheel、隔离安全、性能及真实行情均未验证。v2 是单独迁移/可行性决策，不能把它的能力混入本次 v1 结论。

下一次只应安排一个有上限的 L2 扩展试验：若无法通过稳定公开扩展点表达必要队列解释和 trace，则缩小 Nautilus 适配范围、选择另一回放引擎或登记必须维护的 upstream patch 成本。正式引擎选择仍应比较项目所需语义、许可、支持负担与另一候选的证据，而不只比较这份微型 fixture 的成功。
