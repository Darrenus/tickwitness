# Search Plan v1

状态：S07-01a 实现合同，远端验收与 owner 接受待完成。基线为已接受的 [S06-02d / PR #87](https://github.com/Darrenus/tickwitness/pull/87)，本轮不发行新版本。

## 用途与边界

`SearchPlan` 把已支持的单一接收后缀延迟变换变成可持久冻结的候选序列。它冻结原 `ExecutableProtocol v2`、同一 `AssumptionSpec`、提议种子、生成器与原始提议预算；完整 journal 保留重复与范围拒绝。读取时重建候选顺序和决策，应用再从实际 development 数据重验来源与派生候选。

本切片不会启动策略、读取研究执行结果、预留 attempt 或发出 finding；领域 journal 的 `ELIGIBLE` 只表示唯一候选处于声明范围内，成功的应用回执再证明这些候选通过实际来源的派生预检，未表示引擎已经完成或命题成立。S07-01b 才接入自动评估与 attempt/outcome 关联，S07-02 才形成 campaign 的执行时间／存储硬预算，S07-03 才定义搜索结论。当前 proposal journal 不是完整统计 trial-family 账本。

范围固定为 [Assumption / Scenario v1](assumption-scenario-v1.md) 的 `replay_receive_suffix_shift_v1`，anchor 固定、单位 ns、`COUNTERFACTUAL_STRESS`、研究者给定且未校准。它沿用 [耦合时钟执行](scenario-execution-v1.md) 的限制，不自动成为独立网络接收延迟模型或历史观测相容解释。S06 的 tagged finding 权限不适用于本计划。

## 请求

请求须为最多 64 KiB 的非空 UTF-8 JSON，拒绝重复键、未知／缺失字段、浮点数、布尔冒充整数、非有限值及非规范类型。精确顶层字段为：

```json
{
  "kind": "search_plan_request_v1",
  "schema_version": 1,
  "search_seed": 17,
  "max_proposals": 4,
  "generator": {"kind": "grid", "values_ns": [0, 0, 1000000000, 3000000000]}
}
```

`search_seed` 是 `0..2^63−1` 整数，独立于 `ReplaySpec.seed` 的原生撮合 RNG；它不改变原执行规范或预算。`max_proposals` 为 `1..1024`。所有候选参数均须为 `0..60_000_000_000` 的整数 ns；60 秒是工程支持限额，未表示网络、交易所或物理延迟证据。

Grid generator 精确字段为 `kind` 与 `values_ns`，列表长度 `1..1024`，保持原顺序，包括重复值。它是显式离散列表，不推断连续区间或自动排序／补端点。Random generator 精确字段如下，范围含两端且 minimum 不大于 maximum：

```json
{
  "kind": "random_integer_with_replacement",
  "minimum_ns": 0,
  "maximum_ns": 3000000000
}
```

两种生成器都按原始提议计数；重复和被拒提议仍占一次 `max_proposals`，不会继续抽样补足有效候选。Grid 只访问列表前 `min(length,max_proposals)` 项；未访问后缀不是已拒候选。Random 生成恰好 `max_proposals` 项，允许重复；这不是无放回抽样，也没有覆盖全空间的保证。

## 固定随机政策

生成政策为 `bounded_receive_delay_proposals_v1`，随机政策为 `sha256_counter_rejection_v1`。随机字节流来自：

```text
SHA256(
  ASCII("TickWitness/search-delay/sha256-counter-rejection/v1") || 0x00
  || uint64_big_endian(search_seed)
  || uint64_big_endian(counter)
)
```

Counter 从 0 开始，每次 digest 后增加，包括被整数拒绝采样丢弃的 digest。Digest 解释为无符号 256 位 big-endian 整数 x。令 `span=maximum−minimum+1`，`limit=2^256−(2^256 mod span)`；仅接受 `x<limit`，结果为 `minimum+(x mod span)`。整份计划最多尝试 1,048,576 个 digest；若耗尽，整份计划失败且不发布，不能静默删掉提议或把失败当已覆盖。

这固定了跨 Python 版本的选择算法；固定种子是可复现的伪随机提议，不是市场概率、统计独立性或安全随机数保证。改变提议预算时，原始序列具有前缀稳定性；改变种子、区间、合同或生成政策产生不同计划身份。原生撮合 seed 与上述字节流无关。

## 候选身份与 journal

每个条目精确记录 `ordinal`、`delay_ns`、`scenario_id`、`status`、`duplicate_of`、`reason`。Ordinal 从 1 开始，连续覆盖实际生成的原始提议。对每个延迟值，先检查是否已有较早相同值：

| 情形 | status | scenario_id | duplicate_of / reason |
| --- | --- | --- | --- |
| 首见且在冻结 assumption 范围内 | `ELIGIBLE` | 原有 `ScenarioSpec.scenario_id` | null / null |
| 首见且超出冻结 assumption 范围 | `REJECTED` | null | null / `outside_assumption_range` |
| 重复任意先前值，包括先前被拒值 | `DUPLICATE` | 与该参数规则一致的身份或 null | 最早 ordinal / `duplicate_proposal` |

去重范围只在这一份固定 assumption 的计划内，不跨协议、anchor 或执行语义合并。零延迟可保留源规范化字节，但情景、派生 view 与 catalog dataset 身份仍分开。重复提议不会虚构一次评估，也不能使后续真实重试获得免费 attempt。

计划同时保存 `counts={proposed,eligible,duplicate,rejected}` 和 `generation_stop`。Grid 已访问完整列表时为 `grid_exhausted`，否则为 `proposal_limit`；random 为 `proposal_limit`。这些是生成停止原因，不是执行停止原因、搜索覆盖或收益判定。

## 冻结对象与复核

计划 `kind=search_plan_v1`、`schema_version=1`，嵌入完整 protocol、assumptions、request、对应身份、固定政策、journal、counts、stop、scope 与限制。`plan_id` 是 exact canonical JSON bytes 的 SHA-256；document view 为 detached 数据。Loader 从嵌入声明重新生成完整文档并要求 exact bytes 一致，不能只信任自报 hash、counts 或状态。把错误 journal 的全部 hash 重算仍无法通过。

纯领域对象只检验声明与生成，不访问源数据，因此其 `scope.source_validated=false` 固定不变。应用 freeze／inspect 均从当前 exact protocol 与 development dataset 重建原始／规范化／quality 闭包、AssumptionSpec、来源绑定和 preflight；再派生每个唯一 `ELIGIBLE` 候选并验证。一个候选派生失败会拒绝整份计划，保留原数据与已有证据，不将其偷换成研究反例。

应用派生预检使用 `bounded_derived_event_checks_v1`：实际 source record count × 唯一 eligible 数量最多 1,000,000。超出时明确拒绝整份冻结或 inspect，不抽掉候选以伪造完整计划。该限额是候选与源事件组合规模的工程保护；派生内部会多次 preflight，它不是 CPU 时间或实际处理事件总次数的硬预算，不预留执行槽位，也不认证全局尝试历史。

回执 `kind=search_plan_receipt_v1` 包含 `plan_id`、`created`、完整 `plan` 与 verification。应用层 `plan_recomputed`、`source_revalidated`、`derived_candidates_checked` 为 true，`native_replayed` 为 false；其 scope 始终 `execution_started=false`、`attempt_reserved=false`、`search_performed=false`、`finding_issued=false`。这与领域 scope 的来源未验证标记承担不同责任，不能据此改写已冻结 bytes。

## 存储与 CLI

计划存于单独 `--plans` 根下的 `search-plans/<plan_id>.json`；不改变原 data、registry、runs 或协议预算。POSIX no-follow、nonblocking regular-file 与 2 MiB 上限保护输入，完整 hash 与领域重建一起验证。发布采用临时文件、fsync 与原子 no-replace hard link；同内容重复冻结读取核实后返回 `created=false`。既有损坏文件不覆盖或“自动修复”；提交后持久性错误保留可观察证据。根及其父路径是可信 owner 配置，不是恶意宿主沙箱或访问控制。

```sh
tickwitness freeze-search-plan PROTOCOL_ID \
  stress-assumption-request.json search-grid-request.json \
  --input-root examples --registry registry --store data --plans plans

tickwitness inspect-search-plan PLAN_ID \
  --registry registry --store data --plans plans
```

两条命令均仅限 development。`--split confirmation` 必须在 ID、输入、数据或 repository factory 访问前拒绝；缺失根的 inspect 不创建目录。Inspect 重验需要原 protocol 与 source，不是已封存的可迁移离线证据包。自动执行、完整 trial 记账、全预算搜索、确认集解封、统计检验与搜索 finding 权限都需后续合同，不通过改本计划 scope 提前授权。
