# S01-01：HftBacktest 可行性 spike

记录日期：2026-10-25。项目：TickWitness。状态：**已完成本机有限 spike；正式 adapter、完整 trace 契约和生产支持尚未实现。** 本文不替代 S2 引擎选型 ADR，也不声明 S01-01 的全部跨引擎比较工作已完成。

本次结论：**HftBacktest 2.4.4 可以在当前 macOS arm64 / CPython 3.12.14 上安装并运行受控 L2 合成案例，值得保留为默认引擎候选。** 能读到订单状态、执行价格/数量、持仓、cash 与 fee；策略决策日志需要自行记录。完整多次部分成交事件流、EOF drain、任意 Python 队列解释注入和完整 checkpoint 恢复均未成立为已验证能力，应作为后续选型门槛。

实施次序以 [路线图](../planning/roadmap.md)、[Sprint backlog](../planning/sprint-backlog.md) 和 [ADR-003](../architecture/decisions.md) 为准：S1 比较候选的可行性，S2 选择默认目标，S3 完成 adapter 后建立同语义基线。这里的两次确定性运行不是性能 benchmark。

## 1. 本次实际做了什么

1. 读取官方 PyPI、release tag 源码和项目文档，核对版本、发行文件、模型与公开接口。
2. 在 `/private/tmp/tickwitness-s01-hft/.venv` 建立独立环境，从官方 PyPI 安装固定包及依赖；未修改项目根 `.venv`、`pyproject.toml` 或正式依赖。
3. 用 8 条人工生成的 L2/成交记录驱动一个固定可信策略；其中 6 条为业务事件，2 条为尾部 guard。
4. 在两个独立 Python 进程中各执行一次相同脚本，比较规范化 trace 的完整字节，并检查手算账务。
5. 保存脚本、两份 trace、环境、依赖快照、PyPI 文件摘要和已安装代码哈希。

本次没有连接交易所、采集实盘、使用账户或凭据、发送真实订单，也没有实现正式 `ReplayPort` adapter。

实验文件与复跑步骤见 [spike README](../../research/spikes/hftbacktest/README.md)。

## 2. 版本、平台与许可

| 项目 | 已核实信息 | 证据级别 |
| --- | --- | --- |
| PyPI 当前页面与本次固定版本 | 2.4.4；发布文件上传于 2025-12-10 | 官方发行元数据，本机成功安装 |
| Python 要求 | 该发行包 metadata 与 `py-v2.4.4` 的 `pyproject.toml` 均为 `>=3.11` | 包 metadata 与固定 tag 源码 |
| 本机 | macOS 27.0.1，Darwin arm64，CPython 3.12.14 | 本机实际记录 |
| 本机 wheel | `hftbacktest-2.4.4-cp312-cp312-macosx_11_0_arm64.whl` | 官方文件存在，本机 wheel 安装成功 |
| 其他 wheel | CPython 3.11–3.14，以及部分 PyPy 3.11 文件；macOS arm64/x86_64、Linux glibc/musl 的 x86_64/aarch64/armv7l、Windows amd64 标签出现在文件清单 | 仅发行文件存在，未执行其他组合 |
| 许可 | 上游 MIT；保留版权与许可通知，独立于 TickWitness 的 Apache-2.0 | 固定 tag LICENSE 与包 classifier；传递依赖仍需单独清单检查 |

本机 wheel 的官方 SHA-256 为 `a61c7cc00fdfa498e4d20ee0c30dfcc8d184c8e7e7f2a5ea4ac50810f09101bb`。完整 52 个 wheel 文件名、哈希与上传时间保存于 [release-metadata.json](../../research/spikes/hftbacktest/results/release-metadata.json)。文件存在不保证每个 Python/平台组合的全部依赖均可解析和正常运行。[PyPI 2.4.4](https://pypi.org/project/hftbacktest/2.4.4/)、[官方 release metadata](https://pypi.org/pypi/hftbacktest/2.4.4/json)。

系统自带 Python 3.9.6 不满足发行要求；本次使用已经存在的 CPython 3.12.14，没有修改系统 Python。ReadTheDocs 首页仍写 Python 3.10+，与该包要求不同；发行兼容性以固定包 metadata 与实际安装为准。源码版本采用上游 `py-v2.4.4`，没有把 `master` 或 `latest` 的漂移描述成固定发行能力。[固定版本 pyproject](https://github.com/nkaz001/hftbacktest/blob/py-v2.4.4/py-hftbacktest/pyproject.toml)、[ReadTheDocs 首页](https://hftbacktest.readthedocs.io/en/latest/)、[固定版本 LICENSE](https://github.com/nkaz001/hftbacktest/blob/py-v2.4.4/LICENSE)。

安装得到 `numpy==2.2.6`、`numba==0.68.0`、`llvmlite==0.50.0`，以及绘图/分析依赖共 44 个包。上游约束为 `numpy>=2.0,<2.3`、`numba~=0.61`，并依赖 polars、matplotlib、holoviews；它们可能影响主工程依赖选择，不能在选型前直接加入主环境。本次确切解析快照见 [requirements.lock.txt](../../research/spikes/hftbacktest/requirements.lock.txt)。

首次 sandbox 网络访问 PyPI 因 DNS 受限失败；随后使用已授权的网络权限，只从 `pypi.org` / 官方包文件源完成安装和 metadata 获取。这个失败属于运行环境限制，不是 HftBacktest 安装失败。包安装后 fixture 离线执行成功。

## 3. 可核算的最小 fixture

参数全部人为设置，不是实测市场延迟或校准模型：

| 参数 | 值 |
| --- | --- |
| 资产与精度 | linear contract size 1；tick size 1；lot size 1 |
| 初始可见买/卖盘 | 99 / 101，各 2 单位 |
| queue model | 显式 `risk_adverse_queue_model()` |
| exchange model | 显式 `partial_fill_exchange()` |
| feed / entry / response latency | 100 / 10 / 10 ns |
| maker / taker fee | 0.001 / 0.002，按成交额 |
| 策略 | 看到双边报价后买 1 单位，收到该订单 FILLED 后在 101 卖 1 单位；均为 GTX LIMIT |
| 驱动方式 | `wait_next_feed(include_order_resp=True, timeout=10000)`；每个返回边界读取状态 |

人工 sell trade 在 99 成交 3 单位，足以消耗该模型中的 2 单位前方可见队列，再成交己方买单 1 单位；稍后人工 buy trade 在 101 做相同操作，成交己方卖单。该案例使用支持部分成交的 exchange model，但**每张己方订单只有一次完整 fill**，所以它没有验证分多次部分成交时的日志完整性。

两次最终结果：

| 检查 | 本次结果 |
| --- | --- |
| 输入 / 策略决策 / 观测边界 | 8 / 2 / 14 |
| 观察到的己方成交 | 买 99 × 1，卖 101 × 1 |
| 最终持仓 | 0 |
| gross cash change | `-99 + 101 = 2` |
| 累计 fee | `99×0.001 + 101×0.001 = 0.2` |
| net cash change | 1.8 |
| 两份 trace | 逐字节相同 |
| trace SHA-256 | `6cae5b861917f611a7b0931c791a0512919282bdc671ffed8a9d3cea68b215d7` |

完整输出见 [第一次 trace](../../research/spikes/hftbacktest/results/run-a/trace.json)、[第二次 trace](../../research/spikes/hftbacktest/results/run-b/trace.json) 与 [比较记录](../../research/spikes/hftbacktest/results/comparison.json)。脚本排除运行 ID、墙钟耗时和文件位置等不属于业务语义的字段；环境另存。费用断言采用 `1e-12` 绝对容差。这个小例子的合成收益只验证执行与账务，不支持任何 alpha、真实收益或模型准确性结论。

买决策时间为 `1000000101`，卖决策时间为 `1000001010`。卖决策发生时公开 sell-trade feed 的本地到达时间 `1000001100` 尚未到来，但买单 fill 的响应已经到达；这符合例中 order response 比公开 feed 更快的设定。不能据此误判前视，也不能拿这个人工时间差当真实交易所测量。

## 4. 必要 trace 能力与缺口

| 必要能力 | 本机已验证 | 文档/源码支持与缺口 |
| --- | --- | --- |
| 输入事件身份与时间 | 脚本保留原始 8 行、外部分配 `input_id`、exchange/local 时间 | `event_dtype` 提供时间、类型、价格、数量等字段；引擎没有替 TickWitness 提供原始采集序列/许可/clock evidence 契约 |
| 决策记录 | 受控策略显式写入决策时间、理由、订单 ID 和可用事件引用 | 策略自己 instrument；本次不是引擎自动捕获任意策略决策 |
| 订单生命周期 | 轮询到提交、NEW、FILLED；读取价格、数量、剩余量、执行量/价和相关时间 | `orders()` / `Order` 提供状态；清除 inactive orders 前必须先落审计记录 |
| 自身 fill 记录 | 本例两个单次 fill 可从订单与资金状态核算 | 订单状态是快照，不是已验证的 append-only fill sink；同刻多 fill、重复读取、部分成交合并/覆盖需要后续测试或 Rust hook |
| 资金与持仓 | 读取 `state_values()` 的 balance、fee、position、num_trades、volume/value，手算一致 | 引擎字段使用 f64；正式领域账本的精确金额、舍入、容差与追溯仍需 adapter 契约 |
| EOF 语义 | 实际终止时刻为 `1000004100`；最后 guard 的 local time 为 `1000004101`，尚未可见 | 本例业务成交已早于尾部 guard 完成；不能宣称所有输入都已本地消费，必须补 EOF drain/在途响应测试 |
| 首次分歧定位 | 尚未执行配对情景 diff | 保留了决策与输入引用，但无差异场景，不能把轨迹存在当成已实现 diff 工具 |

源码依据为固定发行的 [Python binding](https://github.com/nkaz001/hftbacktest/blob/py-v2.4.4/py-hftbacktest/hftbacktest/binding.py)、[Order](https://github.com/nkaz001/hftbacktest/blob/py-v2.4.4/py-hftbacktest/hftbacktest/order.py)、[StateValues](https://github.com/nkaz001/hftbacktest/blob/py-v2.4.4/py-hftbacktest/hftbacktest/state.py) 和 [C/Rust backtest exports](https://github.com/nkaz001/hftbacktest/blob/py-v2.4.4/py-hftbacktest/src/backtest.rs)。本机安装文件的哈希保存在 release metadata，便于区分查阅版本和执行版本。

`available_input_ids` 是本例按 local timestamp 计算的外部可用集合；不是直接从引擎取得的逐条 receipt hook，也不证明相同时间戳多事件的内部顺序。`last_trades()` 返回市场公开成交，不能充当自己订单的成交日志。正式 adapter 至少需要稳定 decision wrapper、order-response/fill 捕获和错误码映射；关键遗漏无法可靠弥补时应缩小能力或判 no-go。

订单快照的 `local_timestamp_ns` 表示上游记录的本地下单请求时间，不能当作响应到达时间；后者在本例用 trace 边界时间记录。执行价格/数量仅在 FILLED / PARTIALLY_FILLED 状态有效，早期状态中的默认零值不代表成交。

## 5. 队列、延迟与情景扩展

固定版本 Python builder 暴露保守队列、多种 log/power 队列、L3 FIFO、constant/interpolated order latency、feed latency offset、两种 exchange model，以及成交额/数量/每笔费用模型。默认值包含一种队列选择和零延迟；本例全部显式设置，没有把默认配置当作研究假设。[固定版本 builder 源码](https://github.com/nkaz001/hftbacktest/blob/py-v2.4.4/py-hftbacktest/src/lib.rs)。

本机只实际执行了保守队列、固定订单延迟和一种费用模型。其他 builder 方法经安装包公开方法清单和源码核对，**未运行其行为契约测试**。文档说明 feed latency 由 exchange/local 双时间表达，订单 entry 与 response latency 分开建模；自定义 latency / queue model 需要实现 Rust trait，不能据此声称 wheel 允许直接传入任意 Python callback。[延迟模型](https://hftbacktest.readthedocs.io/en/latest/latency_models.html)、[队列与成交模型](https://hftbacktest.readthedocs.io/en/latest/order_fill.html)。

对 TickWitness 的意义：

- 新增接收延迟压力可以先在受约束输入变换中表达，再由引擎重新决策；需要保留 exchange/local 顺序和原始引用，并重新验证合法性。本次没有完成此变换。
- 选择两种现成队列模型可以检查模型敏感性，但不自动构成两个严格的观测相容解释。要表达具体撤单前后位置或有证据的时钟区间，需明确约束，并验证公开模型能否表达；不能用模型名称代替可行性证明。
- Python 绑定对队列/延迟使用固定 enum 选择。任意自定义解释的完整接入可能需要改 Rust builder/binding 并重编译，而非只写 Python adapter；这一成本必须进入 S2 比较。
- L2 的聚合数量无法证明真实队列位置。历史回放不会因模拟订单而改写真实市场路径，因此不提供完整 market impact 反事实。保守成交模型也不等于 PnL 下界。[官方成交模型限制](https://hftbacktest.readthedocs.io/en/latest/order_fill.html)。

## 6. Checkpoint 与恢复

本次检查的公开 Python 接口有市场深度 `snapshot()` 和 builder `initial_snapshot()`，但没有验证到完整引擎状态的保存/恢复契约。订单簿快照没有包含策略内存、未完成订单、资金、数据 reader cursor、在途消息、队列模型内部状态及随机源；不能把它标成 TickWitness 所需的完整 checkpoint。[固定版本 Python binding](https://github.com/nkaz001/hftbacktest/blob/py-v2.4.4/py-hftbacktest/hftbacktest/binding.py)、[builder](https://github.com/nkaz001/hftbacktest/blob/py-v2.4.4/py-hftbacktest/src/lib.rs)。

首个 adapter 应暂声明 `checkpoint_resume_verified=false`；如果决定支持它，须追加独立恢复实验。现阶段合法 witness 缩减可以每次从有效原始起点重放必要前缀，不依赖完整状态导出。若未来复用 checkpoint，必须绑定协议、策略、引擎、seed 和情景前缀语义；改变前缀的延迟或队列解释后，不能直接加载基线策略状态。

## 7. S2 选型条件与后续最小试验

| 门槛 | 当前判断 | 最小后续工作 |
| --- | --- | --- |
| 当前开发机可安装与可信回放 | 通过本次有限 spike | 选定环境后纳入固定支持矩阵 |
| 可读决策/订单/资金证据 | 单订单受控路径可行 | 将 wrapper 方案与 adapter 契约一并设计，不用轮询结果宣传完整审计流 |
| 多次部分成交及同时间事件 | 未验证；可能需要更底层 hook | 一个订单连续两次部分成交、同刻多 fill、cancel/fill race、相同时间戳事件夹具 |
| 数据末尾与在途响应 | 已观察到尾部 guard 未本地消费 | 只含最后成交/最后响应的 EOF fixture，定义应继续 drain 还是明确 incomplete |
| 受约束队列解释 | 内置选择可用，具体相容世界未验证 | 一个已知撤单案例，核对能否实现前/后位置解释及对应 trace |
| 完整 checkpoint resume | 未验证，不作为首版前置条件 | 先从头重放；确有需求再评估 Rust 状态导出与等价性 |
| Linux / 其他 Python / CI | 有官方 wheel，未实测 | 与另一候选比较后仅测选中的正式支持组合 |
| 依赖与发行维护成本 | 主包可装，但带较大分析/可视化依赖树 | 对比最小部署、依赖兼容和定制 Rust build 的维护投入 |

若首个场景要求只靠现成 Python wheel 即可取得不可丢的每次 fill、任意队列解释及完整恢复，本次证据不足以批准该范围；应补最小试验、接受受限首版或更换目标。当前只支持“候选可继续”，不提前确定默认引擎，也不把未实现的 adapter、回放安全沙箱或真实性校准写成成果。
