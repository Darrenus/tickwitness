# Scenario Comparison v1：已提交基线与压力运行的配对报告

本契约对应 S05-03，描述对已有、已提交 run 的关联校验和敏感性观察。它不执行新策略、不预留 attempt、不创建新的 outcome，也不提供搜索、反例或原 baseline claim 翻转结论。实现与真实远端验收状态以 [Sprint 5 状态](../planning/sprint-05-status.md) 和对应 PR 为准；测试文件存在不等于已通过。

仅支持一份 `research_run_receipt_v1 / baseline_v1` 与一份 `scenario_run_receipt_v1 / COUNTERFACTUAL_STRESS`。压力模型仍为 [场景执行 v1](scenario-execution-v1.md) 中的 `coupled_receive_suffix_clock_v1`，参数依据仍是 researcher-defined、uncalibrated，不升级为独立 venue/observer feed latency 或历史相容解释。

## 1. 配对前先重验完整证据

`compare_scenario_runs(baseline_run_id, scenario_run_id, *, split, ledger_factory, registry_factory, datasets_factory) -> ScenarioComparison` 先拒绝非 development 请求，再检查两个不同的 SHA-256 run ID；被拒请求不初始化任何仓库。参数位置固定为 baseline 在左、scenario 在右，颠倒输入、两个 baseline、两个 scenario、失败 outcome 或未终结 reservation 都不能冒充完整配对结果。

读取使用现有仓库的只读模式。baseline 路径重验原八角色证据闭包，包括原协议、dataset manifest/raw/normalized/质量报告、reservation/outcome、result、独立 accounting/evaluation。scenario 路径重验持久 intent、reservation/outcome，重新读取原 development，重新派生 view/tape/intent 并重算评价。比较器还校验两份输入关联，不能通过提交自洽的新 hash 绕过原始绑定。

共同条件必须相同：原 protocol、claim revision、原 development manifest 与原 normalized hash、ReplaySpec（包括策略、种子、费用、单位、insert/cancel latency）、engine 身份/版本/semantic、完整 environment。两条运行保留各自不同的 reservation 和 run 身份，必须处于原协议冻结预算内。scenario 的来源必须就是该 baseline 绑定的原数据；派生只允许声明的接收时间后缀变化。

这是受控干预关联，报告明确 `controlled_intervention=true`、`strictly_paired=false`。派生 view 不会因为零延迟就冒充原 catalog dataset；其身份始终绑定 assumption/scenario。原 [ReplayComparison](../../src/tickwitness/domain/replay/comparison.py) 对不同 dataset/spec/environment 的 strictly-paired 判定不被放宽，原始 condition differences 仍保留。

## 2. 不可变报告及绑定

领域入口为 `ScenarioComparison(protocol, source_input, view, baseline_receipt, scenario_receipt, baseline_result, scenario_result)`。它输出规范 JSON，`comparison_id = SHA256(canonical_bytes)`；`document` 每次返回独立副本，调用方不能修改报告身份。kind 为 `scenario_comparison_v1`，schema version 为 1。

主要字段为：

| 字段 | 含义 |
| --- | --- |
| `controlled_intervention` / `strictly_paired` | 本模型下来源关联成立，但输入为声明的派生干预，不能伪称完全相同运行条件 |
| `scope` | development 压力敏感性观察，不签发 baseline claim truth 或搜索结论 |
| `bindings` | 原 protocol/claim/source/spec、assumption/scenario/view/derived hash，以及左右 run/attempt/result/evaluation 身份 |
| `condition_differences` | 保留旧比较器对实际运行条件的差异记录 |
| `numeric_comparison` | 精确指标比较或明确不可比较原因 |
| `trace_comparison` | 原始 trace 首差异、显式业务投影首差异、每通道定位及投影政策 |

报告的哈希绑定实际已提交证据，不认证作者或真实市场来源。比较不重新运行 native；它验证已存结果与来源、账务和声明的一致性，不证明原生撮合曾在外部市场真实发生。

## 3. 精确数值与不可比较状态

`numeric_comparison` 给出 `metric`、`unit`、`status`、`reason`、`baseline_value`、`scenario_value` 和 `delta`。只支持原模型下的 `net_marked_pnl_v1 / USD`。双方必须完整、独立审计可评价，并使用相同 mark 和 fee 定义，才能报告 `status=comparable`；此时 `delta = scenario_value - baseline_value`，使用有理整数计算并输出唯一普通十进制字符串，不依赖 float 或宿主 Decimal 精度。

mark 的原始绝对 native 时间允许按声明平移；估值政策、source_ref、价格与可用数量的定义必须保持一致。费用定义包括冻结费率和实际审计政策，不能把手续费差异从 metric 中删除。金额差异不代表延迟一定使结果变坏，额外压力对该 metric 没有单调性保证。

incomplete、无 fill、费用模型不唯一等状态保留原审计的不可评价语义，报告 `status=not_comparable` 和明确原因，`delta=null`；不能填零伪装无影响。左右两边都不可评价时，确定性地先报告 baseline 不可评价。mark/fee 定义不一致同样不能计算收益差。这里没有 `satisfied`、claim comparator、counterexample 或策略失效字段。

## 4. 原始差异与业务投影分开

`trace_comparison.raw` 比较原始五个 trace 通道及终止状态/完整性；它不会因为时间、生成 ID 或输入接收时间属于允许变化就改写原始证据。`trace_comparison.business` 使用版本化、定址的 projection，避免把预期元数据变化当业务响应。`raw_trace_changed` 和 `business_trace_changed` 分别描述这两类观察。

projection 只移除明确支持位置的 absolute native 时钟、input receive/native 时间，以及 native fill ID。它只在单订单的已知 `order_id` 位置，将值精确对应到该侧 submit decision 的订单角色；account orders 和 pending/open orders 同样保持角色关联。`command_id`、`decision_ref`、kind、ordinal、source_ref、状态、价格、数量、费用和原 event time 均保留。input 的 source_trade_id、native capture ID 和行情 payload 不能因内容含订单 ID 子串而被重写。

原生 cancel rejection 已知模板 `ClientOrderId('<本侧原订单ID>') not found` 可以按完整匹配映射其中订单角色；其他 reason 文本保留。不能递归字符串替换或笼统丢弃 reason。原始 reason 和真实订单 ID 始终保留在 raw evidence 中，投影政策明确说明允许的变换。

两类结果都输出 `first_divergence` 与 `per_channel_first`。每个差异包含 section、JSON Pointer、左右存在标记和值；业务差异同时保留投影前 raw 值，trace 引用保存 channel、ordinal、kind、native_time_ns、source_ref。缺行用 `left_present/right_present` 明示，不把缺行解释成真实 JSON null，也不把通道错位后的值冒充相同事件。

固定报告次序为 input、decision、order、fill、account、execution_status、completeness；每通道按其原 ordinal 比较。这个顺序用于可复现展示，**不是跨通道的全局最早时间或因果关系**，报告固定 `global_earliest_claimed=false`。输入事件引用说明处理/结算步骤，不能仅据此宣称唯一经济根因。

零干预没有业务差异时，业务 first divergence 为 null。全流时间平移可能产生 raw 时间、生成 order ID 和 rejection reason 差异，但业务投影和金额保持相同。反之，金额相同但生命周期或成交路径不同会保留 trace change；不会被金额零差抹除，也不因此叫策略失效。

## 5. CLI 与远端验收

在受支持远端 CPU 环境，从本分支固定 commit 安装后运行：

```sh
tickwitness compare-scenario-runs BASELINE_RUN_ID SCENARIO_RUN_ID --store DATA_ROOT --registry REGISTRY_ROOT --runs RUNS_ROOT --split development
```

使用实际 ID 与现有持久根替换占位符。命令输出 `{comparison_id, ...comparison.document}`，没有 engine 参数、worker 调用或 reserve 步骤。即使原执行预算已经耗尽，也可以重复比较已经提交的相同两条 run，得到相同内容身份。缺失根不因查询自动创建；确认集请求先于任何 IO 拒绝。

对应 [真实 native 集成测试](../../tests/integration/test_scenario_comparison_native.py) 在远端构造已提交基线、零干预、capture 4 起加两秒及全流加两秒的实际 run。后者刻意改变按秒生成的 order ID 和原生 rejection reason，验证投影不会把这些当业务失败。已知撤单竞争应定位到 order 通道中基线后续 fill 的 capture 5 与场景 cancel 的 capture 4，金额差为 +1 USD。另以真实 EOF pending-submit 配对证明：两侧业务投影相同也不能给不可评价结果生成零收益差。

这些测试在运行后才构成证据；native 缺失是显式 optional skip。源码检查、core 测试、安装后 wheel/source-archive smoke 与 Linux/macOS 原生矩阵继续在远端执行，实际结果回填工程状态。独立可搬迁 scenario bundle、搜索、最小反例及跨协议统计试验家族账本仍不属于本契约。
