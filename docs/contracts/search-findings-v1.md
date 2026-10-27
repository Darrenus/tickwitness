# Search Findings v1

状态：S07-03 实现合同，[远端验收已通过](../planning/sprint-07-status.md#s07-03-远端验收记录)，[PR #91](https://github.com/Darrenus/tickwitness/pull/91) 待 owner 接受。基线为 owner 已合并的 [S07-02 / PR #90](https://github.com/Darrenus/tickwitness/pull/90)，merge `935282c415d167bdcc8485569e47e5221e95b4c3`。本轮保持 `0.2.0.dev0`，不发行新版本。

## 新命题与权限

本合同为已冻结 [SearchPlan](search-plan-v1.md) 建立独立的报告权限，不改变原 protocol、scenario receipt、campaign 或 [共同预算](campaign-budgets-v1.md)。旧 scenario 只提供指标观测，其 `claim_evaluated=false` 和 `finding_issued=false` 保持原字节和原含义。

`SearchFindingProtocol` 嵌入完整 plan，从 source claim 仅复制 `metric`、`comparator`、`threshold`、`unit`，构成新的条件 stress 谓词 P(s)。新 `predicate_id` 绑定精确 plan 和独立 scope；它不是原 `claim_revision_id`。本入口不允许另挑指标或有利阈值。Universal 目标是该冻结计划的唯一 `ELIGIBLE` 候选集合在声明的未校准接收后缀压力下满足 P(s)，不是 baseline 真值、baseline 翻转或真实历史收益。

权限 `conditional_stress_search_findings_v1` 明确只支持 development、一维 receive-suffix `COUNTERFACTUAL_STRESS`。有限 grid 或 random proposals 不是连续延迟空间覆盖；未校准压力不产生市场概率、实际新订单执行或未来收益保证。当前不统一所有候选的运行环境，因此 `runtime_environment_not_harmonized`；也不作纯延迟因果归因，`no_delay_only_causal_attribution` 明确保留。冻结可以发生在既有证据之后，因此 `preregistration_verified=false`；它不认证作者、人类领域接受或完整统计 trial-family 历史。

请求精确字段如下，拒绝未知字段、重复键、错误类型和非规范 schema：

```json
{
  "kind": "search_finding_request_v1",
  "schema_version": 1,
  "title": "Conditional receive-delay stress criterion over the frozen candidate plan",
  "authority": "conditional_stress_search_findings_v1"
}
```

## 结论与前提

报告必须从实际 `inspect-bounded-search-campaign` 路径重新校验 source、完整 plan、预算、按序入场、原 reservation／intent／result／outcome 及账务。命令不接收用户提供的 JSON report 作为证据。坏 hash、错误身份、损坏闭包或不匹配 source 仍为校验／存储错误，不能变成一份看似成功的不可评价报告。

| 已重审的事实 | 输出与范围 |
| --- | --- |
| 外层已有终态；至少一个 `COMPLETED`、原始结果已审计、指标 eligible 的候选使 P(s)=false | `COUNTEREXAMPLE_FOUND`，列出 false 见证及其原 attempt／run／result／evaluation 引用；针对冻结有限集合的条件稳健满足失败。后续失败或预算终止不抹去独立成立的 false 见证 |
| 无 false；非空 true 集合；正常完成，或干净的评估数／容量／时间／原 attempt 预算停止；所有入场均完成且后缀未派发 | `NO_COUNTEREXAMPLE_FOUND`，只覆盖精确已审计 subset。原 attempt 耗尽允许最后一个入场为已验证且未消费新槽位的 `BUDGET_EXHAUSTED` |
| 合法证据但零覆盖、无外层终态、失败、INCOMPLETE、未知估值或未决尝试，且无有效 false 见证 | `NOT_EVALUABLE`，`finding_issued=false` 并保留具体原因；不能复用“预算内未发现” |

仅白名单中的 stop reason 不足以得到 NO：存储或时间限额可能在候选内部触发，留下已占槽／未决记录。此时若没有独立 false 见证，必须不可评价。时间预算停止仅在非空全 true 已审计 subset、所有 admission 均 COMPLETED、后缀全为未派发且无在途入场时允许有范围 NO；campaign 运行状态仍为 stopped，且有未评估后缀时 coverage_complete_for_plan=false。未知不是 false，重复与越界拒绝不是已评估通过，空集合也不是一个真结论。

## 覆盖、预算与身份

报告保留完整 proposal journal、生成停止原因、eligible／audited／true／false／unknown／unevaluated ordinals、每个候选的紧凑引用、外层和内层停止状态。`coverage_complete_for_plan` 只针对这一份有限计划；`continuous_delay_space_exhausted=false` 始终不变。预算内前缀的 NO 必须明确显示未评估后缀。

报告 scope 自身携带 finding protocol、plan、source protocol／claim revision、predicate、campaign budget 身份，以及 eligible／evaluated 候选的 exact ordinal 与 scenario ID 配对；单独展示 scope 时也不会丢失评价子集或混同其它命题。

`conclusion_target` 进一步区分有限计划的条件稳健满足反例与“精确已审计 subset 内无 false”。`planned_predicate_truth` 在 CE 时为 false，只有完整计划全部可评价且全 true 时才为 true；预算前缀 NO 与 NOT 都保持 null，不能把已审计 subset 的 true 升格成整份未完成计划为真。

原预算字段只保存冻结原协议 limits 和实际候选 attempt 引用；不能根据本 campaign 猜测原协议全部历史消耗或停止当时剩余额度。另列冻结 campaign budget、入场记录、预留容量和已记录 elapsed 值。报告不会重计历史时限、退款、扩预算或启动重放。

纯领域报告含独立权限、紧凑事实投影和实际 bounded snapshot 的 canonical SHA-256，能够重算结论与身份，但不单靠自报内容证明真实来源。应用只有从实际 source／ledger 重新建立证据链后才返回 `finalization_status=LOCAL_REAUDITED` 及其核验旗标。报告不写入 runs；派生到 stdout 的内容不冒充已经完成 S08 的可迁移 sealed search evidence、签名、历史账本承诺或独立离线 FINAL。

## CLI 与读取边界

```sh
tickwitness freeze-search-finding-protocol PLAN_ID search-finding-request.json \
  --input-root examples --plans plans --finding-registry finding-registry

tickwitness inspect-search-finding-protocol FINDING_PROTOCOL_ID \
  --finding-registry finding-registry

tickwitness evaluate-search-findings FINDING_PROTOCOL_ID \
  --plans plans --store data --registry registry --runs runs \
  --finding-registry finding-registry
```

三条命令在 ID、输入与 repository 初始化前拒绝 confirmation。Freeze 只读取冻结 plan 并发布独立 authority，不读取行情或 execution ledger；独立 namespace 使用有界 no-follow 常规文件、原子 no-replace 与 fsync。Inspect 不创建缺失根。

Evaluate 只读 authority、原 source 和 bounded campaign，成功重审的三类输出均以退出0返回机器可读回执；退出0不等于谓词成立。校验／存储／缺失错误继续用2／3／4，confirmation为5。报告流程不导入 native、不构造 worker、不联网、不占 attempt、不发布或补写任何 campaign 状态；重复命令必须得到同一报告且文件字节树不变。

## 验收门

固定正／反／未知 oracle、Decimal 比较边界、新旧权限隔离、预算停止前缀与失败／未决互斥、false 见证保留、零覆盖拒绝、坏 source 不洗白、authority／report 字段及 hash 全量重算攻击、并发幂等与 no-overwrite 都需覆盖。安装验收使用前序真实 native 结果，加上执行前独立冻结 −3 USD criterion 的合成控制组，不能在看到结果后通过新 finding 请求改变阈值。

Core-only guard 禁止 native／worker／network／ledger、campaign 和 authority 写入口后重审；source、原协议和原 slots 字节树不变。六核心环境、两原生平台、实际 wheel 和实际 tar.gz 中脚本／样例的安装闭环均在远端验证。报告及原创合成记录保留30天。未执行的检查不记为通过；真实访谈、采用、工时和独立人类领域复核仍需独立证据。
