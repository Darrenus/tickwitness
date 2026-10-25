# Normalized Events v1

状态：S02-01 已实现的内存验证/规范化契约；尚不提供交易所适配器、文件读取、Parquet 或回放认证。版本：`normalized-events-v1`。设计边界见 [领域模型](../architecture/domain-model.md)、[质量策略](../quality/quality-strategy.md)。

## 1. API 与资源边界

```python
from tickwitness.domain.data_evidence import (
    DataValidationError,
    NormalizedDataset,
    ValidationLimits,
    normalize_events,
)

result: NormalizedDataset = normalize_events(raw_bytes, ValidationLimits())
normalized_bytes: bytes = result.normalized_bytes
report: dict[str, object] = result.report
```

`DataValidationError(ValueError)` 提供 `.message`，与 `str(error)` 相同。输入必须是 `bytes`；失败不会返回部分数据集。domain 只处理字节与值对象，不读取路径、不解压、不联网、不导入外部引擎或文件/数据库 IO。文件、symlink、总上传配额等边界由外围导入服务另行处理。

`ValidationLimits` 是不可变 dataclass，各字段必须为真正的正整数：

| 字段 | 默认值 | 检查范围 |
| --- | --- | --- |
| `max_bytes` | 8 MiB | 原始输入总字节，在解码/解析前检查 |
| `max_records` | 100,000 | JSONL 记录数，在构造逐行记录列表前检查 |
| `max_line_bytes` | 65,536 | 每行原始字节，不计该行 LF/CRLF 分隔符 |
| `max_levels_per_side` | 1,000 | 每条 snapshot/delta 的 bids、asks 各自上限 |

这些限额限制内存工作规模。没有任意脚本、pickle 或其他可执行反序列化路径。外部调用者若自定义更大限额，也相应承担更大的内存上限；此 API 不是进程级资源隔离器。

## 2. 编码和共同字段

输入为 UTF-8 JSONL，每行恰好一个 JSON object，支持 LF 或 CRLF、可省最后一个换行。拒绝 BOM、空记录/空行、无效 UTF-8、未配对 Unicode surrogate、重复 JSON key、非 object 根、未知/缺少字段、浮点语法、NaN/Infinity 和超过解释器嵌套限制的 JSON。

所有数值字段必须是真正的 JSON 整数，`true`/`false` 不能冒充整数。整数范围为 `0..2^63−1`，价格 ticks、数量 lots 与 capture_seq 按下表另有正数限制。`1.0`、`1e3`、数字字符串均不自动转换。

所有记录的共同字段必须完整提供：

| 字段 | 类型/规则 | 含义 |
| --- | --- | --- |
| `schema_version` | integer，恰为 `1` | 协议版本；未知版本拒绝 |
| `type` | `snapshot` / `delta` / `trade` | 记录类型 |
| `source` | identifier string | 数据来源标识，不构成来源真实性证明 |
| `instrument` | identifier string | 交易品种标识；ticks/lots 的实际单位仍需 instrument spec |
| `session` | identifier string | 此来源/品种的捕获会话标识 |
| `capture_seq` | integer，`1..2^63−1` | 在本 stream 内的捕获顺序计数；首次可以从任一正数开始，之后应连续递增 |
| `event_time_ns` | integer，`0..2^63−1` | 来源记录的事件时间值 |
| `receive_time_ns` | 相同范围 integer 或显式 `null` | 本地接收时间值；未知必须保留 null，字段不能省略 |

identifier 必须非空、至多 256 个 Unicode 字符、无首尾空白/控制字符，且可严格编码为 UTF-8。stream 身份为 `(source, instrument, session)`；交织的不同 stream 独立检查 capture_seq 和订单簿序列，不跨 stream 排序。

`event_time_ns` 与 `receive_time_ns` 的时钟未绑定。**不要求接收时间大于事件时间，不要求事件时间单调，也不据此认证延迟。** 接收时间未知仅记录 `UNKNOWN_RECEIVE_TIME`，不能用事件时间补值。时间准确性、clock mapping、UTC 归属和来源可用时间仍需后续协议与证据。

## 3. 三类记录

### snapshot

除共同字段外，恰好包含 `last_sequence`、`bids`、`asks`。`last_sequence` 为已覆盖的最终订单簿序列号。

`bids`、`asks` 是 `[price_ticks, quantity_lots]` 数组的列表。price 与 snapshot quantity 都必须为 `1..2^63−1`，单侧不能重复 price。允许空侧及未排序的价格列表；本函数保留输入顺序，不宣称深度完整、市场状态真实或已检验 crossed book。

### delta

除共同字段外，恰好包含 `first_sequence`、`last_sequence`、`bids`、`asks`。序列范围是闭区间，必须 `0 <= first_sequence <= last_sequence <= 2^63−1`。

delta 数量为**新的绝对档位数量**，不是 signed 增量；`0` 表示删除该档位，其余规则与 snapshot 一致。v1 使用严格连续、非重叠的归一化区间：只有 `first_sequence == 当前已应用 last_sequence + 1` 才能推进有效 epoch。跨 snapshot 边界的重叠 vendor batch 不会被自动裁剪；适配器不能把此协议误称为 Binance 或其他交易所的原始 snapshot/delta 全协议。合法来源消息可能有重叠区间；`OVERLAPPING_DELTA` 只说明它不满足当前 normalized v1 前置条件，不能宣传为交易所来源消息本身错误。

### trade

除共同字段外，恰好包含：

| 字段 | 规则 |
| --- | --- |
| `trade_id` | identifier string，在 stream 内标识同一笔成交 |
| `price_ticks` | integer，`1..2^63−1` |
| `quantity_lots` | integer，`1..2^63−1` |
| `aggressor_side` | `buy` 或 `sell`，主动方方向 |

trade 是观测记录，不直接推进订单簿序列；只含 trade 的合法流可以通过格式检查，但没有有效 L2 epoch，也不因此能执行订单簿回放。

## 4. 最小合成 JSONL 样例

以下是虚构数据，只展示字段与格式。时间值是合成值，不是已校准的真实采集时间；没有真实成交或盈利含义。

```jsonl
{"schema_version":1,"type":"snapshot","source":"synthetic","instrument":"SYN-USD","session":"fixture-001","capture_seq":1,"event_time_ns":100,"receive_time_ns":105,"last_sequence":10,"bids":[[100,2]],"asks":[[102,3]]}
{"schema_version":1,"type":"delta","source":"synthetic","instrument":"SYN-USD","session":"fixture-001","capture_seq":2,"event_time_ns":110,"receive_time_ns":null,"first_sequence":11,"last_sequence":11,"bids":[[100,3]],"asks":[]}
{"schema_version":1,"type":"trade","source":"synthetic","instrument":"SYN-USD","session":"fixture-001","capture_seq":3,"event_time_ns":115,"receive_time_ns":120,"trade_id":"trade-001","price_ticks":100,"quantity_lots":1,"aggressor_side":"sell"}
```

该样例的预期报告为 3 条记录、1 个 stream、`quality_status=accepted`、`unknown_receive_count=1`；第二行有 `UNKNOWN_RECEIVE_TIME`，不生成接收时间。测试直接覆盖同类型的 snapshot/delta/trade 路径。

## 5. 捕获顺序、重复与 epoch

输出保留每一条原记录与原捕获顺序，包括重复、过时和隔离记录；**读取 normalized_bytes 不能忽略报告而把所有 delta 再应用一次**。没有排序、补值、删除、合并消息或恢复丢失历史。

| 条件 | finding / disposition | 状态影响 |
| --- | --- | --- |
| 同 capture_seq 的完整规范化内容相同 | `DUPLICATE_CAPTURE` / `ignored_duplicate` | 保留记录，不重复应用 |
| 同 capture_seq 内容不同 | `CAPTURE_SEQUENCE_CONFLICT` / `quarantined` | 结束当前有效 epoch，数据集隔离 |
| 新出现的 capture_seq 低于高水位 | `OUT_OF_ORDER_CAPTURE` / `ignored_out_of_order` | 不重排；结束 epoch，数据集隔离 |
| capture_seq 跳号 | `CAPTURE_SEQUENCE_GAP` | 结束旧 epoch，数据集隔离；本行若为新鲜 snapshot，可建立新 epoch |
| 新鲜 snapshot，序列不低于本 stream 已观察的 book 高水位 | `applied` | 建立新 epoch；已有 epoch 以 `RESNAPSHOT` 结束 |
| snapshot 序列低于已观察高水位 | `STALE_SNAPSHOT` / `ignored_stale` | 不回滚，不恢复缺口；等待足够新的 snapshot |
| delta 区间及单侧 price→quantity 映射已出现且相同 | `DUPLICATE_DELTA` / `ignored_duplicate` | 不重复应用；新 capture_seq 下的接收时间或档位数组顺序变化不使它变成新 delta |
| 同 delta 区间档位内容不同 | `DELTA_SEQUENCE_CONFLICT` / `quarantined` | 保留冲突证据，结束 epoch |
| 没有有效 snapshot 的 delta | `MISSING_VALID_SNAPSHOT` / `quarantined` | 保留但不应用，等待新 snapshot |
| delta 的 last_sequence 已被当前 epoch 覆盖 | `STALE_DELTA` / `ignored_stale` | 不重复应用 |
| delta 跳过下一必需序列 | `BOOK_SEQUENCE_GAP` / `quarantined` | 缺口起不再应用，直至新鲜 snapshot |
| delta 跨越当前已覆盖与未覆盖区间 | `OVERLAPPING_DELTA` / `quarantined` | 不猜测如何裁剪，结束 epoch |
| 同 trade_id 的事件时间/价格/数量/方向完全相同 | `DUPLICATE_TRADE` / `ignored_duplicate` | 不重复计入；允许接收时间和 capture_seq 不同 |
| 同 trade_id 的上述内容不同 | `TRADE_ID_CONFLICT` / `quarantined` | 不是格式异常；保留双方、结束 epoch，数据集隔离 |

`applied` 仅表示该 snapshot/delta 可以推进**序列检查器**的有效区间，不表示已建立完整价格树或经过引擎认证。普通 trade 的 disposition 为 `observed`。

delta 的语义重复签名使用按 price 排序的临时副本；原规范化行与 bids/asks 原始数组顺序仍完整保留。数量真实改变仍属于冲突。capture_seq 已相同而完整内容不同的情况仍按捕获身份冲突处理，不能借语义签名覆盖捕获证据。

新 snapshot 可以恢复后续状态，**不会撤销数据集整体的 quarantined 标签，也不恢复缺口期间的路径**。处在缺口内的真实 trade 仍可作为观测保存，但没有有效 book_epoch。任何使用区间的回放必须额外检查 epoch、所需输入、能力与冻结协议。

## 6. 规范化与质量报告

规范化编码固定为 UTF-8、JSON object key 排序、无非必要空白、每条末尾一个 LF。字段值、null、记录顺序及 bids/asks 原有顺序均保留。它是本契约的确定性编码，不声称兼容所有外部 JSON canonicalization 标准。

`report` 为 `dict[str, object]`，实际值只包含 JSON-safe 的 string/integer/boolean/null/list/object，不包含 NaN、bytes、异常或 dataclass。

| 字段 | 含义 |
| --- | --- |
| `schema_version` / `normalizer_version` | 报告版本与规范化语义身份 |
| `record_count` / `stream_count` | 物理记录数（含重复/隔离）与 stream 数 |
| `quality_status` | `accepted`：本次格式/序列检查未发现隔离问题；`quarantined`：至少有缺口、冲突等问题；都不是 replay certification |
| `findings` | 每项包含 `code`、1-based `line`、`stream`、`severity`（notice/quarantine） |
| `unknown_receive_count` | 显式 null 的物理记录数，包含重复记录 |
| `record_states` | 每个输入行的 stream、disposition、当时有效的 book_epoch 或 null |
| `book_epochs` | 每个 stream 的局部 epoch 编号、有效起止行、snapshot/最后应用序列、结束原因 |
| `validation_scope` / `checks` | 固定为 schema/sequence preflight，列明实际执行的限额、结构、身份与序列检查 |
| `not_checked` | 完整盘口/crossed book、深度完整性、成交与档位数量一致性、tick/lot spec、来源协议真实性、时钟与回放等未检查项 |
| `book_state_reconstructed` | 恒为 false；本检查器不建立完整价位书 |
| `replay_certified` | 恒为 false |
| `clock_binding` | 恒为 unbound |

epoch 的行号指原捕获行号：被忽略的重复/过时记录仍可位于区间内，必须按 record_states 区分；触发缺口/冲突的行不再属于刚终止的有效 epoch。epoch 末尾 `closed_by=null` 只表示输入结束时尚未因本检查器发现问题而关闭，不表示之后永不缺失。

数据结构非法或超过配额时抛 `DataValidationError`，不生成成功结果；结构合法但历史不连续/冲突时可正常返回并标记 quarantined，以便外围服务原样保存证据。`accepted` 仅表示列明的前置检查通过；即使存在 book_epoch，也不能称作已验证完整盘口。导入成功、序列可用、时点正确与真实市场可信是不同的判断。
