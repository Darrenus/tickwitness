# Tagged Findings v1：冻结权限后签发有限条件结论

状态：S06-02d 实现切片，远端验收待完成；基线为 owner 已合并的 [PR #86](https://github.com/Darrenus/tickwitness/pull/86)，merge `62fc66b563528fcd03713ec8597ddb66e4d9c870`。本合同承接 [Tagged Pair Evidence v1](tagged-pair-evidence-v1.md)，决策见 [ADR 0020](../adr/0020-frozen-tagged-finding-authority.md)，实际验收维护于 [Sprint 6](../planning/sprint-06-status.md)。

本切片为已封存的有限 tagged reconstruction 增加独立报告权限。原 `TaggedQueueProtocol`、单次 run、十二角色 assessment 的 `finding_issued=false` 保持原字节；不能以改字段、重命名旧包或编辑已有结果取得新权限。新权限只评价被绑定的新 tagged claim，不评价 source v2 的原命题，不延长执行权限或重放预算。

## 冻结明确的报告问题

新请求只接受以下 exact 字段，示例见 [tagged-finding-request.json](../../examples/tagged-finding-request.json)：

```json
{
  "kind": "tagged_finding_request_v1",
  "schema_version": 1,
  "title": "Conditional tagged inventory findings over the two frozen policies",
  "authority": "conditional_tagged_findings_v1"
}
```

title 是最多200字符的非空受限文本。authority 固定，不能选择有利的 finding 类型、修改 claim comparator／threshold、放宽模型或跳过必要见证。未知／重复字段、bool 冒充整数、float、非 canonical 合同、来源身份或类型不符均拒绝。

`freeze-tagged-finding-protocol` 从既有 tagged registry 读取完整 subject protocol，冻结新的 `tagged_finding_protocol_v1`。合同包含完整 subject、subject／claim／dataset／normalized／source／gross／ReplaySpec 身份、两项固定 policy、权限、证据政策、报告政策、固定真值映射、scope 和限制。`finding_protocol_id=SHA256(canonical bytes)`；内容变化产生新身份，重复冻结相同内容不覆盖且返回相同身份。

权限明确区分两个问题。`truth_target=frozen_predicate_per_hidden_allocation_v1` 表示冻结谓词在隐藏分配 w 下的真值 P(w)，其识别检验为 `opposite_truth_witnesses_same_public_projection_v1`。`counterexample_quantifier=for_all_listed_policy_witnesses_v1` 则定义已列集合 S 上的稳健满足要求 U_S=∀w∈S P(w)。两个相反真值见证说明 P(w) 不能由这些公开观测唯一确定，同时已经使 U_S 为 false；不能再把这个已确定为 false 的全称聚合命题叫作“不可识别”。

评价对象是同一份观测、同一 gross 声明及明确 protected-tagged 模型下列出的两份见证，不是全部隐含队列世界、全部数据集或未来市场。gross 流仍是研究者声明且未校准；公开投影仍排除模拟 private fills 和 horizon 后清理，未验证真实 private execution observations。

冻结只读既有 subject，写入独立 `tagged-finding-protocols` namespace；不查询行情、不访问确认集、不调用 native、不占 attempt。它允许对既有开发证据建立确定性报告规则，**不证明该规则曾在看数据前预注册**，也不是人类领域审批或作者签名。

## 签发前提与 finding 映射

签发只接受完整、重新审计通过且在同一实际 execution environment 下的两个布尔真值。完整 source pair 需要两种政策各一份真实完成回执、不同 attempt ID 与预算 index、相同完整 subject／claim／观测／约束，且原生回调、守恒、账务、估值和 assessment 都从封存 raw 重新复现。

| 冻结谓词真值 | 允许的 finding | 目标、见证与范围 |
| --- | --- | --- |
| F/F | `COUNTEREXAMPLE_FOUND` | 针对 U_S，附两份 false 见证，已列集合的稳健满足要求失败 |
| T/F 或 F/T | `NOT_IDENTIFIABLE_WITHIN_MODEL` 与 `COUNTEREXAMPLE_FOUND` | 前者针对 P(w) 的识别，附同观测下的两个相反真值见证；后者针对 U_S，只附 false 见证 |
| T/T | `NO_COUNTEREXAMPLE_FOUND` | 针对已列集合的稳健满足检查，附两份 true 见证，仅覆盖已完成的两项 policy |

每项 finding 有明确 `conclusion_target`：NOTID 为 `per_interpretation_predicate_truth_given_public_observations_v1`，COUNTER／NO_COUNTER 为 `robust_satisfaction_across_listed_witnesses_v1`。同一 scope 不会同时出现 COUNTEREXAMPLE 与 NO_COUNTEREXAMPLE。`NOT_IDENTIFIABLE_WITHIN_MODEL` 是在上述明确条件模型和新命题内的存在性见证，不宣称真实历史订单所有权、真实新插单、无市场冲击或市场整体不可研究。条件反例也不是对真实历史实现收益的否定。

`NO_COUNTEREXAMPLE_FOUND` 不代表穷尽所有 admissible hidden allocations，也不是收益稳健性、实际清算能力或未来回报保证。`completeness` 同时列 planned／audited／eligible policy IDs，固定 `coverage_complete_for_listed_policies=true`、`admissible_world_space_exhausted=false`、`full_attempt_history_available=false`，并列出未探索范围。

费用歧义或环境不一致的 source pair 可以保留有效的十二角色审计，但不满足这份严格报告权限。此时退出9，错误码 `tagged_finding_ineligible`，保留原因与 source pair ID，不发布十四角色报告目录。原有证据和每份 run 的实际真值不修改；不能将未知变为 false、将其包装成反例，或用一个新的“证据不足”finding 覆盖已验证记录。本权限不签发 `INSUFFICIENT_EVIDENCE`。

非法、未完成、缺件、篡改、错误模型或不匹配来源是校验错误；不能进入不可识别判定，也不能转成“未找到反例”。

## 命令与读取边界

```sh
tickwitness freeze-tagged-finding-protocol SUBJECT_PROTOCOL_ID tagged-finding-request.json \
  --input-root /path/to/requests --registry /path/to/registry

tickwitness inspect-tagged-finding-protocol FINDING_PROTOCOL_ID \
  --registry /path/to/registry

tickwitness issue-tagged-findings FINDING_PROTOCOL_ID /path/to/sealed-pair \
  --expected-bundle-id SOURCE_PAIR_BUNDLE_ID --registry /path/to/registry \
  --output /path/to/new-finding-report

tickwitness verify-tagged-findings /path/to/relocated-finding-report \
  --expected-bundle-id FINDING_BUNDLE_ID
```

所有命令默认 `--split development`；confirmation 在 ID、文件与 repository 初始化前拒绝。issue 必须显式提供原十二角色 source pair 的 expected ID，防止调用时静默换包；该 pin 需从可信渠道取得，自算 hash 不认证作者。verify 的 expected ID 为可选项，对比的是最终十四角色包。

issue 只读指定 finding registry 和固定 source pair，不读取原 data／ledger，不调用 native 或 worker，不消耗预算。它先重新验证完整源包，再检查 source 与冻结 subject 完全相同，确定性生成报告并发布新目录。已有输出即使同内容或为空也不覆盖；重复签发相同字节到新目录产生相同身份。错误 exporter 返回另一份合法报告亦不应被当成请求成功。

verify 只需 core 安装，不要求 finding registry、原 source pair 目录、原 store／ledger、native、数据库或网络。它从最终包的十二角色子集重建 source pair manifest ID，重新审计其内容、加载独立权限，重建 finding report，逐字节一致才放行。单独加载一份看似自洽的报告不能代替这一步。

## 十四角色包与报告身份

新 envelope 为 `kind=tagged_finding_evidence_bundle_v1`、`schema_version=1`、`scope=development_conditional_tagged_findings_v1`。固定目录仍为 `manifest.json` 与 `objects/sha256/<digest>`。它恰好包含旧 source pair 的十二角色，加上：

| 新 role | 上限 | 内容 |
| --- | ---: | --- |
| `finding_protocol` | 512 KiB | 独立冻结的权限及完整 subject |
| `finding_report` | 512 KiB | 确定性报告、scope、见证引用、coverage 与限制 |

其余 role 上限延续 [十二角色合同](tagged-pair-evidence-v1.md)。默认总量64 MiB、32文件、manifest64 KiB；相同内容共享 CAS。新十四角色、旧十二角色和 baseline 八角色 reader 相互拒绝，不放宽旧 kind。

IO 继续采用 no-follow、有界 regular-file 读取、严格固定树、fsync 与原子 no-replace 发布。隐藏／未知／缺件／symlink／FIFO、大小／总量／文件数超限、重复 JSON key、错误 ref 或 hash 都拒绝。发布前故障不留下有效目标；rename 后 parent fsync 失败保留完整目标并报告持久性未知，不承诺可安全覆盖重试或真实断电认证。

`tagged_finding_report_v1` 绑定完整 finding protocol、其身份、subject／claim、source pair ID、完整 assessment 及其身份、十二角色内容 hash、scope、`execution_status`、`findings[]`、`completeness` 与限制。每份 finding 带明确 conclusion_target、相同受限 scope 和按冻结 policy 顺序排列的 witness：policy／run／attempt／index／intent／result／evaluation／truth 皆可沿封存内容复核。

pure domain 报告只声明 source `CONTENT_CLOSED`，publication 为 `UNASSERTED`。应用只有在完整十四角色闭包发布并复核，或从该闭包独立读回复核后，才返回 `finalization_status=FINAL`，依据固定为 `sealed_finding_evidence_content_v1`。这里的 FINAL 表示内容闭包与规则重算完成，不认证原始发布、作者、审批者或断电持久性；包仍可能被复制到另一目录。

回执固定 `integrity_verified`、`bindings_verified`、`source_revalidated`、`queue_execution_audited`、`findings_recomputed` 为 true；`native_replayed`、`author_signature_verified`、`human_domain_approval_verified`、`original_publication_verified`、`confirmation_reference_checked`、`full_attempt_ledger_checked`、`ledger_commitment_checked` 均为 false。不存在完整历史或已获人类审批的隐含承诺。

## 验收要求与未完成范围

本切片预设四种真值分支 oracle、严格权限／身份／布尔类型、未知拒签、坏证据不得变 finding、十四角色全量 hash 重算攻击、原权限和 source pair 不变、跨格式互拒、无覆盖／并发／持久性故障，以及删除 issuer source pair／authority registry 后的 core-only 复核。安装验收使用前序流程真实 native 产生的四份配对及保留的历史记录，报告流程自身不启动新 engine。实际 wheel、实际 sdist 脚本及两原生平台后的 core 报告链路均须在远端验证，报告和实际十四角色包保留30天。

新原生安装验收另增加独立冻结的 bid100／ge0 案例，预设 P(front)=false、P(back)=true，反例见证应只引用 front。它与既有 F/F、T/F、T/T 一起覆盖四种真值方向；core 历史 golden 仍保留原两案。此处规则和案例是运行前确定的要求，不代替远端结果。外部人类领域复核、真实市场／采用证据、确认集 lifecycle、跨协议完整 trial 账本、报告撤回／更正 lifecycle 与任何更广的统计推断仍需后续验收。没有新增这些证据时不补造工时、访谈、性能或采用数字。
