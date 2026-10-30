# Reduction Input v1

状态：S09-01a 已完成[远端实现验收](../planning/sprint-09-status.md#s09-01a-远端验收记录)，owner 已合并 [PR #95](https://github.com/Darrenus/tickwitness/pull/95) 接受，merge `a2c711861d1d776c78b4b5f5471f8afa388d390f`。决策见 [ADR 0028](../adr/0028-valid-prefix-reduction-inputs.md)。本格式只准备 development 回放输入；[S09-01 / #25](https://github.com/Darrenus/tickwitness/issues/25) 的[S09-01b真实执行与状态投影审计](reduction-execution-v1.md)另有新意图／回执，不能把准备包当成执行结果。即使同一准备包随后被执行，其immutable flags仍不改写。[#24](https://github.com/Darrenus/tickwitness/issues/24) 的外部尝试继续为 `0 / PENDING`，不采集或补造外部记录。

## 1. 已认证源与合法算子

输入是完整的 [Search Evidence v1](search-evidence-v1.md) 包、明确的 expected bundle/report IDs 和一份严格请求。应用先独立重审完整原证据，再选择实际 `COMPLETED`、原始结果已审计且谓词为 false 的 witness。完整 clean control、未审计结果、失败或未完成 attempt 不能作为缩减见证。只接受 development split；confirmation 在接触包、ID 或工厂之前拒绝。

严格 request document：

```json
{
  "kind": "reduction_request_v1",
  "schema_version": 1,
  "witness_ordinal": 3,
  "focus_from_capture_seq": 4,
  "through_capture_seq": 6,
  "additional_delay_ns": 1000000000
}
```

所有字段必须且只能出现一次；ordinal 和 capture 是大于等于1的整数，delay 是大于等于0的整数，bool 不能冒充整数。未知字段、重复 key、状态注入、checkpoint、策略／seed 修改均拒绝。结构安全检查先于任何包属性访问。

| 算子 | 允许范围与实际作用 |
| --- | --- |
| `focus_from_capture_seq` | 必须是真实原始 capture，位于源起点与 retained end 之间；只设置审阅边界，前面的 warmup 事件仍全部保留 |
| `through_capture_seq` | 必须是真实原始 capture；只保留原始首条 snapshot 起到该点的完整连续前缀，并保留原策略 submit capture 和情景 transform anchor |
| `additional_delay_ns` | 不大于选中 witness 的原延迟，且仍在原冻结假设范围；重建完整候选 scenario 后再截取前缀，不能只修改焦点窗口中的时钟 |

完整长度、原始延迟的 no-op 合法；`strictly_shorter_input` 和 `parameter_contracted` 反映实际变化，不能一概写 true。禁止删除中间 delta 或 trade、排序／重编号、替换初始 snapshot、重置账户／策略／队列或导入 checkpoint。延迟变化不蕴含收益单调性，也不产生最小失效阈值。

## 2. 前缀与身份

先从完整原始数据、原始 `ExecutableProtocol`／`ReplaySpec`／`AssumptionSpec` 和新候选 `ScenarioSpec` 调用既有 `derive_replay_view`；再按原始 capture 保留 exact 前 N 条 normalized JSONL bytes。逐字节保留事件编码、换行、顺序和原始 capture／line 引用。以原 replay spec 对保留输入执行 native-free preflight；不得把截短数据套回原 dataset/view ID。

`recipe.json` 绑定完整 source bundle/report、protocol/finding/claim/predicate/run、assumptions/scenario、dataset/normalized hash/spec identities、witness ordinal 及三项明确算子。`materialization.json` 绑定 recipe ID、`prefix_context_id`、完整候选 scenario/view/hash、保留前缀及 warmup 的 hash/count、source/focus/end refs 和原 engine/specification semantics。Descriptor 是计划输入上下文的身份，不是运行中的引擎状态。任何源语义或影响前缀的情景变化都需要重新计算绑定，不能凭相同原始数据和 cursor 复用旧状态。

例如真实7条语料的 focus=4、through=6，实际输入为1..6，warmup 为1..3；不是只执行4..6。cap3 已可能产生部分成交、手续费、持仓和在途撤单。L2 snapshot 不含这些完整状态。当前 adapter 无 `CHECKPOINT` capability；队列模型里名为 checkpoint 的观测点也不是可恢复状态。

## 3. 包与界限

exact physical tree：

```text
manifest.json
recipe.json
materialization.json
normalized.jsonl
```

Manifest exact 顶层为 `kind="reduction_preparation_bundle_v1"`、`schema_version=1`、`scope="development_input_preparation_only_v1"` 和 `roles`。三项 role 为 `recipe`、`materialization`、`normalized`，各自只有 `sha256`、`size_bytes`、`ref`，固定 refs 对应上述文件名。`preparation_id` 是 canonical manifest bytes 的 SHA-256，不写入自身形成循环。Manifest、recipe 和 materialization 必须为 exact canonical JSON。

Recipe 上限64KiB、materialization 上限128KiB、normalized 上限8MiB，整个包上限16MiB。只接受完整 exact tree 和有界 regular files；FD-relative no-follow 读取拒绝符号链接、FIFO、额外文件、路径别名或不安全对象。不裁掉超限后缀。

发布目标必须是 input root 和 source bundle 之外的新目录，不覆盖或 repair。完整 staged bytes 同步后原子发布，再同步 parent。提交前失败不返回成功；提交后 parent sync 不确定保留已发布目录并报 `BundleDurabilityError`，不能将内容可读等同于已确认持久性。具体故障与并发边界由远端 IO 测试验证。

## 4. 应用与 CLI

`prepare_reduction_input(package, request_raw, expected_bundle_id=..., expected_report_id=..., split="development")` 返回 immutable `PreparedReduction`；`.artifacts` exact 为 `recipe`、`materialization`、`normalized`，`.preparation_id` 来自 canonical manifest。`verify_reduction_input(package, source=..., expected_preparation_id=..., split="development")` 从完整源重建所有角色，再与保存内容比较；只校 hash 或相信 flags 不足以通过。

```sh
tickwitness prepare-reduction-input SOURCE REQUEST.json --input-root ROOT \
  --expected-bundle-id BUNDLE_ID --expected-report-id REPORT_ID --output NEW_PREPARATION
tickwitness verify-reduction-input PREPARATION --input-root ROOT \
  --source-evidence SOURCE --expected-preparation-id PREPARATION_ID
```

SOURCE 相对 input root；PREPARATION 可以移动到 input root 外的独立位置，使用其自身安全根读取。input root 仍约束源证据与发布排除边界。显式传 `--split confirmation` 在 IO 前拒绝。没有 ledger／registry／SQLite／native 参数，也不恢复原研究预算。

成功回执包含 `preparation_id`、`source_bundle_id`、`source_report_id`、`recipe_id`、`prefix_context_id`、`event_count`、`warmup_event_count`。保存后重验的状态为 `RECOMPUTED_PREPARATION_ONLY`；prepare CLI 实际保存并重验成功后输出 `PREPARED_INPUT_ONLY`。

Descriptor 与回执明确固定：

| 字段 | 值 |
| --- | --- |
| `requires_full_prefix_replay` | true |
| `checkpoint_supported`、`checkpoint_used`、`initial_state_materialized` | false |
| `native_replayed`、`attempt_reserved`、`reduced_predicate_evaluated` | false |
| `witness_preservation_verified`、`checkpoint_resume_verified` | false |

没有缩减后 EOF／pending-order／收益结论、状态已生成或反例仍成立的声明。本切片不做自动寻找候选、预算受控缩减循环、最小性或发行授权。

## 5. 真实安装验收

复用已提交的 `examples/alpha/counterexample` 与 `clean-control` 完整证据，不再执行原研究、不创建或更新原 ledger。CE source bundle pin 为 `2261f5c82bf19d3f088ecd64fed131ae71635d686a4a4a4b1a8e9e6c43c78369`，report pin 为 `398ead2cd2ed7db4f4ba69a1cd3e4dd4acc6ae9d80abd7897307ca94d4af75bb`；ordinal3 原延迟2e9ns、7events。Clean control 使用原完整 true 证据，必须拒绝作为 false witness。

Installed core smoke 验收 no-op、focus4/through6/warmup1..3、delay1e9 重绑定、非法端点／锚点／checkpoint、原始 hash 篡改与重哈希后的语义篡改拒绝，以及移动源和 preparation 后的相同复算结果。Guard 禁 native、网络、SQLite、原 stores、attempt reservation 与研究 worker；准备和重验保持源字节树不变。确认 split 和不安全 request 另以 pre-IO tripwire 检查，不把输出声明当权限防护。

Smoke 保存实际 runtime interpreter identity、请求、包、回执与失败诊断，目录内成功报告唯一为 `reduction-input-smoke/report.json`，并向显式 `--report` 路径写出相同字节。异常保留诊断并继续失败，不写 accepted 报告。全部 runtime、安装、测试、构建和格式化在远端执行；实际head／artifact见上述验收记录。后续 S09-01b 需要真实完整前缀重放和有效状态证明，S09-02 另验预算与结论保持。
