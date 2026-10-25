# Scenario Execution v1：耦合接收时钟的派生回放

本文件描述 S05-02 的受限执行契约。Phase A 已取得远端时钟资格证据；生产执行、持久化和 CLI 的 Phase B 全量回归仍待验收，不能将本文件视为已经发布的执行支持承诺。[S05-01 声明契约](assumption-scenario-v1.md)的 `execution_approved=false` 保持原义：声明合法、来源绑定和输入约束成立，不等于批准执行。

首个 profile 仅为 `COUNTERFACTUAL_STRESS`、`researcher_defined / uncalibrated` 的 `replay_receive_suffix_shift_v1`。执行 clock profile 为 **`coupled_receive_suffix_clock_v1`**，原始 [ReplaySpec](replay-v1.md) 仍使用 `receive_order_v1`，adapter 仍固定 `nautilus-trader==1.231.0 / nautilus_v1_receive_order_single_limit_buy_v1`。它不是独立 venue clock 加延迟 observer 的 feed 模型，也不是历史网络延迟或真实 UTC 的重建。

## 1. 时间与事件顺序

从 `from_capture_seq` 对应记录开始，整个后缀的 `receive_time_ns` 增加声明的非负常数。前缀字节不变；后缀只替换规范 JSONL 中对应接收时间的数字 token。零延迟保留全部源行情字节。没有排序、夹紧时间、丢消息、修改 event time、变更价格数量、补齐未知时间或改写原始文件。

源与派生输入都必须通过完整 preflight：单 EUR-USD 流、有效初始快照、连续更新、已知且非递减的接收时间、`event_time_ns <= receive_time_ns`、非锁盘/交叉盘口、支持的数量单位与 frozen event budget。声明最大值和具体候选都检查接收时间加 insert/cancel latency horizon 不超出 int64。额外延迟范围上限是软件支持范围，不是物理或实测边界。

现有 adapter 的 native 映射为：

```text
native ts_event = native ts_init = 当前输入 receive_time_ns
```

原始 event time 只作为来源字段保留。因此增加接收时间会同时改变该输入进入模拟交易所和策略回调的时刻。固定 native 的主要处理顺序是：推进当前模拟时钟 → 交易所处理本条行情/撮合 → data engine 更新与策略行情回调 → 对当前 step 结算到期交易命令。内置策略不注册额外 timer；venue 的命令队列延迟本身不保证插入独立的连续时间到达事件。

由此，下一条输入到来时已经到期的 cancel，可能仍在该条行情撮合之后才收到处理。也可能由较早到来的 benign book step 先结算 cancel，随后 trade 不再成交。这是声明模型的顺序，不应解释成真实交易所必然如此处理网络延迟。

同 native 时间的输入保持原 capture 顺序。公开 `SimulationModule.pre_process` 在撮合前绑定输入，避免 fill callback 早于策略 trade callback 时错误引用上一条行情。`source_ref` 表示使该 native 处理/结算 step 发生的源记录；命令的原始 issuing decision 另有引用。它不是成交唯一经济原因的证明。

EOF 不追加市场 guard，也不凭名义到期时间向未来排空：未收讫 submit/cancel 保留 `pending_commands_at_data_end`；仅有开放挂单则为 `input_exhausted_with_open_orders`。订单 FILLED 不能收讫一条仍在途的 cancel。`completed`、账务可估值与研究命题真假是不同维度。

## 2. Phase A 资格矩阵

资格脚本为 [qualify_scenario_clocks.py](../../scripts/qualify_scenario_clocks.py)，真实 native 测试为 [test_scenario_clock_native.py](../../tests/integration/test_scenario_clock_native.py)。输入是本仓库原创 `examples/clock-*`；脚本不执行用户策略、不连接交易所、不占用用户 attempt，也不发布 production derived-view。

| case | 预先声明的验证目标 |
| --- | --- |
| `zero_delay` | 相同输入身份下，零变换得到完整同语义结果；无隐藏时间或数据改写 |
| `full_stream_translation` | 全流统一平移 native 时间，明确经济/callback projection 保持一致 |
| `suffix_without_command_latency` | 后缀非零变换在无命令延迟的固定 fixture 中保留业务数量与费用 |
| `insert_step_control` | 无成交控制下，insert 收讫发生在实际 market step；不假设名义到期时刻自主执行 |
| `cancel_same_time_step_counterexample` | 下一条 trade 与已经到期的 cancel 的处理顺序可从实际 source ref 与 callback 定位 |
| `cancel_business_difference` | benign book step 结算 cancel 可产生真实数量/费用差异，双方仍须独立账务审计 |
| `same_time_capture_order` | 同刻两笔 trade 的 capture 引用保持区分，不从最近策略回调倒推 fill 来源 |
| `eof_pending_submit` | 不伪造未来输入；末尾仍在途的 submit 诚实保留 incomplete |
| `eof_filled_pending_cancel` | FILLED 但 cancel 未收讫仍 incomplete；后来实际输入可改变结算完整性 |

全流平移的 projection 明确移除 native 时间/成交生成 ID，并按 submit decision 将订单 ID 映射为固定序号；原始结果、真实 ID 与原始时间完整保留在报告中。它不是把不同 data hash 的结果称为全字节相等或现有 comparison 的 `strictly_paired=true`。

Phase A 的 [远端 run 40220550602](https://github.com/Darrenus/tickwitness/actions/runs/40220550602) 在 Ubuntu 24.04 与 macOS 26、Python 3.12 的固定 native profile 分别生成报告。资格 head 为 `c1edcf5d772cae78702e33cd2c1d62d2b8622d14`，job 实际 merge checkout 为 `2b78eb75d843f9128bf91ce72868f4bc4a784a10`，不能把两者混用。两份报告均记录 `coupled_model_qualified=true`，同时明确 `independent_venue_observer_model=unsupported`、`scenario_execution_enabled=false`。这限定于所列 fixture 与各自记录的环境，不是任意场景、所有引擎平台或跨平台逐位确定性证明。

报告中的 `cancel_business_difference` 实际记录：baseline 两次成交、实际费用合计 2 USD、净 mark 估值 −2 USD；后缀压力一次成交、实际费用 1 USD、净 mark 估值 −1 USD，双方 completed 且可估值。这是可复核的数量/费用变化，双方都没有因此获得 baseline claim 的 `satisfied`，也不是声明翻转或利润策略证据。额外延迟不必单调降低某个数值。

报告还记录了到期 cancel 在下一条 trade step 后结算的案例。该观察支持当前 step-coupled 模型的边界，不能升级为“venue 已在名义到期时取消”的独立时钟结论。资格报告没有性能吞吐、真实市场校准或生产执行工作流通过声明。

## 3. 原始证据与派生身份

[derivation.py](../../src/tickwitness/domain/assumptions/derivation.py) 的 `derive_replay_view(validated) -> DerivedReplayView` 在内存中重建每个冻结值，并再次校验实际原始 development 绑定及输入约束。它不信任旧 DTO 的 true marker，也不接受调用方直接提交 transformed bytes 或自报派生 hash。

`DerivedReplayView` 包含 `validated`、`canonical_bytes`、`view_id`、`replay_input` 和每次返回新副本的 `document`。`load_derived_replay_view(raw, *, validated)` 从原始来源重新派生，要求描述符全部规范字节相等。描述符固定字段为：

| 字段 | 内容 |
| --- | --- |
| `kind / schema_version` | `derived_replay_view_v1 / 1` |
| `clock_profile_id` | `coupled_receive_suffix_clock_v1` |
| `identity_semantics` | `derived_view_not_catalog_manifest_v1` |
| `scenario_kind / calibration_status` | `COUNTERFACTUAL_STRESS / uncalibrated` |
| `source_bindings` | 原 protocol、development dataset、原规范数据 hash、ReplaySpec ID |
| `assumption_id / scenario_id` | 已冻结声明与具体候选的内容身份 |
| `transform / additional_delay` | 固定后缀语义、capture anchor、具体非负 ns 值 |
| `derived` | `normalized_sha256` 与不变的 `record_count` |
| `execution_approved` | 始终 `false`，不是一份执行授权 |

`view_id = SHA256(canonical_bytes)`。场景 `ReplayInput.dataset_id` 使用这个独立 view ID，不能把变换后的 bytes 冠以原 development manifest ID。它也没有被发布为 `LocalDatasetStore` 的新观测数据：descriptor 明示它是 derived view，不是 catalog manifest。

零延迟时，derived normalized bytes/hash 与源一致，但 view ID 仍绑定场景身份且不得与原 dataset ID 别名。非零延迟时，只允许声明后缀的接收时间变化。逐条 DTO 比较再次证明对应关系；capture、line、market payload 与源事件引用保留。旧 dataset、v2 protocol、baseline receipt 和已导出的证据包均不被改写。

## 4. 持久化执行意图与共享预算

[scenario_records.py](../../src/tickwitness/domain/evidence/scenario_records.py) 引入独立的 `scenario_execution_intent_v1`。它包含原 protocol/claim revision、固定场景 scope、clock profile，以及以下绑定：

```text
development_dataset_id
source_normalized_sha256
replay_spec_id
assumption_id
scenario_id
derived_view_id
derived_normalized_sha256
```

intent ID 是其完整规范字节的 SHA-256，不接受只有一个任意场景标签的记录。`run_scenario` 先完成来源、请求、派生 view 与 event budget 校验，然后向**原始 ExecutableProtocol** 的 ledger 预留 slot。baseline 和所有场景共用该协议冻结的 `max_attempts`，不能按 scenario 派生新的免费预算。wall limit 沿用冻结值，由现有受监督 worker 执行；不另提供 CLI 参数放宽它。

成功预留后，先持久化 assumption、scenario、view descriptor、derived tape 的 CAS 与 intent，再构造 engine。`LocalAttemptLedger.bind_intent` 将 intent 与确切 reservation 绑定，并在独立 `intents` namespace 提交；它不是替 S05-01 把 `execution_approved` 改为 true。目录/对象提交失败时，不能启动 native 来补做，也不能退款已经占用的 slot。

只有 intent 精确匹配，才可为该 slot 发布 `scenario_run_receipt_v1` 或 `scenario_attempt_failure_v1`。intent-bound slot 不能改发旧 baseline outcome；已终结的 baseline slot 不能再绑定新的场景 intent。新的读取路径不为旧 ledger 自动创建 intent namespace。

运行错误、native 不可用、超时或审计拒绝都会消费已预留预算。发生提交不确定性时，可能只留下 reserved/unfinalized 状态；以 `attempt_outcome_unconfirmed` 明示，不能伪造失败终态或重新分配该 slot。重复执行请求是新 attempt，不因内容相同而免除预算。

## 5. 场景评价与回执

`ScenarioEvaluation(view, result)` 要求 engine 条件与原 frozen protocol 相等，对 `view.replay_input` 调用现有 [精确账务/费用/mark 审计](evaluation-v1.md)。它不会放宽原始输入或账务检查，也不会把 derived hash 与源 hash 混用。

评价 kind 为 `scenario_evaluation_v1`，绑定 protocol、claim revision 与 intent ID，包含 `metric_observation` 和完整 `replay_evaluation`。`metric_observation` 只给 `net_marked_pnl_v1 / USD` 的 `eligible` 与 `value`；**没有 baseline 的 `satisfied` 或阈值比较**。incomplete、无 fill 或费用模型不唯一时保留不可估值状态，不生成已知收益值。

scope 固定为：

```json
{
  "phase": "development",
  "scenario_kind": "COUNTERFACTUAL_STRESS",
  "calibration_status": "uncalibrated",
  "search_performed": false,
  "baseline_claim_evaluated": false
}
```

`scenario_run_receipt_v1` 嵌入完整 reservation 与 intent，绑定实际 replay result SHA-256 和 scenario evaluation SHA-256，只接受已审计的 completed / incomplete。失败使用独立 failure kind。旧 `research_run_receipt_v1`、`ProtocolEvaluation` 的 `baseline_v1` scope 与 [8-role portable bundle v1](evidence-bundle-v1.md) 保持严格原格式，不接受场景字段混入。

## 6. 应用/CLI 与重验边界

当前工作树中相应入口为：

- `validate-scenario`：只检查请求和输入约束，仍不使用 attempt 或 native。
- `run-scenario`：通过预检后预留原协议预算、持久化 intent，再调用现有 worker；confirmation 在请求文件和 repository 访问前拒绝。
- `inspect-scenario-attempt`：读取 reservation、是否存在 durable intent、可确认的 outcome；没有 outcome 不表示预算退款。
- `inspect-scenario-run`：先核 reservation/outcome/intent 提交闭包，读原协议 development 数据，重新派生 descriptor/tape、重建 intent 和评价，并比较全部存储字节。

实现位置为 [scenario_execution.py](../../src/tickwitness/application/scenario_execution.py) 与 [cli_scenarios.py](../../src/tickwitness/cli_scenarios.py)。inspect 不导入/调用 native engine，不把存储的 evaluation hash 当作无需复算的事实。它仍需原 source store、registry 与 run ledger，**不是可脱离这些目录独立迁移的 scenario bundle verifier**。

inspect 的验证标记包括 `derivation_recomputed=true` 和独立 accounting；同时保留 `native_replayed=false`、`confirmation_reference_checked=false`、`full_attempt_ledger_checked=false`、`author_signature_verified=false`。它不认证作者、真实市场来源或全部尝试历史。scenario portable bundle、成对差异报告与搜索 finding 留在后续故事；现有 baseline exporter 不被改造成不完整的场景导出器。

## 7. 独立 venue clock + delayed observer 仍需新模型

要实现独立观察延迟，需要让 venue book 在声明的 venue 时间线推进，同时仅在 availability time 将市场数据送达策略自己的 book/cache。下单到达、取消到达、venue fill、响应送达要成为有明确同刻优先级的调度事件；不能通过增加假行情消息来推进命令。

策略不能提前读取已经更新的 venue cache，`cancel_after_first_fill` 也应在策略收到 fill 响应后触发。trace 必须分别表示 venue 事件来源、触发决策/命令与 observer delivery，不能把独立 timer 的回调绑定到“最近 market input”。EOF、有限 drain horizon、账务与各 clock 的 source binding 都需要新的可核验契约。

仅把 native `ts_event` 改成源 event time 而保留 `ts_init=receive_time` 不足以建立此模型：现有 outer loop 仍在输入的 `ts_init` step 同时处理 exchange 与 data engine。新模型必须有独立的 clock/adapter semantic、冻结条件及资格测试；公开源 event time 也不能自动视为已校准真实 venue clock。当前 profile 不批准这条能力，也不产生观测相容世界、队列可辨识证书、声明翻转或搜索覆盖结论。
