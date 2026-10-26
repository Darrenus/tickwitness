# Queue Constraints v1：外部影子队列约束检查

本契约对应 S06-01a 的声明与只读可行性切片，目标构建仍为未发行的 `0.2.0.dev0`。实现与实际远端验收见 [Sprint 6 状态](../planning/sprint-06-status.md)。本切片不能授权两种新队列模型在用户协议下执行，也不能关闭 S06-01 的完整双模型复放故事。

首个 profile 为 `external_fifo_shadow_queue_v1`。它在给定 L2 外部总量和卖方主动成交记录上，检查两种明示撤单分配：先从队前撤、先从队后撤。模型使用虚拟 queue cut 区分 ahead/behind，自己的模拟订单不计入外部观测总量。该 cut 不证明自己的订单已在对应 native 时间被接受，不证明真实排队位置、市场影响或外部成交。

## 声明、来源与输出身份分开

请求为 UTF-8 JSON object，最多 64 KiB，采用 exact schema；拒绝重复 key、未知或缺失字段、float、NaN/Infinity、bool 冒充整数和不支持的 marker。请求不能自填 bindings、target、资格标记或可执行代码。

```json
{
  "kind": "queue_constraint_request_v1",
  "schema_version": 1,
  "model_profile_id": "external_fifo_shadow_queue_v1",
  "entry_capture_seq": 1,
  "parameter_basis": {
    "kind": "researcher_defined",
    "calibration_status": "uncalibrated",
    "calibration_evidence_refs": []
  },
  "assumptions": {
    "priority": "fifo",
    "hidden_liquidity": "excluded",
    "impact": "shadow_no_impact_unverified",
    "flow_timing": "adds_then_cancels_at_checkpoint_v1"
  },
  "updates": [
    {"capture_seq": 2, "additions_lots": 3, "cancellations_lots": 0, "trade_capture_seqs": []},
    {"capture_seq": 3, "additions_lots": 0, "cancellations_lots": 3, "trade_capture_seqs": []},
    {"capture_seq": 5, "additions_lots": 0, "cancellations_lots": 0, "trade_capture_seqs": [4]},
    {"capture_seq": 6, "additions_lots": 0, "cancellations_lots": 0, "trade_capture_seqs": []}
  ]
}
```

样例对应仓库原创 [queue-observations.jsonl](../../examples/queue-observations.jsonl) 和 [请求文件](../../examples/queue-constraint-request.json)。所有数量单位均为绑定 ReplaySpec 的整数 `lots`。`entry_capture_seq` 固定为初始 capture 1 snapshot，策略的 submit capture 也须为 1，insert latency 须为零；这些软件前置条件不构成 native acceptance 证据。

`parameter_basis` 固定为研究者设定、未校准、空校准引用。FIFO、排除隐藏流动性、虚拟订单无市场影响及 checkpoint 内的流顺序都是明示模型假定，不是从 L2 聚合观测推断的事实。`shadow_no_impact_unverified` 不能改写为已校准或观测相容标签。

builder 从实际 `ExecutableProtocol v2` 和 `ReplayInput` 注入 exact bindings：`protocol_id`、`development_dataset_id`、`normalized_sha256`、`replay_spec_id`。dataset ID 引用 sealed manifest，normalized hash 绑定实际字节，两者不混用。target 的 `source/instrument/session` 来自实际单一流，`side=bid`，`price_ticks` 来自冻结策略的 limit price；调用方不能指向另一队列再复用原身份。

canonical spec kind 为 `queue_constraint_spec_v1`；`constraint_id=SHA256(canonical_bytes)`。其 loader 只验证结构、canonical bytes 与身份，不能单独证明来源对象存在。`validate_queue_constraints` 必须取得实际 protocol/input，重新验证 immutable 值、source bindings、ReplaySpec、preflight 与队列约束，输出 `QueueFeasibilityPair`。pair kind 为 `queue_feasibility_pair_v1`，`validation_id=SHA256(canonical_bytes)`；两类 `document` 均返回独立副本。

## 完整输入与数量守恒

输入保持现有 receive-order preflight：单流、首次 snapshot、连续 capture/sequence、已知非递减 receive 时间和 supported instrument。队列切片最多 1000 个事件，同时不超过原协议冻结 `max_events`；initial queue、单项及累计流量受 1,000,000,000 lots 软件限额约束。这不是实测市场上界。

初始 snapshot 必须在策略 limit bid 暴露正外部数量。声明的每个 update 必须按 capture 顺序，恰好覆盖后续每个含该 target bid 的 absolute delta checkpoint，不可漏掉或额外增加。任一 target trade 只能在稍后一个 checkpoint 区间中对账一次，`trade_capture_seqs` 必须等于该区间全部实际成交引用，顺序相同。当前只支持 target price 的卖方主动成交；其他成交范围不被静默吸收为同一队列。

对每个 checkpoint，以前一 checkpoint 的外部总量 `V`、本区间实际成交总量 `T`、声明 gross additions `A`、gross cancellations `C` 核验：

```text
V_next = V - T + A - C
V_next >= 0
```

absolute L2 delta 更新的是可见总量；trade 不会由基础 normalize 层自动扣减盘口。因此这里显式用 trade 引用对账，不能再把同一深度减少全部算成 cancellation。净变化相同可以对应不同 gross `A/C`，这些未记录的分解保持为模型假定；算术自洽不能证明它就是交易所实际订单流。

两个影子解释都从 `ahead=initial_external_lots, behind=0` 开始。按源事件顺序处理 trade 时，先消耗 ahead，再消耗 behind；它描述外部总量相对于虚拟 cut 的分配，不输出自己的策略成交。checkpoint 时先把声明新增量加到 behind，再按所选解释分配 cancellation：

| policy_id | 撤单分配 |
| --- | --- |
| `cancel_front_first_v1` | 尽量先撤 ahead，余量再撤 behind |
| `cancel_back_first_v1` | 尽量先撤 behind，余量再撤 ahead |

每一步都要求 ahead、behind 非负，和为外部总量且不超限；trade/cancel 不得消耗不存在的外部量。在 EOF 仍有未被稍后 absolute checkpoint 对账的 trade 时明确拒绝，不补虚构输入闭合账本。

样例从外部 5 lots 开始，新增 3 后撤 3，再有卖方主动成交 3；两个解释最终都对应外部 2 lots，但队前/队后分别为 `0/2` 与 `2/0`。这展示同一声明框架下未知位置如何改变影子分配，不代表策略成交一手或收益翻转。

## 资格标记与逐步轨迹

spec 和 pair 固定包含：

```text
classification = MODEL_SENSITIVITY_CANDIDATE
actual_acceptance_verified = false
impact_compatibility_verified = false
native_execution_verified = false
execution_approved = false
```

pair 另有 `source_bindings_verified=true` 和 `flow_conservation_verified=true`，只表明实际来源绑定与列明的模型约束检查成立，不能认证市场来源、真实队列、相容历史或原生执行。

`interpretations` 是两份 `{policy_id, trace, final_state}`。trace 行保存 `kind`、完整 `source_ref`、原 receive 时间、before/after 的 ahead/behind/external 数量，以及 additions/cancellations/trade 和 cancel-ahead/cancel-behind 分配。它不发布 `fill_trace`、账户账本、估值、claim observation 或 finding；没有“更保守成交就是收益下界”的保证。

## 只读应用与 CLI

应用入口：

```text
validate_queue_contracts(protocol_id, request, *, split, registry_factory, datasets_factory)
```

入口先拒绝非 development，再检查 protocol ID，读取真实 v2 protocol 和 accepted development 数据，注入来源并执行 checker。确认集不会先被读出再丢弃。返回 JSON 顶层 exact `{constraint_id, validation_id, constraint, validation}`。

在受支持远端 CPU 环境中，从本分支固定 commit 安装核心包后，可使用以下流程；不需要 native extra 或 GPU：

```sh
set -eu
TW_QUEUE_ENV=/tmp/tickwitness-queue-core
UV_PROJECT_ENVIRONMENT="$TW_QUEUE_ENV" uv sync --locked --python 3.12
TW="$TW_QUEUE_ENV/bin/tickwitness"
TW_DEV=$("$TW" import-events queue-observations.jsonl --input-root examples --store .local/queue-data --id-only)
TW_CONFIRM=$("$TW" import-events replay-confirmation.jsonl --input-root examples --store .local/queue-data --id-only)
TW_PROTOCOL=$("$TW" freeze-experiment experiment-request.json --input-root examples --development-dataset "$TW_DEV" --confirmation-dataset "$TW_CONFIRM" --store .local/queue-data --registry .local/queue-protocols --id-only)
"$TW" validate-queue-constraints "$TW_PROTOCOL" queue-constraint-request.json --input-root examples --store .local/queue-data --registry .local/queue-protocols --split development
```

import/freeze 是上述显式写入准备步骤；随后的 validate 只读已有持久根，不构造引擎、不创建 ledger、不占 attempt、不发布新数据或运行回执。查询缺失仓库不会创建空根。CLI 校验错误退出 2（`invalid_queue_constraints`），confirmation 拒绝退出 5，缺失源/registry 使用现有存储错误路径。任何错误都不解释为亏损或反例。

## 执行门与兼容边界

现有 v2 仅作为来源绑定对象，不能因 constraint 检查成功授权新 queue profile。公开 `FillModel`、`SimulationModule.pre_process` 和关闭 native 内置 queue 的组合已取得固定 native 资格，9 组实际案例和确切 CI 见 [Sprint 6 状态](../planning/sprint-06-status.md)。有限案例成功仍未验证策略成交对历史外部量的反馈及无市场影响假定，因此保持模型敏感性，也不把固定资格推广为任意用户数据执行支持。

后续用户数据执行需要新的冻结队列族协议，绑定同观测、约束/解释集合、adapter semantic 和共同预算，执行前持久不可替换 intent。每次引擎调用占同父协议一个 slot，失败/超时/中断不退款；不得克隆成两个协议分别重置预算，也不能用 `qualify` 名称反复观察用户策略结果而不记账。新 queue trace/receipt/auditor 必须显式版本化；旧 ReplaySpec v1、ExecutableProtocol v2、baseline bundle 和 S05 比较器保持原保证与严格拒绝。

只有同观测与列明约束下两个可行解释都通过独立验证、原生重放及同一冻结命题的真假审计，才能另行讨论 S06-02 的 `NOT_IDENTIFIABLE_WITHIN_MODEL`。本切片不签发该 finding，不把两种内置配置或两个模型参数的差异改名为观测相容证明。
