# Frozen Research Protocol v1

状态：本契约描述纯 domain 的声明验证、规范化、不可变冻结与加载。实际数据/源码绑定、存储与读取政策另见[可执行流程](../research-protocols.md)。**冻结只登记声明，不批准执行。** 没有策略运行、收益计算、确认样本解封或完整 trial attempt ledger；访谈也没有因本功能而完成，S02-03 / Issue #6 不能据此整体标记 Done。

领域边界见 [领域模型](../architecture/domain-model.md)、[系统设计](../architecture/system-design.md)、[质量策略](../quality/quality-strategy.md) 和 [Sprint backlog](../planning/sprint-backlog.md)。数据格式见 [Normalized Events v1](normalized-events-v1.md)。

## 1. 纯值 API

```python
from tickwitness.domain.research_contracts import (
    FrozenProtocol,
    ProtocolValidationError,
    build_frozen_protocol,
    load_frozen_protocol,
)

frozen = build_frozen_protocol(
    request_bytes,
    development_dataset_id=development_id,
    confirmation_dataset_id=confirmation_id,
    strategy_sha256=strategy_hash,
)
restored = load_frozen_protocol(frozen.canonical_bytes)
```

`ProtocolValidationError(ValueError)` 提供 `.message`，与 `str(error)` 一致。该 domain 仅使用标准库处理传入字节、标量和哈希，不读取策略文件、数据集、目录、数据库或外部引擎。

`FrozenProtocol` 是 `frozen=True, slots=True` dataclass，只保存三个不可变值：

| 字段 | 含义 |
| --- | --- |
| `protocol_id` | 完整 canonical document bytes 的 SHA-256 |
| `claim_revision_id` | 规范化 claim object canonical bytes 的 SHA-256 |
| `canonical_bytes` | 冻结文档的确定性 UTF-8 编码 |

`document` property 每次独立解码为新的 `dict[str, object]`，不保留可变字典引用。修改返回字典及其嵌套对象不能修改冻结值。直接构造 dataclass 或 `dataclasses.replace` 也会重验文档与两个身份，不能用旧 identity 包装不同文档。

## 2. 请求与编码边界

request 必须是非空 `bytes`，最多 **64 KiB（65,536 bytes）**，恰好一个 UTF-8 JSON object。可以使用普通 JSON 空白、字段顺序和 Unicode escape；构建时统一规范化。拒绝 BOM、非 UTF-8、重复 key、float/exponent 数值 token、NaN/Infinity、非 object 根、非法 Unicode surrogate 及超过解释器嵌套限制的 JSON。

冻结文档增加固定 policy 与内容引用，加载上限为 **68 KiB（69,632 bytes）**，为合法满 64 KiB 请求留下 4 KiB 固定 metadata 余量；这不增加 request 配额。加载要求字节已经是精确 canonical encoding，不自动接受 pretty-printed 或有尾随换行的 frozen document。

canonical encoding 使用 UTF-8、object key 排序、无非必要空白、`ensure_ascii=False`、不允许非有限数。它是本协议的确定性编码，不声称覆盖所有第三方 JSON canonicalization 标准。原始请求若需保存，由应用层另行绑定，domain 的冻结对象不保留可变输入。

## 3. request 的完整 schema

顶层必须且只能包含：`schema_version`、`claim`、`strategy_name`、`parameters`、`configuration`、`budget`、`seed`。嵌套的 claim、configuration、budget 也严格拒绝缺少或未知字段。`schema_version` 必须为真正的 integer `1`；`true` 不等于版本 1。

### claim

| 字段 | 规则 |
| --- | --- |
| `title` | 非空 Unicode text，最多 200 字符，无首尾空白/控制字符 |
| `hypothesis` | 非空 Unicode text，最多 2,000 字符，无首尾空白/控制字符 |
| `metric` | 只能是 `net_marked_pnl_v1` |
| `comparator` | `gt`、`ge`、`lt` 或 `le` |
| `threshold` | 下节规定的纯十进制字符串 |
| `unit` | 最多 64 字符的 identifier |

metric 与 comparator 在此只是研究命题的声明，**当前 domain 没有 evaluator**，不会因此计算或认证净损益。unit 也是引用式声明，不替代真实 instrument/tick/lot/费用与估值规范。

除 threshold 外保留文本的精确内容，不做翻译、大小写折叠、Unicode NFC 或自然语言等价归并。title 也参与 claim identity；编辑其精确内容会产生新的 claim_revision_id。这里的 hash identity 表示规范化内容相同，不表示两个不同措辞的假设在科学意义上等价或独立。

### threshold 的精确规范化

语法为 `[+-]?[0-9]+(?:\.[0-9]+)?`。必须是 JSON string，不接受 JSON number、指数、`.5`、`1.`、千位分隔、空白或 Unicode 全角数字。

- 输入共最多 28 位 ASCII digits（不计 sign/dot，但计前导零和尾随零）。
- 输入小数部分最多 18 位；超过后直接拒绝，不舍入，即使多余部分全是零。
- 去掉整数前导零、fraction 尾随零、正号；空 fraction 时去掉 dot。
- 负零统一为 `0`。例如 `-000.000` → `0`，`+001.2300` → `1.23`。
- 全程按字符处理，不依赖全局 `Decimal` context，也不会用 float 转换。

### strategy_name 与 configuration

identifier 使用 ASCII `[A-Za-z0-9][A-Za-z0-9._:-]*`，策略名和模型引用默认最多 128 字符。标识不解释为文件路径，也不加载同名代码。

configuration 必须且只能包含 `fee_model_id`、`execution_model_id`、`clock_policy_id`。

fee/execution model ID 只验证非空格式与长度；**模型是否存在、受支持或适合执行并未获得批准**。clock policy 当前只能声明 `capture_order_unbound_v1`，明确表示没有完成时钟绑定；不能在请求中设置 `verified_utc` 等值伪造认证。

### parameters、budget 与 seed

parameters 必须是 object，最多 32 项；key 为最多 64 字符的 identifier。value 仅允许 `null`、boolean、signed int64（`−2^63..2^63−1`）或最多 1,024 字符的 Unicode string。参数字符串允许为空及有首尾空格，但不允许控制字符或非法 Unicode；不自动修剪值。禁止 list、nested object、float 和隐式数字转换。

| budget 字段 | 真正的 integer 范围 |
| --- | --- |
| `max_scenarios` | 1..1,000,000 |
| `max_wall_seconds` | 1..86,400 |
| `max_events` | 1..1,000,000,000 |

seed 为真正的非负 integer，范围 `0..2^63−1`；boolean、负数或越界均拒绝。预算只记录声明的上限，不创建作业、资源预留或执行许可；实际执行的政策可以更严格。

## 4. 外部内容身份

三个额外 API 参数都是 **64 字符小写 hexadecimal SHA-256 文本**：development dataset ID、confirmation dataset ID、strategy SHA-256。development 与 confirmation ID 必须不同。

ID 不同不证明底层样本没有交集。这个纯 domain 不知道对象是否存在、是否已封存、是否符合数据格式/质量要求、策略字节是否真的匹配或两个数据集是否重叠。应用层必须读取并验证实际数据与策略 artifact 后再发布，不能把格式合法的 hash 直接当作真实来源证明。

## 5. 冻结文档与身份规则

输出 document 必须且只能含以下 12 个字段：

| 字段 | 固定值或结构 |
| --- | --- |
| `kind` | `frozen_research_protocol_v1` |
| `schema_version` | integer `1` |
| `execution_ready` | boolean **false** |
| `read_policy` | `development_only_v1` |
| `claim_revision_id` | 规范化 claim canonical bytes 的 SHA-256 |
| `claim` | 规范化后的完整 claim object |
| `datasets` | 恰好 `{development: <dataset ID>, confirmation: <dataset ID>}`；值是纯字符串 |
| `strategy` | 恰好 `{name: <strategy_name>, sha256: <strategy hash>}` |
| `parameters` | 已验证的 bounded scalar object |
| `configuration` | 已验证的三个模型/clock policy 引用 |
| `budget` | 已验证的三个正整数 |
| `seed` | 已验证的非负 int64 |

`protocol_id = SHA256(canonical_bytes)`，不内嵌到 document，避免自引用。claim identity 只基于规范化 claim：

- 同一命题声明下，更改数据、策略 hash/名称、参数、费用/执行模型引用、预算或 seed，产生新 protocol_id，保持 claim_revision_id。
- 更改规范化后的 claim 内容，产生新的 claim_revision_id 与 protocol_id。
- `-0`、`+0.000` 等规范化等价 threshold，不制造新版本。

后续应用层可以在登记记录中绑定相应 trial，但本批不构造“已经运行”的 trial、尝试次数或实验结论。完整 family/trial attempt ledger 与确认集访问/解封协议仍属于后续工作。

## 6. 可重现的纯 domain 合成 fixture

下面的 request 与测试使用相同内容。它只展示声明冻结，**没有真实策略文件、实际 dataset、执行或盈利记录**。这里的 a/b/c 重复 hash 是纯 domain fixture 的格式占位，应用层不得把它们视为已存在的 artifact。

```json
{
  "schema_version": 1,
  "claim": {
    "title": "Synthetic net marked PnL declaration",
    "hypothesis": "Under the frozen declared model the net marked PnL exceeds zero.",
    "metric": "net_marked_pnl_v1",
    "comparator": "gt",
    "threshold": "-000.000",
    "unit": "synthetic_quote_units"
  },
  "strategy_name": "synthetic_strategy_v1",
  "parameters": {
    "size_lots": 1,
    "post_only": true,
    "label": "synthetic",
    "optional": null
  },
  "configuration": {
    "fee_model_id": "declared_fee_demo_v1",
    "execution_model_id": "declared_execution_demo_v1",
    "clock_policy_id": "capture_order_unbound_v1"
  },
  "budget": {
    "max_scenarios": 10,
    "max_wall_seconds": 60,
    "max_events": 1000
  },
  "seed": 42
}
```

调用参数为 `development_dataset_id="a" * 64`、`confirmation_dataset_id="b" * 64`、`strategy_sha256="c" * 64`。实际内存构建后的身份为：

```text
claim_revision_id = e674d923b5257c5ebfc4d3b047041fae80d04b0c93c98018ea416b46741d5679
protocol_id       = 83e9dbb51dc642db86fb3415d2afc999829f47fb8c07cd1958f3e53c354e3974
```

输出 claim.threshold 为 `"0"`，document.execution_ready 为 false，read_policy 为 development_only_v1。上述身份来自本契约的声明编码，不是回测结果。

## 7. 加载与防止过度认证

`load_frozen_protocol` 严格解析 bounded canonical bytes，检查 exact schema、固定 kind/policy、hash 格式和所有值约束；随后重建规范化请求、重算 claim identity 并逐字节比较 canonical document。它拒绝：

- `execution_ready=true`，以及用数字 0 假冒 false；
- 修改 read_policy 开启 confirmation；
- claim_revision_id 与规范化 claim 不匹配；
- 在文档内添加 protocol_id 或其他未知字段；
- 非规范化 threshold、非 canonical 字节、非法 clock policy 或超界参数。

如果有人完整构造另一份合法声明并重算其所有内容身份，加载会得到**新的 protocol_id**，不会证明作者身份。可信应用读取已存 protocol 时还必须核对请求的/pinned identity 与返回内容；hash 完整性不替代签名、授权或真实数据验证。

development_only_v1 是冻结声明的读取政策，不是对宿主 owner 隐藏文件的沙箱。实际接口的权限与确认数据保护由应用层落实；确认解封尚未实现时不能通过声明字段授权读取。整个冻结流程不能被描述成已验证 engine/clock、已完成科学审核或已批准执行。
