# S2：HftBacktest 2.4.4 队列与 trace 选型门槛补测

日期：2026-10-25。状态：**本机合成研究补测已执行；不是正式 adapter、已冻结协议或完整可行性证明。** 本文补充 [S01 原始 spike](hftbacktest-feasibility.md)，不改写旧实验记录。默认引擎的最终选择由 [ADR-003](../architecture/decisions.md) 记录。

结论：**可以有条件选择 HftBacktest 2.4.4 作为 S3 受限 L2 / 单次完整成交轨迹路径的目标；不能因此开放 S6 的精确前撤/后撤相容见证、部分成交策略账务或无损逐笔 fill 日志。** 本次明确发现部分成交账务不一致、同刻响应合并和 EOF 时公开时钟陈旧，相关能力应 fail closed。需要该完整范围时，当前现成 Python wheel 为 no-go，须另立上游修复、受控 Rust trace hook 或替代引擎验证任务。

许可仍按已核实的上游 MIT；实际运行固定为 `hftbacktest==2.4.4`，不是 `master` 或未来版本。当前环境为 macOS arm64 / CPython 3.12.14、NumPy 2.2.6、Numba 0.68.0，沿用独立临时环境，没有修改主工程依赖。[固定 tag LICENSE](https://github.com/nkaz001/hftbacktest/blob/py-v2.4.4/LICENSE)、[固定包要求](https://github.com/nkaz001/hftbacktest/blob/py-v2.4.4/py-hftbacktest/pyproject.toml)。

## 1. 实验范围与证据

脚本为 [run_queue_probe.py](../../research/spikes/hftbacktest/run_queue_probe.py)。它执行 20 个固定合成案例：7 种 builder 配置 × 有撤单/无撤单两种输入，加 3 个部分成交驱动案例和 3 个 EOF 案例。没有实盘、交易账户、联网采集、生产 adapter 或 Rust 修改。

- [最终运行 A](../../research/spikes/hftbacktest/results/queue-selection-final-a.json)、[最终运行 B](../../research/spikes/hftbacktest/results/queue-selection-final-b.json)：完整输入、策略决策、原始轮询状态、receipt latency、源公式估计与整数 oracle。
- [首次探索记录](../../research/spikes/hftbacktest/results/queue-probe-run-a.json)：尚未加入 receipt latency 字段的原始结果，保留异常与不符合期望的案例。
- [增加 receipt 观测后的探索记录](../../research/spikes/hftbacktest/results/queue-selection-run-a.json)：用于区分“事件没处理”与“公开时钟陈旧”。
- [比较及 gate 摘要](../../research/spikes/hftbacktest/results/queue-selection-comparison.json)：两次最终运行比较、检查失败项与门槛。

JSON 的 `status=EXECUTED` 只表示 probe 完成，不表示正确性期望通过。未通过的部分成交与终止时钟检查原样保留；不通过改写输出或丢弃案例凑出“通过”。`observation_compatible_witness_certified` 与 `fill_event_sink_certified` 都保持 false。

结果不包含墙钟执行时间、随机 run ID、native pointer 或环境绝对路径；模拟事件时间、引擎 receipt 时间和状态均保留。两次相同结果只证明本机这些固定案例可重现，不是性能基准或跨平台保证。

## 2. claim-draft-001 的具体队列解释

[草案 001](../discovery/claim-draft-001.md) 规定：买价 100 上先有 1000 lots，己方买 1 lot 随后加入；外部再加 1000 lots；无成交地撤去 1000；最后同价主动卖出 1 lot。FIFO 与小订单不改变录制行情是显式近似。固定成交费为 1，102 只给期末 evaluator，不提供给策略。

脚本按这些顺序生成并保存同一份 L2 输入，使用固定的 exchange/local 时间和 10 ns entry/response latency。己方订单在初始双边报价后提交并获接纳，早于新增外部量 B。构造的整数 oracle 为：

| 显式解释 | C 撤单后 ahead / behind | D 的己方 fill | 净标记损益 / 命题真假 |
| --- | --- | --- | --- |
| Q-front：撤前方 1000 | 0 / 1000 | 1 | `102−100−1=1`，true |
| Q-back：撤后方 1000 | 1000 / 0 | 0 | 0，false |

这些 oracle 用于展示明确分配和检验期望，**不是 HFT 执行所得的两个见证，也不是正式可行性验证器**。本轮没有把任一内置模型重命名成 Q-front。

### 内置模型的实际输出

| Python builder 配置 | 源公式对 C 后 ahead 的估计 | 本机己方 fill | 能否因此当作精确 Q-front |
| --- | --- | --- | --- |
| `risk_adverse_queue_model()` | 1000 | 0 | 不能；在这个指定案例与 Q-back 的行为一致 |
| `log_prob_queue_model()` | 500 | 0 | 不能 |
| `log_prob_queue_model2()` | 约 908.879 | 0 | 不能 |
| `power_prob_queue_model(2)` | 500 | 0 | 不能 |
| `power_prob_queue_model2(2)` | 250 | 0 | 不能 |
| `power_prob_queue_model3(2)` | 750 | 0 | 不能 |
| `power_prob_queue_model2(16)`，诊断参数 | 0.0152587890625 | 1 | 不能；非零分数 ahead 经 lot 舍入后触发 fill，不是把 1000 撤单明确分配到前方 |

表中 ahead 是按照固定源码公式计算的旁路估计，标注 `SOURCE_DERIVED_NOT_PUBLIC_ENGINE_QUEUE_OBSERVATION`；公开 Python 订单接口未提供对应 ahead 值。fill 是实际引擎输出，两者不能互相冒充。

固定源码表明 RiskAdverse 在深度改变时用 `min(ahead,new_qty)`；ProbQueue 用概率函数直接更新浮点 ahead，并非随机采样一个带撤单身份的世界。`is_filled` 又按 lot size 舍入可执行量。指数 16 专门用于暴露数值/模型敏感性，不是预注册或校准过的前撤模型。[固定 queue.rs](https://github.com/nkaz001/hftbacktest/blob/py-v2.4.4/hftbacktest/src/backtest/models/queue.rs)。

无撤单负例中，D 改为 1001 lots 主动卖出，7 种配置都实际得到 1 lot fill、费用 1、净标记损益 1，与整数对照一致。这说明同名/异名模型本身不会构成不可识别结论；也不能因为指数 16 在有撤单例中翻转，就出具 `NOT_IDENTIFIABLE_WITHIN_MODEL`。

**S6 gate 仍关闭。** 当前 wheel 可做模型敏感性实验；要把明确的撤单前/后分配作为两个相容世界重放，仍需有 typed 场景约束、逐步队列证据和独立可行性检查。Python builder 只暴露固定模型选择；自定义 queue trait / builder 接入与可观测 trace 要单独评估维护成本，本轮不改 Rust。[固定 Python/Rust builder](https://github.com/nkaz001/hftbacktest/blob/py-v2.4.4/py-hftbacktest/src/lib.rs)。

## 3. 一单两次部分成交：实际账务不一致

另立 fixture，不将其冒充原草案的一单位订单：己方买单数量 2；接纳时前方 1，之后外部追加 3；第一次 trade 2 消耗前方 1 并成交己方 1，第二次 trade 1 成交剩余 1。可见外部量足够支持录制成交；深度更新也按录制 trade 相应减少。费用为每次 fill 固定 1。

不同 exchange 时间、逐次 `wait_next_feed(True)` 的实际观测：

| 观察点（相对 ns） | 订单状态 / leaves / last exec | 引擎本地 position / cash / fee / num_trades |
| --- | --- | --- |
| 1010，第一次响应 | PARTIALLY_FILLED / 1 / 1 | 0 / 0 / 0 / 0 |
| 2010，第二次响应 | FILLED / 0 / 1 | 1 / −100 / 1 / 1 |
| 手算与订单剩余量所要求的最终值 | 累计成交 2 | **2 / −200 / 2 / 2** |

不是没有发生第一个 partial fill：订单 leaves、执行数量和响应时间都显示它存在。固定源码的 local processor 只在收到 `Status::Filled` 时 `apply_fill`，没有对 `PartiallyFilled` 做相同账务更新，与本例结果吻合。[固定 local.rs](https://github.com/nkaz001/hftbacktest/blob/py-v2.4.4/hftbacktest/src/backtest/proc/local.rs)。

因此不能只在报告尾部“补算”就宣称 partial-aware 策略正确：策略在运行中调用 `position()` 已会看到遗漏第一笔成交的状态。正式支持需要上游修复或经验证的执行状态边界，不能掩盖为普通浮点容差。当前 partial-fill 账务 gate 为 **CLOSED**。

### 轮询也不能保证逐笔成交完整

- 两个 trade 的 exchange timestamp 相同、对应两条响应也同刻到达时，一次 wait 返回后已是 FILLED，leaves 从 2 直接到 0，`last_exec_qty` 只有最后的 1。中间 PARTIALLY_FILLED 未作为独立 Python 返回边界可见。
- 用较粗 `elapse(3500)` 驱动时，即使两次 fill 的 exchange 时间不同，也只能读到最后状态。
- 本例无修改/撤单，可以从 leaves 差额推导“累计执行量跳了 2”，但推不回全部逐笔价格、费用、顺序与原因；这种旁路推导不是通用 fill ledger。

上游 local processor 在一次接收调用中循环处理同刻响应，Rust 层留有 handler 形式，常规 Python 路径未暴露无损逐笔 callback。本轮没有实现 trace hook；需要独立任务和验收，不能把轮询封装直接宣传为完整审计流。

## 4. EOF：响应会处理，但公开 current_timestamp 可能陈旧

EOF probe 把 fill 放在最后 trade，exchange time 为 +1000，行情 local time 为 +1100，order response latency 为 200，因此响应处理时间应为 +1200。

| 案例 | 第一次 EndOfData 返回时 `current_timestamp` | `order_latency` 记录的响应时间 | 最终己方成交与账务 |
| --- | --- | --- | --- |
| 无 guard | +1100 | +1200 | 已处理该 fill，position 1 / cash −100 / fee 1 |
| guard 在响应之前（local +1150） | +1150 | +1200 | 已处理该 fill |
| guard 在响应之后 | +1600 | +1200 | 已处理该 fill；最后 guard 的 `feed_latency` 是 +1700 |

两次额外 `wait_next_feed` 和一次额外 `elapse` 都继续返回 EndOfData，公开时钟不追上已处理事件。固定主循环在没有下一项时直接返回 EndOfData，公开 `cur_ts` 的更新路径与中途返回不同，支持“终止时钟陈旧”的解释。[固定 backtest 主循环](https://github.com/nkaz001/hftbacktest/blob/py-v2.4.4/hftbacktest/src/backtest/mod.rs)。

**这是对 S01 报告中一项推断的更正：** 当时仅凭 `current_timestamp` 小于最后 guard 的 local time，写成最后 guard 尚未本地消费；该推断证据不足。本轮 `feed_latency` 明确显示最后 guard 已被 local processor 处理。旧 JSON 和旧报告保留，本补测以更完整 receipt 字段取代那项解释。

同理，不能把“终止快照在 +1100 已显示响应”说成响应物理上提前到达：本例 `order_latency` 明确记为 +1200，而陈旧的是外层当前时间。adapter 不得把 EndOfData 快照的 `current_timestamp` 直接作为最后响应的接收时间、最后数据消费位置或时点可见性证明。

S3 至少需明确终止快照、实际 receipt 时间、数据覆盖与完成条件的契约；未实现前应拒绝给终止时钟范围作认证。为输入追加人为市场 guard 不是默认生产修复，更不能改写历史来遮盖终止语义问题。

## 5. 供 ADR-003 使用的条件式结论

| 能力 | 本次 gate | 可接受的下一步 |
| --- | --- | --- |
| 固定版本安装、受控 L2 重放、单次完整 fill | 有限案例可行 | 可作为 S3 默认 adapter 的受限目标；保持明确能力矩阵 |
| 精确 Q-front / Q-back 相容见证 | **关闭** | S6 前补 typed 撤单分配、可观察队列证据和独立可行性验证；不能使用模型别名替代 |
| 部分成交策略账务 | **关闭，实测不一致** | 在修复和运行中状态回归通过前拒绝该能力；不得用最终报告补账掩盖策略已见错误状态 |
| 无损逐笔 fill trace | **关闭，同刻合并已见** | 自定义受控 trace hook 或其他公开事件接口经独立测试后再启用 |
| 终止 current_timestamp 可用作 receipt 证明 | **关闭，实测陈旧** | 原始 receipt 与完成语义单独建模，补末尾订单、响应和数据覆盖契约测试 |
| 完整 checkpoint / resume | 本轮未验证 | 继续从有效前缀重放，维持原 gate |

若选择 HFT，应把限制写进 ADR 和 capability contract：首期可信、单资产、单 lot / 单次完整执行的受控路径，拒绝任何实际出现的 partial 状态或不一致；不承诺相同时间戳复杂生命周期、任意策略、通用真实 fill 或真实市场可识别性。`NoPartialFillExchange` 若日后采用，也必须作为明示的不同执行协议，不能悄悄替代。

本轮没有正式签发 `COUNTEREXAMPLE_FOUND` 或 `NOT_IDENTIFIABLE_WITHIN_MODEL`。这里只保存选型研究发现与原始例子，供工程 gate 决策；不把仍未冻结的 claim-draft-001 标成已获两个 HFT 有效见证。

## 6. 复跑

沿用 [S01 固定依赖](../../research/spikes/hftbacktest/requirements.lock.txt)，在仓库根目录执行：

```sh
/private/tmp/tickwitness-s01-hft/.venv/bin/python research/spikes/hftbacktest/run_queue_probe.py --output /private/tmp/tickwitness-s01-hft/selection-a.json
/private/tmp/tickwitness-s01-hft/.venv/bin/python research/spikes/hftbacktest/run_queue_probe.py --output /private/tmp/tickwitness-s01-hft/selection-b.json
cmp /private/tmp/tickwitness-s01-hft/selection-a.json /private/tmp/tickwitness-s01-hft/selection-b.json
```

脚本把 probe 错误记录为 `status=ERROR` 并保留 case ID，不把参数或期望强行改到通过。选择 gate 结论需要结合原始 trace、固定源码和本节范围审阅，不能仅凭脚本退出码 0 决定放行。
