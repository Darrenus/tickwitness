# Queue Semantics Qualification v1

状态：S06-02a 的语义资格切片；远端验证与 owner 审阅中。承接已接受的 [Queue Family v1](queue-family-v1.md)，不修改旧族、旧评价器、budget 或 finding 合同。

## 三种对象与两个门

一条外部行情路径、加入自身订单的交易世界，以及外部路径上的 shadow fill 功能值，是不同的模型对象。`queue_source_grant_margin_audit_v1` 验证按声明模型执行及记账正确，不证明自身成交与真实市场的观测投影相容。

本切片分开验证两件事：在明确投影下逐条核对数量关系；在明确且仅用于资格实验的谓词政策下验证真假比较。它们不能互相替代，两个模型输出不同也不能绕过任一门。

### 外部投影

固定前／后撤单解释满足声明的 gross flows、非负、FIFO 与目标 checkpoint 对账，证明的是该受限外部队列在声明条件下投影回同一份外部观测。gross additions/cancellations 仍然是研究者条件，不因为可行而成为已观测事实；这不是所有价格、事件或隐藏流动性的完整历史证明。

### 单次分配的插单诊断

另固定一个具体的必要条件投影：目标 bid 深度只表示外部订单，公共 trade 的总量在 external 与 own 间只分配一次，保持同一份明示 gross 增撤单。此时：

```text
external_after_recorded = external_before + adds − cancels − trade
external_after_inserted = external_before + adds − cancels − (trade − own_fill)
candidate_checkpoint_residual = cumulative_own_fill
```

当前 shadow 模型已从 external 扣整笔 trade，再额外产生 own fill。标准 front 在 trade 前 ahead=2、behind=3；trade=3、own fill=1。将它们解释为同一笔真实 trade 会分配 4 lots，而公共成交只有 3；候选插单世界的外部剩余为 3，源 checkpoint 为 2。back own fill=0 时没有这个残差。

诊断 `literal_order_insertion_single_counted_trade_v1` 报告逐 trade 的 public/external/own/total/over-allocation 和各 checkpoint 的累计 own fill 残差。正残差得到 `contradiction`，没有残差只得到 `necessary_checks_passed`。它是对上述指定投影的必要数量检查，**不排除所有 ghost/paired-world 模型，也不证明无残差者有完整相容世界**。订单干预、队列变化、真实市场反应与时钟的其他条件仍未证明。

## 用户数据的只读配对入口

```text
qualify-queue-pair RUN_A RUN_B --families FAMILY_ROOT --store DATA_ROOT --runs RUN_ROOT
```

只接受两份不同的、已提交的 queue run，政策集合恰为 front/back。应用先拒绝 confirmation、坏 ID 和相同 run；再重验实际 development store、不可变族、reservation／intent／receipt／CAS 闭包与独立执行审计。两个 run 必须属于相同完整族、原始规范化字节、数据／spec／constraint 和 engine/environment。不同 attempt/index，输出固定 front/back 顺序，因此调换命令参数得到同一报告。

报告 `queue_pair_semantics_v1` 绑定全部共同条件、两 result/evaluation hash 与来源 claim revision。`qualification_id` 为 canonical domain document 的 SHA-256；应用另附 committed run/attempt 引用与重验状态，并用 `inspection_id` 绑定包含这些引用的完整输出。它不调用 engine、不 reserve/bind/publish，也不改变源、预算或工件。缺根是缺证错误，不创建空目录。坏输入、未完成结果、跨族、重复 policy、环境改变及篡改是 typed error，不包装成“未发现分歧”。

现有族对 source claim 仅保留 lineage，且 scope 明确禁止 claim verdict。因此本命令固定：

```text
observation_compatibility.status = not_established
predicate.status = not_evaluable
predicate.reason = queue_family_claim_lineage_only
predicate.values = {cancel_front_first_v1: null, cancel_back_first_v1: null}
predicate.satisfied = {cancel_front_first_v1: null, cancel_back_first_v1: null}
predicate.truth_divergence = null
scope.scenario_kind = MODEL_SENSITIVITY
scope.source_claim_evaluated = false
scope.claim_verdict_issued = false
scope.finding_issued = false
findings = []
```

调用方不能上传 `proof=true`、已相容标签或布尔真值来覆盖这些结果。两份数值／成交不同不改变上述权限。

## 固定资格实验中的候选谓词

`queue_qualification_predicate_v1` 是独立的 canonical、内容寻址合同。其 exact fields 为 kind、schema_version、purpose=`semantic_qualification_only`、metric=`net_marked_pnl_v1`、unit=`USD`、comparator=`gt/ge/lt/le`、有界 canonical decimal threshold 和 evaluation_policy=`qualification_flat_zero_last_visible_bid_v1`。未知字段、bool 数字、重复字段、非有限数或其他政策拒绝。

候选政策明确仅在已完成且执行审计通过时，按实际成交的价格／数量增量和实际费用，采用源路径最后可见 best bid 进行精确有理数标记：

```text
diagnostic_net_marked_value = filled_physical_quantity × final_best_bid
                              − actual_fill_notional − actual_commission
```

这是未平仓的模型标记值，不是实际清算收益。native 费率量化歧义导致不可评价；失败或缺结果不能填零。完整终态、零成交、零仓位且零费用仅在这个显式候选 flat-zero 政策中得到值 0；旧评价器的 `no_fills` 规则保持原状。候选 predicate 在固定资格案例首次 engine 调用前构建并记录，不能拿看过结果后改的阈值冒充事先冻结的研究命题。

候选 observation 重新核对真实源、原生执行审计及完整 predicate 身份，计算值和 bool；配对必须同 predicate、完整族与共同来源，恰为两政策。诊断 pair relation 只有 `DIAGNOSTIC_PREDICATE_AGREEMENT`、`DIAGNOSTIC_PREDICATE_DISAGREEMENT`、`DIAGNOSTIC_PREDICATE_NOT_EVALUABLE`，不产生生产 finding。生产 CLI 不接收这个候选政策，也不借它评估 source claim。

| 固定资格 oracle | front / back 值 | 比较 | 预期 |
| --- | --- | --- | --- |
| 原样例最终 best bid=100 | −1 / 0 | `gt 0` | false / false |
| 独立样例最终加入 best bid=102 | +1 / 0 | `gt 0` | true / false，仅诊断分歧 |
| 同一 102 样例 | +1 / 0 | `ge 0` | true / true |
| 原样例 | −1 / 0 | `gt -2` | true / true，数值不同不等于真假不同 |
| 空仓等号边界 | 0 | `gt 0` / `ge 0` / `lt 0` / `le 0` | false / true / false / true |

## 后续实际 finding 门

两见证必须在共同、执行前冻结的 queue claim／evaluation policy、observation projection、干预／impact 合同与全部约束下独立验证，并有相反的 eligible 真值，才有条件进入不可识别见证判定。无效／不支持／失败／未完成／缺证都不等于 false。同真值 pair 只能说明所查 pair 无翻转，不能证明整个模型集合已识别或穷举无反例。

现有 DDD 的最终 finding 还要求封存证据及相应状态流程。本资格切片没有签发 `NOT_IDENTIFIABLE_WITHIN_MODEL`、`COUNTEREXAMPLE_FOUND`、`NO_COUNTEREXAMPLE_FOUND` 或 `INSUFFICIENT_EVIDENCE`，没有新增统计评分、置信区间、搜索覆盖或现实盈利结论。
