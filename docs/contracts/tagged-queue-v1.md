# Tagged Queue v1：守恒的条件队列重建

本合同对应 S06-02b，承接 [S06-02a 资格结论](queue-semantics-qualification-v1.md)。它为已显示流动性中的一个假定参与者冻结独立命题、观测投影、干预和共同预算。工程实现与远端验收状态见 [Sprint 6](../planning/sprint-06-status.md)；本文的手算 oracle 是验收要求，不能代替实际运行记录。

## 研究对象与观测范围

输入限于受支持的单流 EUR-USD public L2 snapshot／delta 和目标 bid 的 sell trades。初始公开量已经包含标记订单。干预 `relabel_existing_tail_quantity_v1` 把现有队尾的 `q` lots 标记为假定己方订单；总量不增加。它描述有限观测路径下的条件重建，没有验证真实历史所有权、实际新插单或市场冲击。

投影 `inclusive_tagged_fifo_total_depth_v1` 为：

```text
A = external ahead
R = tagged live remaining
B = external behind
Q_public = A + R + B
entry: A = Q0 - q, R = q, B = 0, requiring 0 < q <= Q0
```

模拟产生的 private fills 不属于 public observation projection；horizon 后的行政撤单也不属于该投影。当前输入格式没有读取或验证真实 private execution observations。若以后取得此类证据，必须扩展合同并检查其约束，不能声称本轮已经排除了这些矛盾。

这与 [旧影子队列族](queue-family-v1.md) 的 external tape 模型有不同研究对象。旧结果保持原身份和语义；新模型不改名接收旧结果，也不为旧 source claim 补签真值。

## 请求、独立命题与身份

`freeze-tagged-queue SOURCE_PROTOCOL TAGGED_REQUEST GROSS_REQUEST` 读取实际已接受 development 数据、完整 `ExecutableProtocol v2` 和两份 JSON 请求。新请求 exact fields：

```json
{
  "kind": "tagged_queue_request_v1",
  "schema_version": 1,
  "claim": {
    "title": "Conditional tagged net inventory mark",
    "hypothesis": "The tagged participant has a positive net inventory mark.",
    "metric": "tagged_inventory_net_marked_pnl_v1",
    "unit": "USD",
    "comparator": "gt",
    "threshold": "0"
  },
  "budget": {"max_attempts": 2, "max_wall_seconds": 60, "max_events": 1000}
}
```

命题 title／hypothesis 分别最多 200／2000 字符，无空白包围或控制字符；comparator 为 `gt/ge/lt/le`，threshold 为规范化十进制字符串。metric 与 USD 单位固定。`claim_revision_id` 是这份规范化**新命题**的 SHA-256；source claim 仅保留来源关系。

gross 请求沿用 [Queue Constraints v1](queue-constraints-v1.md) 的来源绑定、目标价位及逐 checkpoint gross declarations。完整旧约束以 `gross_constraint_source` 嵌入，角色固定为 `source_and_gross_flow_lineage_only_v1`。旧约束中的 shadow impact、模型分类和 `execution_approved=false` 不是新模型的授权或兼容性结论。gross additions／cancellations 仍属研究者声明、未校准且校准引用为空，不能从净深度推断成观测事实。

`tagged_queue_reconstruction_protocol_v1` 固定完整 source／gross 声明、实际 dataset／normalized SHA／ReplaySpec／gross constraint 身份、新命题及 revision、政策顺序、模型、策略、估值政策、scope 和共同预算。协议 ID 是完整 canonical JSON 的 SHA-256。数据、gross 分解、命题、预算或任何合同字段改变都得到新身份；canonical loader 重建固定字段，不能用重新计算 hash 绕过语义校验。

Engine 固定 Nautilus Trader `1.231.0`，新 semantic 为 `nautilus_tagged_fifo_reconstruction_v1`；模型为 `protected_tagged_fifo_reconstruction_v1`，策略为 `tagged_passive_order_at_entry_v1`。entry 为 capture 1，horizon 为实际源最后一条 target bid checkpoint，数量／价格／增量／资金／费率取完整 source ReplaySpec。原生 insert／cancel latency 均为零，source `cancel_after_first_fill=false`。模型不是样例中 100 ticks／2 lots／capture 6 的硬编码。

请求、协议、intent 和结果均拒绝未知／重复字段、浮点 JSON、非有限数字、bool 冒充整数以及超限输入。预算为共同 `max_attempts=2..100`、每调用 wall `1..60` 秒、events 不超过 source 预算且最多 1000。冻结阶段从实际源验证两种解释均可行；不启动 native、不占 attempt。

## 单次分配与保护订单

新增先追加到 `B`，然后按显式政策分配外部撤单：

| 政策 | 外部撤单优先级 |
| --- | --- |
| `protected_tag_front_cancel_v1` | A，再 B |
| `protected_tag_back_cancel_v1` | B，再 A |

撤单跳过保护中的 `R`，每次要求 `cancellations <= A+B`。即使旧总量算术可行，只要任一解释需要撤掉保护订单，整份新协议都拒绝冻结，不能挑选留下可行的一侧。

每笔 sell trade 按 `A → R → B` 恰好消耗一次：

```text
external_trade_ahead + own_trade + external_trade_behind = recorded_trade_lots
external_consumed + own_fill = recorded_trade_lots
Q_after = Q_before + additions - cancellations - recorded_trade_lots
R + own_filled = original_tagged_quantity
```

成交不可用未来 checkpoint 新增量补足。trade 后的绝对 target depth 负责对账，不再把已计 trade 当作 cancellation。每个 checkpoint 都要求 `A+R+B` 等于同一份源记录的 `Q`。输入引用必须完整、唯一、顺序一致；同接收时刻保留 capture 顺序。非目标 book 更新保留在 trace，队列 flow 为零。

## 原生表示、horizon 与清理

原生接受用于表示该假定已在簿参与者，`acceptance_role=tagged_reconstruction_proxy`。真实 `OrderAccepted` 必须发生在首 capture，并从原生目标价位检查公开总量；该回执不是订单历史真实到达时点的证据。

每个 capture 的公开 FillModel 只授予守恒模型中 `own_trade_lots` 的容量。空 book 表示不授予，禁止以 None 回退旧撮合；重复 hook 共用已授数量，不能重新领取。同一确定性 profile 要求实际 grant 与实际 native fill 都精确等于该单次分配。实际订单回调、费用与账户由原生引擎产生，独立审计重算 source／allocation／lifecycle／账务并逐项核对。

终止政策 `observe_mark_then_cancel_after_horizon_v1` 固定逻辑顺序：

1. `observed_window`：消费原始 source 至最后 checkpoint H。
2. `claim_horizon`：在清理前保存重建队列、实际 native target quantity 和账户；mark 取实际最终可见 best bid。
3. `post_horizon_cleanup`：若仍有 R，使用同一原生时刻明确取消，并要求真实终态回执。完全成交无需撤单。

不补行情、不推进时钟、不加 EOF guard 来完成回执。horizon 后不得有成交。清理记录 `canceled_own_lots=R`、`projected_total_after_cleanup=Q-R`、`projected_external_after_cleanup=A+B` 和 `own_live_after_cleanup=0`；清理不改写已存 horizon trace。

原生缓存书簿标注 `book_role=recorded_observation_cache`，仍是原始观测缓存，不宣称它在行政撤单后变成物理总簿。原生 CANCELED 订单的 `native_unfilled_lots` 可以仍是 `q-filled`；它表示未成交量，不代表撤单后仍然存活的 own quantity。缺接受／缺取消回执、未决命令、EOF 开放状态或任一守恒／账务不匹配均不能发布 verified 收益。

## 估值与手算验收要求

新估值政策 `tagged_inventory_final_visible_bid_flat_zero_v1` 仅评价该 tagged inventory：

```text
net_marked_pnl = filled_lots * size_increment * (final_best_bid - fill_price) - actual_fees
```

最终 best bid 从完整实际源重建，不能回退到目标价位或沿用已删除价格。无成交而完整终止的库存净值明确定义为零。mark 是条件库存估值，不声称按显示量实际清算或保证可退出。margin cash 为 starting cash 减实际费用，不按 spot notional 扣款。费用仍按 pinned native binary64／USD Money 量化审计；存在支持模式间费用歧义时估值和命题真值为 null，保留原因。

下表是运行前独立预设的标准 oracle；实际验收记录见 [Sprint 6](../planning/sprint-06-status.md#s06-02b-远端验收记录)。初始 Q5／q2，新增3、撤3、trade3，两侧最终 Q2；价格100、增量1、maker fee1%。

| 项目 | front | back |
| --- | --- | --- |
| trade 前 A/R/B | 0/2/3 | 3/2/0 |
| trade 的 external/own 分配 | 1/2 | 3/0 |
| horizon A/R/B | 0/0/2 | 0/2/0 |
| 原生成交／费用要求 | 2 lots / 2 USD | 0 lots / 0 USD |
| 最终 bid100 的 net / gt0 | −2 / false | 0 / false |
| 最终 bid102 的 net / gt0 | +2 / true | 0 / false |
| 最终 bid102 的 net / ge0 | +2 / true | 0 / true |

该 2/0 oracle 与旧 ghost 的 1/0 不同，原因是研究对象与单次 trade 分配合同改变；旧结果不能重标为新模型通过。双模型同真值只说明这两个解释的结果，不能证明所有模型都识别；异真值也不自动签发 `NOT_IDENTIFIABLE_WITHIN_MODEL`。

## 持久执行、只读复核和 CLI

新 POSIX 注册表使用统一 `--registry` root 下独立 `tagged-queue-protocols` namespace，source v2 的 namespace 不变。数据仍用 `--store`，attempt／intent／outcome／CAS 工件仍用共同 `--ledger` root。所有执行只允许 development，confirmation 在请求文件、ID 和 repository factories 前拒绝。只读缺失根不创建目录。

| 命令 | 输入及行为 |
| --- | --- |
| `freeze-tagged-queue SOURCE_PROTOCOL TAGGED_REQUEST GROSS_REQUEST` | 另需 `--input-root --store --registry`；验证实际源、两种分配后冻结新合同，JSON 返回 protocol_id |
| `run-tagged-queue-pair PROTOCOL` | 另需 `--store --registry --ledger`；按冻结顺序各运行一次，每调用占一个共同槽 |
| `run-tagged-queue-model PROTOCOL POLICY` | 同上；显式运行某政策，仍消耗同一协议预算 |
| `inspect-tagged-queue PROTOCOL` | 同上；只读检查来源、已提交 attempt 前缀和剩余共同预算 |
| `inspect-tagged-queue-run RUN_ID` | 同上；RUN_ID 是 committed receipt digest，重新审计闭包，不调用 native |

运行可显式提供 `--engine-python`；其余安全输入与受监督 worker 边界延续既有设计。完整工作流从已经导入的 public 观测和已冻结 source v2 开始，示例新请求见 [tagged-queue-request.json](../../examples/tagged-queue-request.json)。

每次调用依次验证实际源、reserve、持久绑定不可替换完整 intent 及输入工件、构造 worker、执行、持久保存原始结果、独立审计并发布 outcome。独立 kinds 为 `tagged_queue_attempt_reservation_v1`、`tagged_queue_run_intent_v1`、`tagged_queue_run_receipt_v1` 和 `tagged_queue_attempt_failure_v1`。attempt 不因失败、超时或中断退款；未决 reservation 保留为已消费。共享末槽用 POSIX 锁和无覆盖发布保护。

双调用首次失败即停止，返回 partial／failed、已完成 run 与未尝试政策，CLI 非零退出；不删除第一份成功。取得但审计失败的有界原生结果作为诊断工件保留，不成为 verified 结果。共同预算仅约束该协议；它不是跨协议完整试验历史，也不证明多重检验已校正。

reserve 的持久化确认失败时，槽可能已经提交。调用停止并返回 `tagged_queue_reservation_unconfirmed`、`budget_consumed=null`；不能因缺少 attempt ID 就声称未占预算或自动退款。先用 `inspect-tagged-queue` 检查已提交前缀；后续显式重试仍受原共同预算约束。明确预算耗尽且本次未占新槽才报告 false。

`tagged_queue_replay_result_v1`、`tagged_queue_replay_evaluation_v1` 绑定新协议／命题／policy／实际源。只读 inspect 检查 committed reservation／intent／receipt／CAS 和注册表，重读实际 development 输入并重算评价，返回 `native_replayed=false`。hash 闭包不认证作者，不证明完整历史或真实交易所 ownership。

每份 submission 保留实际 `execution_environment`。两份已完成运行只有在该环境的 canonical JSON 相同、估值均 eligible 时才报告同真值／异真值关系；环境不一致返回 ineligible 及 `execution_environment_mismatch`，仍保留两份独立运行的审计结果。环境字符串不是第三方认证。

单次 run 的 findings 始终为空；旧 baseline bundle、S05 比较器和旧 queue qualification 继续拒绝新 kind／semantic。独立封存与 core 离线复核见 [Tagged Pair Evidence v1](tagged-pair-evidence-v1.md)，另行冻结的条件报告权限见 [Tagged Findings v1](tagged-findings-v1.md)，不会回写本协议。确认集 lifecycle、独立人类领域复核与真实用户采用证据仍是后续验收门。
