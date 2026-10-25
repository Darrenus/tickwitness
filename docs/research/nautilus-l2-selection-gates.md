# S2：NautilusTrader v1 L2、部分成交与终止语义补测

日期：2026-10-25。状态：**固定版本本机合成补测已执行；未实现正式 adapter，未签发研究声明判定。** 对象是 `nautilus-trader==1.231.0` stable v1；未使用 v2 API。本文补充 [S01 原始可行性记录](nautilus-feasibility.md)，默认引擎选择仍由 [ADR-003](../architecture/decisions.md) 决定。

结论：**本次证据支持有条件进入 S3 有限 L2 + TradeTick + 公开事件回调 adapter 路径。** 分时和同刻的两次部分成交，都有两条独立 `on_order_filled`，且回调内缓存持仓、保证金账户现金和费用已一致更新。必须同时保留一个重要边界：最后行情之后仍在途的延迟命令不会自动推进到未来到达时刻，不能把引擎正常返回当作作业已完全结算。S6 的严格前撤/后撤相容见证仍未验证，不能据此放行。

## 1. 版本、环境与本轮范围

- 实际运行版本 `1.231.0`，CPython 3.12.14、macOS 27.0.1 arm64；环境为 `/private/tmp/tickwitness-s01-nautilus/venv`，沿用已有固定依赖，没有改主项目环境。
- 包 metadata 的 `License` 为 `LGPL-3.0-or-later`；`License-Expression` 未填写。没有改第三方源码或二进制，也没有将其复制/重新许可进 TickWitness。
- 原创人工行情只有多档 L2 快照、L2 增量和 `TradeTick`，没有使用 `QuoteTick`；无账户、API key、联网行情或真实交易。
- 本轮测试的是当前包公开接口的有限执行语义，不是现实交易所成交校准、性能 benchmark、完整安全隔离或跨平台认证。

脚本：[run_l2_probe.py](../../research/spikes/nautilus/run_l2_probe.py)。依赖沿用 [S01 固定 requirements](../../research/spikes/nautilus/requirements.txt)。包许可和发行信息的既有证据见 [PyPI metadata](../../research/spikes/nautilus/results/pypi-1.231.0-metadata.json)；执行结果另存安装源码哈希，避免将可变 `latest` 文档混入所测版本。

## 2. 真正的 L2 输入及明确参数

每个场景先建立两档 bid、两档 ask：bid 100.00 × 1、99.00 × 10，ask 103.00 × 10、104.00 × 10。使用公开 `BookOrder`、`OrderBookDelta`、`OrderBookDeltas`，快照先 CLEAR，再 ADD 各档；快照标记与末条 `F_LAST` 明确。后续数量改变使用 UPDATE，成交使用公开 `TradeTick` 与 `AggressorSide.SELLER`。

策略通过 `subscribe_order_book_deltas(..., book_type=L2_MBP)` 获得数据，首个回调实际缓存为 `L2_MBP`、2 个 bid 档与 2 个 ask 档。结果同时保留原始输入行、批次 flags、sequence 和逐个策略回调；不是给 L1 demo 改个名称。

| 参数 | 本轮显式值 | 核实程度 |
| --- | --- | --- |
| `book_type` | `L2_MBP` | 实际输入与缓存检查 |
| `trade_execution` | `True` | 实际 trade 触发成交 |
| `queue_position` | `True` | 下单前可见前方量须被 trade 消耗；不是精确撤单分配模型 |
| `liquidity_consumption` | `True` | 本轮开启；未单独验证所有重置边界 |
| `use_message_queue` | `True` | 命令经过仿真队列与 latency model |
| `bar_execution` | `False` | 不使用 bar |
| fill model | touch probability 1、slippage 0、seed 7 | 固定参数，不是现实校准 |
| 费用 | maker 1%，taker 2% | 人为放大便于逐笔核算；不是任何真实市场费率 |
| 账户 | NETTING、MARGIN、USD 10,000、leverage 1 | 保证金现金、锁定保证金与持仓分别检查 |

安装源码确认这些 v1 参数位于 `BacktestEngine.add_venue`，queue tracking 需要 `trade_execution=True`。L2 的当前实现从同侧档位读取初始前方数量，并有私有 queue state；存在开关不表示可以注入任意带撤单身份的两个世界。[v1 config](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/nautilus_trader/backtest/config.py)、[v1 engine](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/nautilus_trader/backtest/engine.pyx)、[v1 data types](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/nautilus_trader/model/data.pyx)。

## 3. 两次部分成交及回调内状态

固定策略在初始 L2 回调后提交买价 100.00、数量 2 的 post-only limit。前方可见量为 1；随后同价外部量增加 3，总量 4。第一笔主动卖出数量 2，按该模型消耗前方 1 并成交己方 1；第二笔主动卖出数量 1，成交剩余 1。录制 trade 后还有对应 L2 数量更新。价格和数量均使用明确精度。

分时案例的直接实测结果：

| 回调 | `last_qty / last_px` | callback 内缓存持仓 | USD cash total | 累计 commission |
| --- | --- | --- | --- | --- |
| 第一次 `on_order_filled`，+1 s | 1 / 100.00 | 1 | 9999 | 1 |
| 第二次 `on_order_filled`，+2 s | 1 / 100.00 | 2 | 9998 | 2 |

每条 fill 的 commission 为 1.00 USD、liquidity side 为 MAKER，与 `1 × 100 × 1%` 一致。`on_position_opened` 和 `on_position_changed` 随后的快照也与对应状态一致，未发现 HFT 补测中那种第一笔 partial 未计入本地持仓/现金的问题。

这里是保证金账户：开仓名义本金不会作为现货买入直接从 cash total 扣掉。最终 cash total 为 9998、locked 为 200、free 为 9798；不能把没有扣除 200 名义本金误判成漏账。本例没有平仓、没有真实收益结论，也没有计算一个“策略赚钱”的结果。

同刻案例将两笔 trade 的 exchange/init 时间都设为 +1 s，仍获得两次不同 `trade_id` 的公开 fill 回调。第一个回调中持仓 1、现金 9999；第二个回调中持仓 2、现金 9998。JSON 保留 `fill_ordinal`、确定性 trade ID 和回调顺序，没有通过去重删掉相同时间的第二次成交。

这些检查只覆盖所列单资产、单买单、同价、明确 aggressor 的 fixture。不同价位分层成交、多个己方订单竞争、手续费舍入临界点、跨资产保证金和修订数据仍需各自的 adapter 契约测试。

## 4. 同刻 cancel/fill 竞态

两个 race case 都在第一次部分成交的 `on_order_filled` 内发取消剩余量请求，第二笔 trade 与第一笔处于同一个时间戳，输入列表顺序明确。

| 场景 | 人为 cancel latency | 实际公开事件与最终结果 |
| --- | --- | --- |
| `cancel-zero-same-time` | 0 | 第一次 fill 后生成取消请求；下一条输入之前完成取消；1 个 fill，订单 CANCELED、已成交 1、剩余 1 |
| `cancel-delayed-same-time` | 1 s | 第二次 fill 先到，订单 FILLED、累计成交 2；后续数据步产生 OrderCancelRejected |

两种结果的每笔回调账务均与所见成交一致。这里验证的是固定引擎的顺序规则：市场数据先进入 exchange，再进入策略数据处理，随后结算命令；不能将输入列表顺序随意等同于现实交易所同刻事件的唯一顺序。正式 adapter 必须把 tie-break、数据顺序和取消延迟放进语义版本，不能只保留时间戳。[v1 回放主循环](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/nautilus_trader/backtest/engine.pyx)。

## 5. EOF 与在途命令：必须标明未完成

独立 EOF fixture 在 +3 s 的最后一条 L2 增量回调中提交 1 单位 market buy，insert latency 为 2 s。名义到达时刻是 +5 s。

| 输入范围 | 引擎返回后实际状态 | 解释 |
| --- | --- | --- |
| 最后一条数据为 +3 s | 订单仍 SUBMITTED，0 fills，现金 10000、持仓 0、clock +3 s | 没有自动推进到未来命令到达；probe 输出 `INCOMPLETE_AT_DATA_END` |
| 同一输入另有 +6 s 的 L2 增量 | 在 +6 s 填单，成交 1 × 103.00、taker fee 2.06，现金 9997.94、持仓 1 | 命令在后续数据步结算，不是独立按 +5 s 插入一个命令事件 |

第二行是独立控制案例，**不是建议给生产历史数据伪造 guard 来制造成交**。实际协议可以明确截断并标记未决，或采用经过单独验证的 timer/end/drain 方案；本次未实现后一方案。

安装源码中的 command drain 只取到达时间 `<= ts_now` 的队列项；主循环末尾仍以当前 test clock 结算，符合本轮观察。引擎返回成功与所有业务命令已完成必须分开；没有 fill 回调时相应 callback 一致性检查记为 `null`，不会用空集合的“全部通过”代替验证。

S3 adapter 必须保存最终订单状态和完成范围；本例 SUBMITTED 不得被当成“未找到反例”或一次完整评价。取消命令和止损/GTD/定时器在数据末尾的其他组合仍需后续验证，不能从这一个案例推断所有结束语义。

## 6. 选择门与仍未成立的能力

| 能力 | 本轮证据 | 条件式结论 |
| --- | --- | --- |
| 公共 L2 delta + trade 输入 | 实际多档快照、增量与交易驱动已运行 | 可进入 S3 有限 adapter 契约 |
| 逐次 partial fill 回调 | 分时与同刻都观察到两次独立 callback | 可按该公开路径设计审计记录；不能承诺所有订单类型无损 |
| 回调内 position/cash/fee | 本例每次回调及最终状态均一致 | 未见本例账务异常；仍需回归矩阵 |
| 同刻取消竞态 | 0 / 1 s 两种 latency 有可重复、可解释结果 | 支持规则必须文档化，不能代表真实撮合真值 |
| EOF 在途命令自主推进 | 无后续数据时保持 SUBMITTED | **不支持该默认假设**；必须限制或显式 incomplete |
| S6 精确前撤/后撤解释 | 本轮未构造、未验证 | **gate closed**，不得输出两个相容世界证书 |
| checkpoint / 跨平台 / 真实数据 / 性能 | 本轮未验证 | 不纳入本次 Go 范围 |

因此可以建议 **conditional Go：以固定 v1 的公开 L2、TradeTick、订单/持仓事件为 S3 adapter 的有限基础，同时强制终止完整性检查**。这不是产品完整可行性批准，也不是“所有选型门已关闭”。维护者仍需决定 LGPL 依赖/分发边界、固定支持矩阵、能力不支持时的拒绝路径和后续维护责任。

本次没有修改第三方源或 binary，没有发送上游 issue、PR、评论或邮件。运行出现 Pandas 弃用警告（`Timestamp.utcnow` 与小写频率 `d`）；结果保存了当前固定环境，尚未验证未来 Pandas 兼容，不将警告视为已经修复。

## 7. 结果、重复性与复跑

- [第一次最终运行](../../research/spikes/nautilus/results/l2-selection-run-a.json) 与 [第二次最终运行](../../research/spikes/nautilus/results/l2-selection-run-b.json)：6 个案例的完整输入、决策、fill 和回调内状态。
- [比较摘要](../../research/spikes/nautilus/results/l2-selection-comparison.json)：两次独立进程输出逐字节相同，SHA-256 为 `e710002f27e7fde245297b53767bd2306979d4bf5c58477df2e3d1182e81634c`。
- [初次探索记录](../../research/spikes/nautilus/results/l2-initial.json)：保留加入 trade ID、L2 缓存档数和显式 completeness 检查之前的原始结果。

排除的只有随机 event UUID、run/instance ID、墙钟耗时及日志；业务时间、trade ID、callback 顺序、费用和未决状态全部保留。本轮不报告吞吐或 P99。

在仓库根目录使用既有独立环境：

```sh
/private/tmp/tickwitness-s01-nautilus/venv/bin/python research/spikes/nautilus/run_l2_probe.py --output /private/tmp/tickwitness-s01-nautilus/l2-repeat-a.json
/private/tmp/tickwitness-s01-nautilus/venv/bin/python research/spikes/nautilus/run_l2_probe.py --output /private/tmp/tickwitness-s01-nautilus/l2-repeat-b.json
cmp /private/tmp/tickwitness-s01-nautilus/l2-repeat-a.json /private/tmp/tickwitness-s01-nautilus/l2-repeat-b.json
```

脚本记录每个 case 的 `execution_status`、期望、实际检查和 `completeness`；错误保留为 ERROR，不会为了与预期吻合而改成交或伪造成功。两个同机重复不能替代独立环境复验或完整 S3 / S6 验收。
