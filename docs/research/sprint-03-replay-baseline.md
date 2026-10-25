# S3：有限回放适配器的重复性与原始耗时基线

状态：**本机固定 qualification 已完成 10 次独立进程语义重复与 1 次已知输入变化定位**。测量时间为 2026-10-25 16:28 UTC（新加坡 2026-10-26 00:28）。这份微型基线只支持下面列出的有限工作负载；不代表完整 S3 范围、跨平台或研究判定已经验收。

本轮对象是固定版本 NautilusTrader stable v1 的单资产、内置买单 qualification。输入为 TickWitness 原创微型合成 L2 / trade 行情。它不执行 FrozenProtocol 或用户策略源码，不计算研究命题的成立与否，也不输出收益有效性或实盘真实性结论。S2 已确认的部分成交、回调账务与 EOF 边界见 [L2 选择门](nautilus-l2-selection-gates.md)。

## 1. 比较语义

[comparison.py](../../src/tickwitness/domain/replay/comparison.py) 只接收统一契约已经验证的 `ReplayResult`，不提供另一套宽松 JSON 解析。比较保存全部 engine、environment、specification 和 data 条件差异；任一条件不同均令 `strictly_paired=false`。相同 trace 不能抵消这些条件差异。

`strictly_paired` 表示结果 envelope 中上述已记录条件一致，不认证未记录的硬件、依赖内容或隐含状态。benchmark 另存安装模块哈希与机器观察以补充本次复跑证据。比较对象的 canonical bytes 从两个已验证 DTO 派生，不能直接用任意 JSON bytes 构造一份“有效比较回执”。

语义比较覆盖 `input_trace`、`decision_trace`、`order_trace`、`fill_trace`、`account_trace`、`execution_status` 和 `completeness`。不删去同时间戳的第二笔成交，不忽略 bootstrap 行、订单未决状态或现金/持仓末状态。结果只包含稳定语义内容；耗时位于独立 benchmark 摘要，不进入结果身份。

规范化采用统一结果 schema 与排序 key 的紧凑 UTF-8 JSON；价格、数量和费用的 native/精确十进制文本按实际字段保留，不靠舍入或数值容差隐藏差异。native 随机 event UUID、engine run/instance ID、日志与墙钟耗时不属于该结果 schema；确定性的 client order ID、native trade ID、源事件时间、绑定时间与 trace 顺序均保留。比较器不再从已验证结果里额外删字段。

`first_divergence` 使用 JSON Pointer、trace channel、该 channel 内的 ordinal，以及双方的 source event reference 定位变化；missing row 通过显式 presence 字段区分于 JSON null。`first_decision_divergence` 另外定位决策通道的首处分歧，即使更早已发现输入内容改变。JSON boolean 与 integer 严格区分。

扫描顺序固定为 input → decision → order → fill → account → execution status → completeness。这是可复核的比较顺序，**不表示不同通道回调之间的全局时间顺序或真实交易所因果顺序**。source reference 表示使该 native 处理/结算步骤发生的源输入；对延迟命令不能据此声称该输入是成交的唯一经济原因。

## 2. 实际测量方法

[benchmark_replay.py](../../scripts/benchmark_replay.py) 在安装了 TickWitness wheel 与固定 native 依赖的独立环境中执行了 10 次相同 qualification。父进程和每个工作子进程均启用 `-I`；测量区间只围绕 adapter 的 `run` 调用，以 `perf_counter_ns` 保存原始 nanoseconds，不包含 Python 启动与调用前的准备。`run` 内发生的懒加载和重复 guard 计入耗时，不能声称已排除所有 import。每次结果都经过统一领域验证，并与第一份结果比较。

摘要另存父进程观测的 `worker_wall_ns`：包括子进程启动、fixture 规范化与封存、preflight、`run`、输出序列化与退出。两种原始时间都保留，不把差值标成“纯启动耗时”或“adapter 开销”。操作系统文件缓存、动态库加载缓存和硬件状态没有重置；新进程不等于全冷机器。

脚本要求十份结果条件一致、所有语义通道及 completeness 一致；失败、中断或环境差异均使该次脚本失败，不能把九次成功描述为十次一致。保存单份 golden result、十次耗时与结果摘要、运行环境指纹，以及一个已知输入变化的实际运行比较。原始行情和内置策略均为本仓库原创，不复制第三方数据或引擎二进制。

这些微型耗时包含 adapter 的输入翻译、native engine 构建/运行/释放以及结果整理，不能称作 native 核心撮合耗时，也不能由此推算产品 events/s、P99、百万事件性能或 ≤20% 包装开销。后者需要双方同语义、同工作量的独立对照实验，当前未执行。

## 3. 时钟、关联与结束语义

- qualification 的 native clock binding 必须由 spec 显式指定；原始 event / receive 时间与捕获顺序保留，不能将合成绑定称作真实 UTC 验证。
- 同刻输入保留确定性顺序，不以线程调度或时间戳去重决定先后。
- native 回调的源事件关联必须在行情进入撮合前设置；不能仅依赖策略最近一次收到的 trade 回调倒推，因为成交可能先于该回调发生。
- 正常返回不等于在途命令已排空。EOF 尚有 SUBMITTED、INITIALIZED 或 PENDING 类命令时必须标记 incomplete；不添加伪造未来行情来制造完成。
- 资格结果的 `completed` 只描述该受限工作负载与所列结束规则，不批准研究声明、其他订单类型、跨资产执行、checkpoint 或精确撤单前后见证。

## 4. 本机实测证据

实际环境为 CPython 3.12.14、macOS 27.0.1 arm64，操作系统报告 10 个逻辑 CPU；没有设置 CPU 配额或清空系统缓存，也没有测量 RAM/磁盘性能。native 为 `nautilus-trader==1.231.0` stable v1，其他实际依赖版本逐项保存在 [summary.json](../../research/baselines/sprint-03/results/summary.json)。没有安装或调用 v2 API。

本次安装的 `tickwitness-0.0.1.dev0-py3-none-any.whl` SHA-256 为 `12ed6cc534e59111abbcaf19e3c721d6b69254b187364439737e5550d3a1ff1e`。摘要同时记录实际安装的桥接源码、adapter 源码、native engine binary 和 benchmark 脚本哈希；桥接源码 hash `4d1068acae6a05f9a1e13eb3cca55889407fc3dec4133f2b5ac7265c4568ff92` 与测量时仓库文件一致。adapter 包含只读机器能力声明；其源码 hash 为 `372f7bd3443c574a4233ee9c8ae5ee94ca0779c3da059161d52af55612f80908`，也与本次安装及仓库一致。哈希只绑定这些实际字节，不证明作者身份或第三方二进制安全性。

输入是 [7 行原创行情](../../research/baselines/sprint-03/results/fixture-events.jsonl) 与 [固定 spec](../../research/baselines/sprint-03/results/fixture-spec.json)：初始 bid 100 × 1、99 × 10，ask 103 × 10、104 × 10；内置策略在首个 snapshot 回调后提交买价 100、数量 2 的 post-only limit。随后外部 bid 数量增加，再有主动卖出 2 与 1，产生两次各 1 的部分成交。maker/taker 费率人为设置为 1%/2%，只为可手查，不代表真实市场费率。

十次的 `engine/environment/spec/data` 条件及全部语义 JSON 字节均一致。golden SHA-256 为 `eafd1aadccb8b8853459b0a5cdbe19be4a29cb0dc816ca9fc3383f50a6cd848e`；十次 stderr 均为空。原始时间全部保留，没有删除首条或其他较慢观察：

| run | adapter `duration_ns` | 子进程 `worker_wall_ns` |
| --- | ---: | ---: |
| 1 | 1105101917 | 1206062708 |
| 2 | 506301666 | 584588458 |
| 3 | 499762209 | 577677708 |
| 4 | 502079916 | 580265625 |
| 5 | 515772958 | 598293083 |
| 6 | 512092375 | 594759334 |
| 7 | 504964916 | 583668083 |
| 8 | 503600708 | 581820208 |
| 9 | 508242375 | 586813500 |
| 10 | 507381167 | 586320750 |

[golden-result.json](../../research/baselines/sprint-03/results/golden-result.json) 保存实际 native trace，包括以下可手查结果：

| fill ordinal | 触发输入 capture_seq | qty × price | 本笔费用 USD | 回调内持仓 lots | cash total USD |
| --- | ---: | --- | ---: | ---: | ---: |
| 0 | 3 | 1 × 100 | 1 | 1 | 9999 |
| 1 | 5 | 1 × 100 | 1 | 2 | 9998 |

本例两笔 native 费用与精确十进制 `qty × price × rate` 一致，trace 仍分别保存 native 费用政策、理论值和差额；不能据此声称其他精度与舍入边界均精确。这里是保证金账户，cash total 只按费用下降，不能拿现货扣名义本金的预期去解释它。末状态订单 FILLED、累计持仓 2、cash total 9998、locked 200、free 9798；7 条输入全部处理，open orders 与 pending commands 都为空，`stop_reason=input_exhausted`。这不是一次平仓收益计算。

另外实际执行一次控制变化：只将第 1 行 `receive_time_ns` 增加 **1 ns**。完整 [变化结果](../../research/baselines/sprint-03/results/changed-result.json) 与 [比较报告](../../research/baselines/sprint-03/results/changed-comparison.json) 显示：

- dataset manifest 与 normalized data hash 改变，`strictly_paired=false`，不能当作同条件对照；engine、environment 和 spec 不变。
- 首个输入差异为 `/input_trace/0/fields/native_ts_event_ns`，从 `1700000000000000100` 到 `1700000000000000101`。
- 首个决策差异为 `/decision_trace/0/native_time_ns`，同样增加 1 ns；双方引用均为 `line=1, capture_seq=1, event_type=snapshot`。

这证明该 fixture 的变化可以从实际 native 输出定位回稳定输入引用，不证明时间映射是真实 UTC，也不把不同数据运行包装成严格 paired。

## 5. 复跑与尚未测量的范围

先按项目锁定的 optional native 环境安装依赖与新构建 wheel，再使用该环境的解释器执行；本次用了独立 `/private/tmp/tickwitness-s03-benchmark`，未向 core 环境安装引擎。以下命令里的环境路径是本机操作示例，不是可移植支持矩阵：

```sh
/private/tmp/tickwitness-s03-benchmark/bin/python -I scripts/benchmark_replay.py --output-dir research/baselines/sprint-03/results
```

脚本只在全部 10+1 次检查通过后写入输出；重跑会覆盖所选输出目录内的同名基线文件，保留历史时应选择新的目录。wall time 与测量时间不要求逐字节重现；应核对实际条件、模块哈希与语义结果。新的平台、依赖或适配器版本可能有差异，应保留条件差异而不是忽略它们。

[质量策略](../quality/quality-strategy.md) 中百万事件、两策略、十场景和包装开销等仍是后续测量目标，本次 7 行单买单没有完成这些目标。没有跨平台认证、真实市场成交校准、checkpoint、精确前撤/后撤见证、任意策略执行或性能承诺。
