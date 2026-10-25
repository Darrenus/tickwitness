# S02-02：初始回放引擎的有限选择

日期：2026-10-25（Asia/Singapore）。状态：**选择决定已记录；S3 正式 adapter 尚未实现或验收。** 本文汇总 S1/S2 实验，记录初始集成目标与边界；不自动关闭 S02-02 全部工作，不代替 [ADR-003](../architecture/decisions.md)、Sprint 状态或产品发布 gate。

**选择 NautilusTrader `1.231.0` stable v1，作为 S3 首个单资产 L2 adapter 的目标。** 采用固定 v1 公开的 L2 delta、TradeTick、策略决策 instrumentation、订单/fill 与持仓事件路径。选择理由是所测分时/同刻部分成交能逐笔回调，且每次回调内的持仓、保证金账户现金与费用一致；不要求先维护上游原生补丁。

这个选择不包括任意时间点精确延迟撮合、EOF 自动清空未来在途命令、任意策略审计完整性、完整 checkpoint、真实队列还原或 S6 的精确前撤/后撤相容见证。它是有限集成目标，不是对产品完整可行性、真实市场收益或客户采用的批准。

## 1. 选择所依据的证据

| 证据 | 本机实际观察 | 对选择的作用 |
| --- | --- | --- |
| [HFT S1](hftbacktest-feasibility.md) | 2.4.4 可安装；受控 L2 单次完整成交与手算账务可复现 | 保留为可行候选，未据此认证复杂成交 |
| [Nautilus S1](nautilus-feasibility.md) | 1.231.0 可安装；L1 baseline 和额外订单延迟压力的公开事件、现金可核算 | 证明基础接口与版本路径，不能单独证明 L2 |
| [HFT S2 补测](hftbacktest-selection-gates.md) | 部分成交订单累计执行量 2，而本地持仓只计 1；同刻响应在轮询中合并；终止 current_timestamp 可陈旧 | 当前现成 Python 路径不能满足本项目所需的部分成交账务和逐笔 trace 门槛，暂不选作首个 adapter |
| [Nautilus S2 L2 补测](nautilus-l2-selection-gates.md) | 真正多档 L2 + trades；分时/同刻两次部分成交都有独立回调，回调内 position、cash、fee 一致；取消竞态可解释 | 支持有限 S3 L2/部分成交集成目标 |
| Nautilus S2 EOF 补测 | 最后输入之后仍在途的订单保持 SUBMITTED；有后续数据步才结算命令 | 必须限定延迟与终止语义，不能承诺完整 drain |

两引擎的试验不是同一输入、账户、策略或撮合协议，不能横向比较合成收益、吞吐或“准确率”。选择根据必要契约的已观察行为及维护边界，不按纸面 PnL 排名。

可核验的小型结果：

- [Nautilus L2 比较摘要](../../research/spikes/nautilus/results/l2-selection-comparison.json)：6 个固定案例，两次独立进程语义输出逐字节一致；两份结果 SHA-256 均为 `e710002f27e7fde245297b53767bd2306979d4bf5c58477df2e3d1182e81634c`。
- [Nautilus 运行 A](../../research/spikes/nautilus/results/l2-selection-run-a.json)、[运行 B](../../research/spikes/nautilus/results/l2-selection-run-b.json)：保留输入批次/序列、策略决策、每次 fill、回调内状态及未决命令，含未通过的 EOF 自主推进假设。
- [HFT 比较摘要](../../research/spikes/hftbacktest/results/queue-selection-comparison.json)：20 个固定案例，两次输出相同；部分成交、逐笔日志与终止时钟 gate 不通过。
- [HFT 原始运行 A](../../research/spikes/hftbacktest/results/queue-selection-final-a.json)、[运行 B](../../research/spikes/hftbacktest/results/queue-selection-final-b.json)：保留不符合账务期望的案例，不以末尾补账或删例改变结果。

两次同机重复不是跨平台确定性认证，也不是独立人类领域审阅。HFT 旧 S1 关于“尾部 guard 未本地消费”的推断，已被 S2 receipt 字段更正为“可能已处理但公开时钟陈旧”；旧原始记录继续保留，不能重复沿用旧解释。

## 2. 有限 Go 的具体含义

| 范围 | S3 目标契约 | 当前实现状态 |
| --- | --- | --- |
| 引擎版本 | 精确固定 `nautilus-trader==1.231.0`，stable v1；adapter 绑定语义版本和依赖快照 | spike 已运行；正式依赖/adapter 尚未集成 |
| 数据 | 单资产、有效 L2 快照与增量、明确 aggressor 的 TradeTick；输入身份、顺序和精度受控 | 原创合成 fixture 已验证；通用数据映射待实现 |
| 撮合配置 | 显式 `L2_MBP`、`trade_execution=True`、`queue_position=True`、`liquidity_consumption=True`；模型与费用写进协议 | 对所测组合有证据；其他组合不自动受支持 |
| 策略与 trace | 可信本地策略的显式决策记录；公开订单/fill/position 回调；相同时间事件保留顺序和独立成交 ID | probe 能取到；持久化、错误映射和证据契约待实现 |
| 账户 | 首先围绕已测单资产、USD 保证金账户、固定精度与费用模型，分别报告现金、保证金和持仓 | 合成案例内逐笔一致；其他账户/资产规则另立验收 |
| 执行时间 | 接受固定 v1 的数据步驱动结算语义；零延迟或有明示限制的延迟配置 | 已观察，正式能力声明待实现 |
| 终止 | 区分数据耗尽、引擎返回和命令完成；保留最终状态与未完成范围 | probe 可识别 SUBMITTED；应用层 completeness/拒绝策略待实现 |

初始支持矩阵只能承认本机已测的 CPython 3.12.14 / macOS arm64 组合。官方其他 wheel 的存在不等于产品支持认证；Linux、其他 Python/OS 和 CI 环境应在相同 adapter 契约通过后逐项加入。[既有发行元数据](../../research/spikes/nautilus/results/pypi-1.231.0-metadata.json)。

这次选择只确定后续工程要实现哪一个 adapter。没有正式 `ReplayPort` 集成、运行能力检查、结果映射及端到端验收前，README、CLI 或 API 不得宣称 Nautilus 已作为可用产品功能提供。

## 3. 时间、延迟与 EOF 的硬边界

**不支持“填一个纳秒延迟参数，就能在任意独立时刻精确撮合”的假设。** S1 的 1.5 s insert latency 在后续行情 step 处理；S2 的命令在 +3 s 提交、名义到达 +5 s，而有 +6 s 数据时才在 +6 s 结算。不能将其描述为自动在 +5 s 当时盘口执行。

S3 必须把数据到达顺序、相同时间戳 tie-break、市场先处理/策略后观察、命令结算时点和费用规则放进冻结协议及执行语义版本。需要独立连续时间调度的研究问题，先返回 unsupported 或进入专项验证；不能静默换成近似时间还沿用原声明。

**不支持默认 EOF 自动 drain 未来命令。** 无 +3 s 之后数据的 probe 中，订单仍 SUBMITTED，probe 明确标为 `INCOMPLETE_AT_DATA_END`。引擎正常返回不等于所有在途 insert/update/cancel 已处理，也不等于一次研究评价完整。

适配层必须检查未决命令及协议定义的结束条件；未完成范围映射到执行状态与 `completeness`，不能生成无范围限定的 `NO_COUNTEREXAMPLE_FOUND`。已接纳但继续挂单是否满足某个截止协议，由该协议明示；不能把它与尚未到达的命令混为一个“完成”状态。

禁止为强迫结算而给生产历史数据追加虚构行情 guard。日后若要用 timer、显式 end 或其他 drain 方案，必须另立受支持的能力、测试在途命令/定时器/订单状态，并验证时点语义，不能从 API 存在推断其已正确实现。

## 4. S6 与其他未通过项

| 能力 | 当前 gate | 再开放前所需证据 |
| --- | --- | --- |
| 精确 Q-front / Q-back 观测相容解释 | **CLOSED / 未通过** | 同一 L2 观测与明确撤单分配约束；逐步队列 trace；两个可行解释独立重放并使同一命题真假相反 |
| 从 L2 知道真实队列或真实自身 fill | 不支持 | 不能由聚合观测推出；任何模型范围与现实验证分开报告 |
| 无条件任意策略/订单路径的无损审计 | 未验证 | 多订单、多价格、修改、拒绝、重复、同刻事件与错误路径契约矩阵 |
| 任意时间精确 latency / EOF 自动 drain | 不支持为默认承诺 | 独立的调度/结束语义验证及能力版本 |
| 跨进程完整 checkpoint / resume | 未验证 | 包含 book、订单、队列、inflight、时钟、策略和随机源的恢复等价性；当前从冻结输入重放 |
| 隔离执行任意恶意代码 | 未通过安全 gate | 保持可信本地代码范围，独立安全验证后才能扩大 |
| 性能、真实市场准确性与用户采用 | 本轮无此证据 | S3 后同语义基线、合法真实数据、独立复现与实际用户任务分别验收 |

尤其不能把 `queue_position=True` 当成 S6 已完成：本次只验证一种内置队列规则的有限运行路径。两种配置名称不同、损益不同或模型参数导致翻转，都不足以签发 `NOT_IDENTIFIABLE_WITHIN_MODEL`。平台的声明/协议/反例验证边界继续按 [领域模型](../architecture/domain-model.md) 执行。

## 5. 可选依赖与许可证边界

项目原创代码继续采用 **Apache-2.0**。NautilusTrader 的上游包及其源码/二进制继续保留 **LGPL-3.0-or-later**；本选择没有重新许可它，也没有因为它是 optional 就免除相应分发义务。[上游固定版本 LICENSE](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/LICENSE)。

集成决定是：

1. 将引擎放在 infrastructure adapter 与可选依赖 extra 边界内，建议 extra 名称为 `nautilus`；精确版本与锁定策略在 S3 集成时落地。
2. 核心领域、Catalog/CAS、协议与证据测试不要求安装该 native 包；domain 不导入 Nautilus 类型。可信 coordinator 与引擎 worker 经端口/DTO 交互。
3. 独立执行环境保存引擎和依赖版本，避免把两个候选的依赖树强行合入核心；不在仓库提交 wheel、第三方源码或 binary。
4. 对 wheel/容器再分发、上游修改、notice、来源与对应许可义务建立发行检查；需要扩大分发方式时单独复核，不能用项目 LICENSE 覆盖依赖许可。

**当前 extra 尚未添加，正式 adapter 也未实现。** 以上是实施边界，不是已经可用的安装命令。不得为完成本决策而悄悄加入核心必需依赖，或自动切换到 v2 `latest` / RC 版本。

## 6. S3 落地与重新决策条件

S3 的首个验收应从既有合成 L2/partial/race/EOF 夹具移植出可维护契约：固定支持类型与精度，明确 input/decision/order/fill 的引用，逐笔核算 position/cash/fee，保留同刻顺序，并使 EOF 未决命令明确 incomplete。然后完成领域端口、能力协商、结构化错误和离线证据导出，不将研究脚本直接改名为正式 adapter。

出现以下任一情况应重开选型或收缩能力，而不是扩大宣传范围：

- 必须修改私有 native 结构才能稳定记录所需事件，且维护成本超过约定预算。
- 已测部分成交/账务契约在支持环境中失败，或无法定义可审计的终止完整性。
- 首个必须交付的研究问题依赖精确前/后撤单世界，而公开扩展点不能表达或无法验证。
- 平台 wheel、依赖兼容、许可证分发义务或安全隔离无法由维护者承担。
- v2 或另一引擎的能力成为真实需求；它们必须有新的固定版本验证，不继承 v1 的通过记录。

HftBacktest 仍保留其原始实验和后续候选资格。其部分成交账务、无损 trace hook 与终止时钟若得到固定版本修复并通过相同契约，可另行比较；本轮没有修改它、提交上游报告或以单一案例宣称该项目整体不可用。

本选择为下一阶段提供一个明确、有限且可复核的集成目标；尚未通过的研究、运行、安全和采用 gate 继续按各自证据验收。
