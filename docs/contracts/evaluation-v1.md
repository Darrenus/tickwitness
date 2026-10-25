# Replay Evaluation v1：源绑定、账务审计与观测 bid 估值

本契约已实现于纯领域模块 [evaluation.py](../../src/tickwitness/domain/evidence/evaluation.py)。它接受 [ReplayInput / ReplayResult v1](replay-v1.md)，独立重建源盘口与成交账本，核对 native 轨迹中的金额、持仓和输入引用，然后按 `last_observed_bid_mark_v1` 生成精确估值。它不加载 Nautilus，不运行策略，不执行 FrozenProtocol，不判断研究声明。

适用范围固定为 `EUR-USD`、保证金账户 `MARGIN`、`NETTING`、单个内置 `single_limit_buy_v1` post-only 买限价单。只有做多建仓，没有卖出平仓。本批估值进一步限制为源 trade 触发、成交价恰等于冻结限价的 MAKER fills；其他 book-triggered 填价路径返回不支持该审计 profile 的错误，不能由一次 L2 replay 的正常返回扩大估值支持范围。固定引擎条件为：

```json
{"id":"nautilus-trader","version":"1.231.0","semantic_id":"nautilus_v1_receive_order_single_limit_buy_v1"}
```

`environment.package_versions.nautilus_trader` 也必须是 `1.231.0`。更换版本、订单生命周期或 trace 字段不能继续冒用此审计 profile。

## 领域 API

```python
evaluate_replay(replay_input: ReplayInput, result: ReplayResult) -> ReplayEvaluation
load_replay_evaluation(raw: bytes) -> ReplayEvaluation
```

`ReplayEvaluation` 是冻结值对象，包含 `evaluation_id`、`canonical_bytes`，以及每次返回新副本的 `document`。`evaluation_id` 为规范 UTF-8 JSON 字节的 SHA-256 小写十六进制，不包含自身；最大编码长度为 64 KiB。字段、数字类型与规范编码均严格检查，拒绝浮点 JSON、重复键、未知字段、非有限数值、指数金额文本和不规范估值小数字符串。`true` 与整数 `1` 不相等。

错误统一为 `EvaluationValidationError`。输入仍先执行 native-free replay preflight；不能用一个格式有效的结果绕过源数据 gap、重复、未知时钟、重建后锁盘/交叉盘或不支持资产的限制。

单独调用 `load_replay_evaluation` 只能校验结构、内容哈希、状态组合和估值算术。离线 bundle 验证必须用 bundle 内的规范数据与 spec 构造 `ReplayInput`，加载 `ReplayResult`，再次调用 `evaluate_replay`，并与携带的 evaluation **全部规范字节相等**。重写 manifest、result hash 或 evaluation hash 不能修复与封存源输入或独立账本的矛盾。哈希不是作者签名，也不是 native 撮合真实性证明。

## 审计步骤与不变量

1. 绑定 `dataset_id`、规范数据 SHA-256、`spec_id`、完整结果 SHA-256，以及固定 engine 条件。结果里的 `input_records` 必须等于封存输入记录数。
2. 按封存顺序重建 snapshot + absolute-quantity deltas。逐一比对已处理前缀的 **全部** `input_trace.fields`、`source_ref`、捕获顺序和 receive-order 时钟；包括原始 event/receive 时间、源序列、原始 trade ID、双方盘口、价格/数量单位、内部 capture 映射和政策字段。不是只检查外层数据哈希。
3. 所有决策/订单/成交引用必须指向实际已处理的输入，native clock 必须等于该输入的 `receive_time_ns`，各通道引用不能倒序。输入回放使用合成 `receive_order_v1` 绑定，不能认证交易所时钟或真实 UTC。source reference 指 native 处理/结算步骤所处的输入，不证明该输入是成交唯一经济原因。
4. 严格复核单次 submit 与可选 first-partial-fill cancel 的参数、顺序、命令 ID、订单 ID、提交点和收讫台账。第一条生命周期必须是 `OrderInitialized`，限价成交必须有 `OrderSubmitted` 和 `OrderAccepted` 收讫。`PENDING_CANCEL` 不能凭状态文字出现，必须有实际 pending cancel 与对应事件。订单生命周期、最终 open orders / pending commands、账户缓存中的最终订单必须一致。`OrderFilled` 不能收讫一条尚未收到 `OrderCanceled` / `OrderCancelRejected` 的撤单命令；终态后不能再发生普通订单生命周期事件。
5. 每笔 fill 的 lots 必须为正整数，ticks 必须为正整数，物理数量/价格必须与 spec 增量精确相乘一致。此 profile 的 maker 买价必须**恰等于限价**，不能将任意价格改善当作有效 native 结果；单订单累计数量不能超过请求量。native fill trade ID 不得重复；同一源卖出 trade 触发的成交累计不能超过该公开 trade 的数量。此 post-only profile 仅接受 `MAKER`，不能指向主动买入 trade。
6. 实际 commission 必须为非负 USD、符合 native USD cent 精度，并通过下述固定 native 费用模型的独立复算；费率、精确十进制理论费用和 native 差额字段也必须算术一致。只检查 `actual - theoretical = difference` 不足够；同步篡改 cash、实际费用与 difference 的一分钱操纵同样必须拒绝。不得把精确理论费用覆盖为实际 native 费用。
7. 每笔 fill 必须有对应的订单 callback 与账户 callback。账户 callback 的真实 cache position、累计 fill lots、累计 commission、cached order filled / remaining 必须等于独立成交账本。初始账户为空；最终账户与全量成交账本和最后订单生命周期一致。初始与最终现金、每个 fill callback 都核对 `cash_total = starting_cash - actual_commission_so_far`、`free + locked = total`，locked 不得为负。这里是 MARGIN，不能按现货方式另扣成交名义本金。
8. 核对账户 book 类型与 native 金额政策。最终缓存盘口层数必须与源重建相等。成交 callback 的市场数据 cache 可能在撮合之后才更新，因此允许与该输入处理前或处理后的相邻源盘口层数一致；不据此声称跨通道拥有全局 callback 顺序。

审计拒绝格式内自洽但跨证据矛盾的结果，例如：把 final cash 与 free 一起增加而仍保持 `free+locked=total`；把单位文本与整数 ticks/lots 改成不同金额；修改成交费用而不匹配独立累计；复制 native fill ID；更改 input trace 的价格、原始 trade ID 或序列；在订单 FILLED 后删除未收讫的撤单台账。

`failed` 可以携带已处理输入前缀或空轨迹。已提供的轨迹仍按上述规则核对；没有账户证据的失败不能携带成交。它始终无估值。非 failed 结果要求初始、每笔 fill、最终账户证据齐全。`audit_status=verified` 仅表示提供的证据通过该有限一致性审计，不把失败前缀变成完整研究证据。

## 精确算术和 mark 政策

领域运算使用 `Fraction` 的整数分子/分母和受限十进制词法解析，不依赖调用方的全局 `Decimal` 精度、舍入方式或指数范围。输出金额采用唯一有限十进制文本：无指数、无多余尾零、零统一为 `"0"`。这不改变 native 引擎内部金额算法。

令 `p_inc` / `q_inc` 为价格和数量增量，`q_i` / `p_i` 为每笔 fill 的整数 lots / ticks：

```text
physical_quantity_i = q_i × q_inc                         # EUR
physical_price_i    = p_i × p_inc                         # USD / EUR
fill_notional       = Σ physical_quantity_i × physical_price_i
position_quantity   = Σ physical_quantity_i
actual_commission   = Σ 实际 native USD commission
declared_decimal_commission = Σ physical_quantity_i × physical_price_i × maker_rate
native_commission_difference = actual_commission - declared_decimal_commission
```

固定 native 费用链分两次量化：`Quantity/Price` 的 raw fixed-point 整数先转 binary64、除以固定 scalar；二者相乘得到 binary64 notional，构造第一份 USD `Money`；notional 的十进制金额乘费率，再转 binary64 并构造 commission `Money`。USD `Money` 的量化是 binary64 `amount × 100` 后 Rust 正数 half-away rounding。依据为固定 v1.231.0 的 [fee.pyx](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/nautilus_trader/backtest/models/fee.pyx)、[objects.pyx](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/nautilus_trader/model/objects.pyx)、[money.rs](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/crates/model/src/types/money.rs) 与 [fixed.rs](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/crates/model/src/types/fixed.rs)。这与直接对精确理论费用做一次 half-even 舍入不同。

领域用有理整数精确模拟每次 IEEE-754 binary64 nearest-ties-even 转换/运算，再模拟两级 USD 量化；生产审计代码也不依赖宿主 float。不是给 `actual - theoretical` 设置一分钱宽容区间。当前输入范围远离 binary64 subnormal / overflow；遇到不支持的数值范围拒绝。

S3 result 未绑定 native `HIGH_PRECISION_MODE`，因此审计同时计算 raw scalar `10^9` 与 `10^16` 的候选；不得从自报 commission 反推并选定 mode。同一次运行的实际费用必须与至少一个一致的全局 mode 相容。如果某笔有两种不同 cent 结果，`fee_model_verification.status=ambiguous`，即使运行 completed 也不给估值或 claim truth；新增 `ineligibility_reason=ambiguous_native_fee_model`。候选唯一时，实际 commission 必须**精确相等**，偏差一分钱也拒绝。没有 fills 时标为 `not_applicable`，有 fills 且所有候选唯一才为 `verified_unique`。

例如 `price=10000.065, quantity=1, maker_rate=1` 产生 `10000.06` / `10000.07` 两种 cent 候选，本契约不能把任何一个自报值变成研究估值。正常 `100 × 1 × 0.01` 的唯一费用为 `1`；把它改成 `0`、`0.99` 或 `1.01` 并同步改写账户余额仍会失败。最终 eligible 研究估值扣除已独立核验的实际 commission；精确理论值和 native 差额仍分别保留，不声称 native 内部全为 Decimal。

只有 `execution_status=completed`、全部输入闭合、无 open orders / pending commands、至少有一笔正数量成交、费用模型候选唯一时才估值。`mark` 取**最后一个已处理 snapshot/delta 之后重建的 best bid**，引用该条 book 输入；最后一条输入如果是 trade，不能把该 trade 当作 mark 来源。

```text
realized_pnl         = 0                         # 没有卖出平仓
gross_unrealized_pnl = position_quantity × mark_price - fill_notional
net_marked_pnl       = gross_unrealized_pnl - actual_commission
```

这是观测 bid 的 mark 估值，不是保证成交、可清仓收益或已实现利润。`available_quantity_lots` 原样记录 best bid 可见数量；它可能小于持仓。这里没有模拟按深度卖出、市场冲击、退出延迟、退出手续费、队列可辨识性或真实成交校准，也没有由 L2 推导精确排队位置。

若回放 incomplete / failed，或 completed 但没有 fill，则 `valuation_status=not_eligible`，`mark=null`、`valuation=null`。拒单或未成交不能变成“零收益研究成功”。独立 `ledger` 可以保留已核对的成交数量和费用，但没有 claim truth。研究声明、阈值、协议、开发集/确认集与探索次数在上层绑定；本契约没有创建第二套 protocol 或反例搜索结果枚举。

## 输出形状

以下数字来自可手查的两笔买入示例：各 1 EUR × 100 USD，费用各 1 USD，最后 bid 100 USD。完整对象的顶层字段是固定集合；示例哈希用占位文字说明，真实值必须为 64 位 SHA-256 小写十六进制。

```json
{
  "kind": "replay_evaluation_v1",
  "schema_version": 1,
  "evaluation_policy": "last_observed_bid_mark_v1",
  "bindings": {
    "dataset_id": "<dataset manifest SHA-256>",
    "data_sha256": "<normalized bytes SHA-256>",
    "spec_id": "<canonical spec SHA-256>",
    "result_sha256": "<canonical replay result SHA-256>",
    "engine": {
      "id": "nautilus-trader",
      "version": "1.231.0",
      "semantic_id": "nautilus_v1_receive_order_single_limit_buy_v1"
    }
  },
  "audit_status": "verified",
  "execution_status": "completed",
  "valuation_status": "valued",
  "ineligibility_reason": null,
  "unit": "USD",
  "fee_model_verification": {
    "policy_id": "nautilus_v1_binary64_usd_double_quantization_v1",
    "status": "verified_unique",
    "raw_precision_candidates": [9, 16],
    "ambiguous_fill_ordinals": []
  },
  "ledger": {
    "fill_count": 2,
    "requested_quantity_lots": 2,
    "filled_quantity_lots": 2,
    "position_quantity": "2",
    "fill_notional": "200",
    "actual_commission": "2",
    "declared_decimal_commission": "2",
    "native_commission_difference": "0"
  },
  "mark": {
    "source_ref": {"line": 7, "capture_seq": 7, "event_type": "delta"},
    "native_time_ns": 1700000003000000100,
    "price_ticks": 100,
    "price": "100",
    "available_quantity_lots": 1
  },
  "valuation": {
    "realized_pnl": "0",
    "gross_unrealized_pnl": "0",
    "net_marked_pnl": "-2"
  }
}
```

不满足估值资格的 `ineligibility_reason` 只允许：`execution_incomplete`、`execution_failed`、`no_fills`、`ambiguous_native_fee_model`，按该顺序优先表达回放未闭合和无成交。金额、数量 ledger、fee-model 状态与 mark 算术由严格 loader 再校验。没有 `claim_satisfied`、`NO_COUNTEREXAMPLE_FOUND`、全局稳健性或市场验证字段。

纯核心测试位于 [test_evaluation.py](../../tests/domain/test_evaluation.py)。测试覆盖手算估值、全局 Decimal context、IEEE binary64 转换、half-cent/近边界/双级量化/大名义额、mode ambiguity、一分钱及零费用自洽改写、篡改源字段与账户、复制成交、未完成撤单、失败及无成交结果；不需要 native 引擎或外部行情。S3 原始 golden result 可通过该审计，但这不是新增性能 benchmark，也不扩大引擎支持矩阵。
