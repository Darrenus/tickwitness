# Executable research protocol v2

状态：S4 受限开发链路契约。v2 将命题、内置回放模型、估值策略与预算绑定为一个新对象；它不是 [FrozenProtocol v1](frozen-protocol-v1.md) 的升级或执行开关。v1 的 `execution_ready=false` 始终保持不变。两种 loader 互相拒绝对方格式。

本契约复用 [Replay qualification v1](replay-v1.md) 的单资产、内置 `single_limit_buy_v1`、接收顺序时钟及完整性边界。领域依赖方向见 [领域模型](../architecture/domain-model.md)，数据前置条件见 [normalized events](normalized-events-v1.md)。构建协议只验证值，不能凭协议文件证明数据可用、实际执行、估值正确或研究命题成立。

## 1. 入口与身份

```python
from tickwitness.domain.research_contracts.executable import (
    ExecutableProtocol, ProtocolValidationError,
    build_executable_protocol, load_executable_protocol,
)

protocol = build_executable_protocol(
    request_bytes,
    development_dataset_id=development_id,
    confirmation_dataset_id=confirmation_id,
)
same_value = load_executable_protocol(protocol.canonical_bytes)
```

`ExecutableProtocol` 是 frozen/slots 值对象，只保存 `protocol_id`、`claim_revision_id`、`canonical_bytes`。构造器也重新验证内容与身份；`document` 每次解码为独立副本，修改嵌套字典不能改变已注册协议。

- `claim_revision_id` 是规范化 claim 的 canonical JSON SHA-256。采用 v1 的同一命题规范化规则；同一规范化 USD claim 在两个版本具有相同的 claim revision ID。
- `replay_spec_id` 是内嵌规范化 ReplaySpec 的 SHA-256，与独立构建的 ReplaySpec ID 一致。
- `protocol_id` 是完整 v2 document canonical bytes 的 SHA-256，不内嵌自身 ID。
- 更改费用、延迟、内置策略参数、seed、数据集或预算产生新 protocol ID；只要规范化命题未变，claim revision ID 保持不变。更改命题、比较符、阈值等 claim 内容产生新 claim revision ID。

canonical JSON 固定 UTF-8、object key 排序、紧凑编码，不自动重排数组。load 仅接受精确 canonical bytes；build 可以规范化字段顺序和等价十进制写法。

## 2. 请求 exact schema

请求最多 **128 KiB**，必须为非空 UTF-8 JSON object。拒绝重复 key、float token、NaN/Infinity、BOM、非法 Unicode、未知/缺少字段及超限输入。整数要求真正 int，bool 不能冒充 int。

| 顶层字段 | 规则 |
| --- | --- |
| `schema_version` | 真 int `2` |
| `claim` | exact `{title,hypothesis,metric,comparator,threshold,unit}` |
| `replay_spec` | 完整的 ReplaySpec JSON object，不能是路径、URL、bytes 或 v1 research protocol |
| `budget` | exact `{max_attempts,max_wall_seconds,max_events}` |

claim 的 title 最长 200 字符、hypothesis 最长 2,000 字符，均非空且没有前后空白/控制字符。metric 固定 `net_marked_pnl_v1`，unit **严格为 `USD`**，comparator 为 gt/ge/lt/le。threshold 是普通十进制字符串，拒绝 exponent；输入最多 28 digits、18 位 fraction，去除多余零和正号，负零归零。规范化不依赖全局 Decimal context。

replay_spec 沿用 [v1 exact schema](replay-v1.md#2-replayspec-exact-schema)：只支持 EUR/USD 和 `single_limit_buy_v1` 内置策略，时钟固定 `receive_order_v1`，账户为受限 MARGIN/NETTING 语义。拒绝任何用户 Python 源码、source hash、策略文件或任意执行入口。内嵌字段也要通过其大小、整数、货币、精度和范围约束。

| 预算 | 真 int 范围 |
| --- | --- |
| `max_attempts` | 1..100 |
| `max_wall_seconds` | 1..60 |
| `max_events` | 1..10,000 |

development 和 confirmation ID 由 API 单独绑定，均为 64 字符小写 hexadecimal hash，必须不同。它们引用上层 sealed dataset manifest，不直接等同 normalized bytes 的 hash。build/load 不读取任一数据集。

## 3. 冻结后的 exact document

| 字段 | 固定内容或绑定 |
| --- | --- |
| `kind` | `executable_research_protocol_v2` |
| `schema_version` | 真 int `2` |
| `read_policy` | `development_only_v1` |
| `evaluation_policy` | `last_observed_bid_mark_v1` |
| `claim_revision_id` / `claim` | 规范化命题身份与内容 |
| `datasets` | exact `{development: <id>, confirmation: <id>}` |
| `strategy` | exact `{kind: "builtin", id: "single_limit_buy_v1", semantic_id: "nautilus_v1_receive_order_single_limit_buy_v1"}` |
| `engine` | exact `{id: "nautilus-trader", version: "1.231.0", semantic_id: "nautilus_v1_receive_order_single_limit_buy_v1"}` |
| `replay_spec_id` / `replay_spec` | 完整规范化回放参数及其身份 |
| `budget` | 上述预算 |

该 document 同样最多 128 KiB。没有 `execution_ready` 字段；v2 kind 表示一个支持受限执行链路的契约版本，实际运行仍须通过应用门禁。没有未被执行的用户策略 source hash；strategy descriptor 诚实声明内置策略身份和固定适配器语义。

load 重新构建整份文档并按编码比较，重算 claim/spec/protocol 身份，拒绝伪造 engine、策略、估值策略、read policy、额外授权字段或非 canonical 数据。仅有一个匹配文件 SHA-256 不足以绕过这些语义检查。

## 4. 应用必须执行的门禁

应用应先验证真实 development/confirmation 数据集的完整存储闭包、规范化字节和报告，检查严格向前且不交叠的分区关系，再对 development 运行 replay preflight。确认集只作为外部 hash 引用登记，不从普通 inspect、run 或 evidence bundle 返回确认行情。

每次执行前必须对本协议的 `max_attempts` 做持久化 reserve；失败、超时和 worker 异常也占用 attempt。worker 的 wall limit 和事件上限不得超过 protocol budget 或底层 replay 上限。领域对象与本 registry 不替代这个生命周期，也不伪造尝试记录。

目前预算保证的范围为 **单个 protocol ID**。修改参数或预算会产生新 ID；它不自动形成跨协议、跨命题 family 的完整统计账本，也不能据此宣称完成多重检验校正或没有过拟合。

估值使用 policy `last_observed_bid_mark_v1`，金额单位 USD，root application 将估值的 `net_marked_pnl` 与 claim threshold/comparator 绑定。incomplete、failed 或 evaluator 判为 not_eligible 的结果不能伪装为已完成的数值判定。单次模型内的计算结果不证明现实获利，不解封 holdout，也不等于反例搜索或稳健性证明。

## 5. 本地不可变登记

```python
from pathlib import Path
from tickwitness.infrastructure.executable_registry import (
    LocalExecutableProtocolRegistry,
    ExecutableRegistryError, ExecutableProtocolNotFoundError,
)

registry = LocalExecutableProtocolRegistry(Path("/trusted/root/executable-protocols"))
record = registry.seal(protocol.canonical_bytes)
read_only = LocalExecutableProtocolRegistry(
    Path("/trusted/root/executable-protocols"), create=False,
)
same_record = read_only.get(record.protocol_id)
```

记录为 frozen/slots `ExecutableProtocolRecord(protocol_id,canonical_bytes,created)`。独立可信根仅保存 `protocols/<protocol_id>.json`，没有用户源码、行情副本、SQLite catalog 或可变 attempt 状态。不能以旧 v1 registry 的宽松存储 envelope 代替本 registry 的严格 v2 loader。

seal 在写制品前通过完整领域 loader。临时文件采用 exclusive/no-follow 创建，写完 flush/fsync 后通过同目录 hard link **原子、不覆盖**发布，随后 fsync 目录。并发同内容只有一个 created=true，其他调用验证已有文件；已有内容损坏则拒绝，不能静默覆盖“修复”。提交文件出现是可见性边界，读者不会读取半写 JSON。

get 通过 no-follow directory/file descriptor 读取，拒绝 symlink、FIFO、非普通文件、超限数据、hash 不符及不合法的 v2 envelope。`create=False` 的初始化和 get 不创建缺失目录、不写入文件，也不执行数据库迁移。create 参数控制目录初始化，不能作为针对可信本地 owner 的权限沙箱。

根目录的父路径和本机 owner 是可信配置；当前实现要求 POSIX 的 no-follow、directory descriptor 与同目录 hard-link 能力。遭遇发布后的 fsync 错误可能返回错误但已有完整提交，调用方应以同一 ID get/seal 复核结果。崩溃可能遗留未发布 `.pending-*` 临时文件；get 不将其视为协议，本批没有自动清理或跨文件系统事务承诺。
