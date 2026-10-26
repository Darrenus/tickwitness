# Queue Family v1 与持久执行

本合同对应 S06-01b。原有 [Queue Constraints v1](queue-constraints-v1.md) 只验证来源和外部流量守恒；此处单独冻结执行权限、模型集合和共同预算。执行分类为 `MODEL_SENSITIVITY`，不签发收益估值、命题真假或观测相容性证明。

## 请求与身份

`freeze-queue-family SOURCE_PROTOCOL FAMILY_REQUEST QUEUE_REQUEST` 读取已接受的 development 数据、现有 `ExecutableProtocol v2` 及两份安全 JSON 请求。族请求 exact fields：

```json
{
  "kind": "queue_family_request_v1",
  "schema_version": 1,
  "cancel_at_capture_seq": 6,
  "budget": {"max_attempts": 2, "max_wall_seconds": 60, "max_events": 1000}
}
```

队列请求沿用 [约束合同](queue-constraints-v1.md)。所有整数拒绝 bool，未知字段和重复字段拒绝。持久的 `queue_family_protocol_v1` 包含完整 source protocol、完整 source-bound constraint、来源数据 ID/normalized hash/spec ID/constraint ID、固定两政策及顺序、策略、engine、研究者明示且未校准的参数依据、scope 和共同预算。身份是完整 canonical JSON 的 SHA-256；不同数据、gross 分解、取消时点、预算或政策都产生不同身份。返回的 document 是 detached 副本。

模型固定为 `cancel_front_first_v1` 与 `cancel_back_first_v1`。Engine 固定 Nautilus Trader `1.231.0`、semantic `nautilus_external_fifo_shadow_queue_execution_v1`；旧 native v1 与资格脚本的 probe semantic 不能代替它。策略 `single_limit_buy_cancel_at_capture_v1` 在 capture 1 提交 post-only 限价买单，在冻结的最终 target bid checkpoint 明确撤销剩余订单。insert/cancel latency 均为零，源策略 `cancel_after_first_fill=false`。最后 checkpoint 必须是实际输入最后一条。数量、价格、增量、资金和费率取冻结 ReplaySpec，未绑定样例的 100 ticks / 2 lots / capture 6 常量。

预算 `max_attempts` 为 2–100，wall 为每次调用 1–60 秒，events 不超过源预算且最多 1000。共同预算归族 ID 所有；source v2 只提供来源和配置，不授权新模型。两个政策没有各自独立协议或预算。变更协议会创建新的声明，不能据此声称已经实现跨协议的统计试验族追踪或多重检验校正。

## 在调用之前占槽

每次 `run-queue-model` 消耗一个族槽。`run-queue-family` 按冻结顺序各调用一次，不隐式复用已有结果；首次失败即停止并列明已完成 run、失败 policy、未尝试 policy、exit code 和是否消耗预算。双调用不是事务：第二次失败保留第一份已提交结果。显式单模型命令用于后续研究，仍需要剩余槽。

序列为验证 development/scope/实际输入、reserve、持久 bind intent 和输入工件、构造受监督 worker、执行、独立审计、提交终态。`queue_attempt_reservation_v1`、`queue_run_intent_v1`、`queue_run_receipt_v1` 和 `queue_attempt_failure_v1` 使用独立 strict kind；intent 嵌入完整族和具体 policy，先于执行不可替换。失败、超时、发布不确定或进程中断均不退槽。尚无终态记录的 reservation 显示为 `reserved_unfinalized`，不能当作未尝试。

本地 POSIX ledger 保留内容寻址、flock、无覆盖发布、fsync、intent/outcome 闭包检查和共同末槽竞态保护。成功 receipt 绑定 reservation、完整 intent、实际结果和独立评价 hash。已获得但未通过审计的有界结果也保存为诊断工件，失败信息给出 hash；它不会成为 verified 成功。未获得 native 结果的启动失败不伪造 trace。

## 原生执行与独立审计

原生 adapter 使用公开 pre-process、FillModel、接受/成交回调；关闭内置 queue gate。每个输入先重建外部队列；显式 gross 增撤单对账，不从净深度猜测。实际接受必须发生在首 capture，读取公开原生书簿的目标价位数量后初始化 ahead；未接受前没有分配额度。

每个 sell trade 的单次总上限独立计算为：

```text
capacity = min(own_remaining_before_input, max(trade_lots - ahead_before_trade, 0))
native_filled_lots <= total_granted_lots <= capacity
```

每 capture 的多次 hook 共用额度，不得重置来重复授予。非 trade 或没有容量时返回空 OrderBook；禁止返回会回退旧撮合的 None。真实引擎决定实际成交、费用、订单状态和账户；输入结束不补 guard、不推进时钟强制结清。

`queue_replay_result_v1` 保存 exact source/input clocks、decision/order/fill/account trace、每输入的 before/after/flow/grant/消费/剩余量及 public hook trace、engine/environment 和结束状态。独立 `queue_source_grant_margin_audit_v1` 不调用 native、也不导入执行层队列算法，而从源约束重新生成政策 trace，核对所有输入、实际接受、FIFO 容量、原生成交与唯一 trade ID、原生回执和现金/仓位前缀。费用按 pinned binary64 与 USD cent 双重量化校验，记录兼容 raw modes 和歧义；margin cash 为 starting cash 减实际费用，不按 spot notional 扣款。

只有完整输入、真实已接受订单、匹配的终态回执、无 open/pending 以及全部队列/费用/账务校验通过才保存 `status=verified` 评价。full fill 不再撤单；否则必须收到冻结最终 capture 的真实 cancel receipt。EOF、拒单、缺回执和校验不一致保存为失败或未决证据，不计为策略盈亏，也不补签 finding。

## 只读复核与权限

`inspect-queue-run` 从 committed receipt/reservation/intent/CAS 闭包、不可变族注册表及实际 development store 重新构造输入、约束和独立评价，精确比较持久评价与结果绑定；返回实际 trace，`native_replayed=false`。`inspect-queue-family` 列出当时可见的 append-only committed slot 前缀、policy、终态或未决状态和剩余共同预算。并发执行时这不是全局原子快照，更不是所有其他协议的完整统计试验账本。

confirmation 在请求文件、错误 ID 和存储工厂前拒绝。读取缺失根不创建目录。旧 v2、baseline/scenario receipts、baseline auditor、bundle 和 S05 比较器继续拒绝新 kind/semantic，不能通过改 engine 标签混用。

S06-02 仍需要独立接受的观测相容性及命题判定合同；`NOT_IDENTIFIABLE_WITHIN_MODEL` 在此合同下关闭。外部 gross 流为明示未校准模型条件，影子成交与真实外部 tape 的无冲击相容性未经证明。
