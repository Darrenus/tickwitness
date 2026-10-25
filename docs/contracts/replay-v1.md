# Replay qualification v1

本批提供受限的引擎资格验证契约，不执行 FrozenProtocol v1，不评价研究命题、不产生研究 finding、不解封确认集。`ReplaySpec` 与 frozen research protocol 是不同类型；后者的 `execution_ready=false` 不会被回放入口改为 true。

数据基础见 [normalized-events-v1](normalized-events-v1.md)，声明边界见 [frozen-protocol-v1](frozen-protocol-v1.md)，领域/质量原则见 [领域模型](../architecture/domain-model.md) 与 [质量策略](../quality/quality-strategy.md)。实际引擎版本与行为须由 adapter、integration tests 和基准证据另行确认，不能仅因 domain 预检通过就称真实成交被验证。

## 1. 端口与真正不可变的 DTO

```python
from tickwitness.domain.replay.specs import build_replay_spec, load_replay_spec
from tickwitness.domain.replay.contracts import (
    ReplayInput, ReplayPort, ReplayResult, build_replay_result, load_replay_result,
)
from tickwitness.domain.replay.preflight import preflight_replay

spec = build_replay_spec(spec_bytes)
request = ReplayInput(dataset_id, normalized_bytes, spec)
prepared = preflight_replay(request)  # 必须在加载 native 依赖之前完成
```

- `ReplayPort.run(replay_input: ReplayInput) -> ReplayResult` 是同步应用端口，domain 不导入引擎或文件/数据库 IO。
- `ReplaySpec` 保存 `spec_id` 与 canonical bytes；spec_id 为完整 canonical bytes SHA-256，不内嵌自引用。
- `ReplayInput` 保存合法的 dataset ID、不可变 normalized bytes、实际 ReplaySpec，拒绝任意对象/研究协议替代 spec。
- `PreparedReplay` 保存 replay_input、spec、dataset_id、data_sha256、三段 stream tuple 与 `tuple[ReplayEvent,...]`。
- `ReplayEvent` 使用 frozen/slots 与嵌套 tuple 保存价位，不保存可变列表；包含 line、capture_seq、event_type、原始 event/receive time、book sequence、bids/asks 和 trade 字段。`source_ref` 返回新的 `{line,capture_seq,event_type}`。
- `ReplayResult` 仅保存 canonical bytes；`document` 每次解码成新副本。构建与加载均验证结构，不能用后改的字典改变已生成结果。

dataset ID 是上层 sealed manifest 的引用，不等于 normalized bytes hash；data_sha256 单独绑定实际规范化内容。应用层必须先确认 dataset ID、存储闭包、规范化与报告一致，domain 不能仅凭这两段字节重建上层 manifest 身份。

## 2. ReplaySpec exact schema

输入为非空 UTF-8 JSON object，最多 64 KiB。拒绝重复 key、未知/缺少字段、float token、NaN/Infinity、非法 Unicode、BOM 与超限嵌套。整数必须是真正 int，boolean 不能冒充 int。

```json
{
  "schema_version": 1,
  "clock_policy_id": "receive_order_v1",
  "instrument": {
    "base_currency": "EUR",
    "quote_currency": "USD",
    "price_increment": "1.00",
    "size_increment": "1"
  },
  "account": {"starting_cash": "10000.00"},
  "fees": {"maker_rate": "0.01", "taker_rate": "0.02"},
  "execution": {"insert_latency_ns": 0, "cancel_latency_ns": 0},
  "strategy": {
    "kind": "single_limit_buy_v1",
    "submit_capture_seq": 1,
    "limit_price_ticks": 100,
    "quantity_lots": 2,
    "cancel_after_first_fill": false
  },
  "seed": 7
}
```

这是合成资格验证请求，不是交易建议。该 schema 不接受 strategy source、研究协议、参数脚本、账户模式或其他策略种类。账户语义固定为 adapter 资格验证的 **MARGIN / NETTING**，不是任意交易市场支持承诺。

| 范围 | v1 限制 |
| --- | --- |
| 资产 | spec 只能 EUR/USD，源记录的 instrument 必须严格为 `EUR-USD`；不支持把 BTC/USDT 或 TEST-USD 重新解释成欧元美元 |
| price/size increment | 纯十进制字符串，正数且不超过 1,000,000，规范化后至多 8 位小数 |
| starting_cash | 正 decimal、最多 1,000,000,000、规范化后最多 2 位小数，单位 USD |
| maker/taker rate | decimal 范围 0..1，规范化后最多 8 位小数；不支持负费率返佣 |
| insert/cancel latency | 真 int，0..60,000,000,000 ns；最终接收时间加两种延迟不能溢出 signed int64 |
| submit_capture_seq | 正 int64，必须对应实际输入记录 |
| limit ticks / quantity lots | 正 int64，物理映射与 derived notional 还须通过下文限制 |
| seed | 非负 int64 |

decimal 输入仅接受 `[+-]?[0-9]+(?:\.[0-9]+)?`，最多 28 位 digits、18 位输入 fraction；去掉多余零与正号，负零归零，再检查各字段的规范化精度。指数、数字 token、字符串空白均不自动转换。规范化和物理范围运算使用整数有理数，不依赖全局 Decimal context，也不经过 float。

`load_replay_spec` 仅接受已经精确 canonical 的字节；`build_replay_spec` 可以规范化普通字段顺序和 decimal 等价写法。规范化固定 UTF-8、object key 排序、紧凑 JSON，不对数组重排。

## 3. native import 之前的预检

1. 输入上限为 8 MiB / 10,000 记录，必须已是 canonical normalized JSONL。没有排序、补包或静默丢弃记录。
2. 仅一个 source/instrument/session，第一条必须是 snapshot，之后不允许 resnapshot。拒绝所有缺口、冲突、重复、过时记录及未知 receive time；不能把 S2 的 accepted 当作回放许可。
3. `receive_time_ns` 全部已知且非递减，逐条要求 `event_time_ns <= receive_time_ns`。同一 receive time 仍按输入 capture 顺序处理。
4. 真正重建 price→absolute quantity 盘口；delta 同时更新两侧后检查最终状态，拒绝 absent-level deletion、累计超过 1,000 档/侧、空侧、锁定或 crossed book，以及两侧都空的 no-op delta。
5. `ticks × price_increment` 与 `lots × size_increment` 必须精确、为支持范围，最大物理 price/quantity 为 1e9。每个价位/成交的 quote notional，以及策略 quantity 与每个已观察价格/自身限价的 notional，均不得超过 1e9，防止单项合法但乘积溢出 native money 范围。
6. `submit_capture_seq` 必须存在；不存在时明确拒绝，不能选择附近事件替代。

trade 不自动消耗本地价位；L2 depth 和 trade 是两种输入，不能用重复应用推断全部订单身份。检查器没有证明数据来自真实市场，没有检测 hidden liquidity，也没有校准队列或真实冲击。

`receive_order_v1` 在 native 中将 `ts_event = ts_init = receive_time_ns`，原 event_time 仍保留在 trace。这是**声明的接收顺序仿真时钟**，不是 UTC、NTP 误差或历史可得性的认证。给出一串符合大小关系的时间值不等于拥有真实时钟证据。

adapter 必须先调用 preflight，再加载 native 模块。native 内部可以使用 capture_seq 关联 sequence、用 `CAPTURE-<capture_seq>` 作为内部 TradeId；这些标记不是原交易所序列/TradeId，必须保留原字段与 source_ref。实际同刻 matching/command 触发语义由固定 engine semantic_id 和 integration tests 说明，不能拿上一条 callback 的上下文冒充当前输入。

## 4. Result exact envelope 与环境条件

`build_replay_result(document)` 验证字典后封装 canonical bytes；`load_replay_result(raw)` 最多读取 16 MiB，重新验证 exact schema、types 与 canonical encoding。严格拒绝未知顶层字段，尤其不能嵌入 research finding、claim verdict、确认授权或 execution_ready。

| 顶层字段 | 类型/规则 |
| --- | --- |
| `kind` / `schema_version` | `replay_qualification_result_v1` / 真 int 1 |
| `engine` | exact `{id,version,semantic_id}`，bounded nonempty strings |
| `environment` | exact `{python_version,platform,package_versions}`；package_versions 为非空、最多 128 项的 name→version string object |
| `dataset_id` / `data_sha256` / `spec_id` | 各为 64 字符小写 hexadecimal SHA-256 |
| `execution_status` | completed / incomplete / failed，必须与 completeness 一致 |
| `completeness` | 下节定义 |
| 五类 trace | input_trace、decision_trace、order_trace、fill_trace、account_trace，全部为 list |

这些指纹描述运行条件，loader 只校验它们的结构与一致性；应用层还必须匹配请求的 dataset/spec/data hash、允许的 engine/version/semantic_id 和执行环境政策。自报的字符串不是软件供应链证明。对不同 engine、环境、spec 或数据的结果，不能声称严格同条件比较。

## 5. Trace 与稳定源引用

每个 channel 内的每一行 exact 为：

```text
{
  kind: bounded nonempty string,
  ordinal: 真 int，自此 channel 的 0 连续递增,
  native_time_ns: 非负 int64,
  source_ref: {line: 正 int, capture_seq: 正 int64, event_type: snapshot|delta|trade} 或 null,
  fields: bounded JSON object
}
```

fields 中不允许 float；native money/decimal 应使用精确 string。通用 payload 最大深度 8，object 最多 128 个 key、list 最多 10,000 项、string 最多 4,096 字符，整数保持 signed int64。每 channel 至多 50,000 行，整个编码仍受 16 MiB 上限约束。不同 channel 的 ordinal 不构成全局时间排序。

input_trace 不允许 null source_ref，数量必须等于 processed_records；input line 必须是 ordinal+1 的已处理前缀，capture_seq 严格递增。其他 trace 可以为初始 native account 等 bootstrap 状态提供 null ref；所有非 null ref 和 pending command ref 必须完整匹配某条已处理 input_trace 的引用，不得引用不存在/未来未处理的源事件。

稳定引用为 result.dataset_id 加上 source_ref 的 line/capture_seq/event_type。引擎字段的完整语义、金额核算与真实 native 回调关系还须由 adapter/integration tests 检验；本 loader 不会仅凭 fields 的字符串认证原生成交。

## 6. EOF 完整性与未决命令

completeness exact 字段：

- input_records：1..10,000；processed_records：0..input_records。
- open_orders：`[{order_id: string, status: string}, ...]`，保留 native 仍开放订单。
- pending_commands：`[{command_id, order_id, command_type, decision_ref, source_ref}, ...]`，command_type 为 submit/cancel；source_ref 必须属于已处理输入。
- stop_reason：按以下状态规则决定。

| execution_status | 必要条件 | stop_reason |
| --- | --- | --- |
| completed | 处理全部输入，open_orders 和 pending_commands 都空 | input_exhausted |
| incomplete | 处理全部输入，有 pending commands；优先于开放订单条件 | pending_commands_at_data_end |
| incomplete | 处理全部输入，无 pending 但仍有 open orders | input_exhausted_with_open_orders |
| failed | 可以只处理输入前缀，不伪装完成 | engine_error |

订单已经 FILLED 不代表之前的 cancel 命令已经收到 CancelRejected；pending ledger 只能因实际对应的 native 回报解除。结果不能仅凭订单终态误报 completed。外层 worker 的 wall timeout（最大 60 秒）、进程终止与 IPC 预算由应用/基础设施处理，不由 domain 自动运行或假造执行结果。

## 7. 有限保证

本契约验证的是受限 EUR-USD L2 输入、固定内置策略及结果结构是否具备资格验证前置条件。它没有把 FrozenProtocol 的 research claim 转成可执行对象，没有创建策略源执行口、没有走确认解封，也不证明现实成交或策略获利。下一阶段增加资产、重同步、时钟模型、用户策略或账户模式，需要新 capability、协议与测试，不能自动降级沿用 v1 标记。
