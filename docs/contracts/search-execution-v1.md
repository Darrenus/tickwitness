# Search Execution v1

状态：Accepted；S07-01b [远端验收已通过](../planning/sprint-07-status.md#s07-01b-远端验收记录)，owner 已合并 [PR #89](https://github.com/Darrenus/tickwitness/pull/89)，S07-01／[#19](https://github.com/Darrenus/tickwitness/issues/19) 已在此受限 profile 范围接受并关闭。实施时基线为 owner 已合并的 [S07-01a / PR #88](https://github.com/Darrenus/tickwitness/pull/88)，merge `373d08a5c2196662c5116e02ea7b7fe3a98dc167`；该切片未发行新版本。

## 用途与边界

本合同把一份已冻结且实际来源可重验的 [SearchPlan](search-plan-v1.md) 交给顺序协调器，依 journal 次序自动执行唯一 `ELIGIBLE` 候选，并把每个候选与原协议中的真实 reservation、intent、result 和 outcome 持久关联。`DUPLICATE` 与 `REJECTED` 继续保留在 proposal journal，不能虚构一次执行或被当作已评估通过。

只支持既有 development-only、固定 anchor、一维 `replay_receive_suffix_shift_v1` 的未校准 `COUNTERFACTUAL_STRESS`。它沿用 [Scenario Execution v1](scenario-execution-v1.md) 已资格化的耦合市场／策略 receive 时钟，不声称模拟独立网络延迟、真实历史接收过程或观测相容世界。

本切片交付执行与尝试关联，不签研究 finding，不评价原 baseline claim，也不把遍历完有限候选称为稳健证明。S07-02 的 campaign 总时间／存储硬限额、S07-03 的搜索结论、S08 确认集 lifecycle、S10 自动恢复／取消和完整统计 trial-family 账本仍需独立验收。原逐次执行 deadline、event 限额和共同 attempt budget 继续生效；这不等于已实现 campaign 总资源控制。

## 身份、顺序与共同预算

一个 campaign 嵌入完整冻结 plan，绑定 plan ID、原 `ExecutableProtocol v2`、新 campaign nonce 与版本化顺序执行政策。计划中的 search seed 不改变原 `ReplaySpec.seed`；campaign 不成为新的预算 owner。

每次实际候选执行都在原 protocol 的 `LocalAttemptLedger` 占用一个不可退款槽。此前的 baseline、手动 scenario、其它 plan 或失败／未决尝试占用的槽继续计入同一预算；不得克隆协议、按 plan 重置预算或将重复执行伪装成免费缓存命中。不同 plan 可以竞争余下槽，槽位占用以原 ledger 的原子提交为准，不能根据较早的预算快照假定仍有容量。

同一 plan 在同一 runs 根下只建立一次 campaign。POSIX 非阻塞排他锁阻止同 plan 的两个协调器同时执行；已有 campaign 再次收到运行命令时取得协调锁后，以只读 ledger 复核其已记录状态，不自动重放、补跑后缀或恢复未决尝试。检查无需引擎或 GPU。更广的作业恢复机制仍属 S10；重新运行命令不会退还槽位或消除已发生的结果。

## 执行前的持久关联

每个唯一 eligible 候选遵循以下顺序：

1. 实际重验 source、完整冻结 plan、assumption、candidate identity 及派生 view。
2. 不可变发布 dispatch，绑定 campaign／plan／protocol／proposal ordinal／scenario／预定 reservation nonce 与完整旧格式 `ScenarioIntent`。
3. 使用该已承诺 nonce 在原 protocol 的 slot namespace 中 reserve。原 reservation schema、owner 和预算含义保持不变；相同 named nonce 不能被复用来免费重跑。
4. 持久记录实际 reservation link，然后由既有 scenario 流程提交 intent 与派生制品。引擎构造严格晚于这些写入。
5. 引擎返回后先保存实际 raw result，再进行既有独立场景审计和 outcome 发布。审计失败仍保留已经取得的原始结果；保存原始结果不等于认可其中的账务或完成声明。

Slot link 成功后 fsync 仍可能失败，因此 reserve 抛错不能被解释为未消费。预先冻结的 nonce 允许只读检查在原 protocol 的已提交 slot 前缀中恢复关联；找不到 reservation 时仍保留不确定性并停止，不退款或自动重试。若同 nonce 对应多个已提交 reservation，或者实际 link 与 dispatch／reservation 不一致，应报告完整性错误。

旧 `ScenarioIntent`、`ScenarioRunReceipt` 和 failure 的 `search_performed=false` 等 scope 不改写。Campaign 是外层协调与覆盖记录，不通过修改历史回执扩大旧权限。原 source、protocol、plan 和已有结果不覆盖。

## 状态、停止与拒绝

报告逐个列出 eligible 候选，包括未访问后缀；每行关联实际 attempt／index、outcome／run 与重审评价，缺失值明确为 null。候选状态必须区分：

| 状态 | 证据含义 |
| --- | --- |
| `NOT_DISPATCHED` | 尚无执行 dispatch；不是已经评估或通过 |
| `RESERVATION_UNCONFIRMED` | dispatch 已提交，但未能确认 reserve 返回及原 slot 的完整状态 |
| `BUDGET_EXHAUSTED` | 本次 reserve 已明确预算用尽，未取得新槽；与未知状态分开 |
| `RESERVED_UNFINALIZED` | 已有不可退款 reservation，intent 或 outcome 尚未完整提交，包括中断 |
| `FAILED` | 原 attempt 有已提交 failure；不转为策略亏损或反例 |
| `INCOMPLETE` | 实际运行尚有不完整终态；不等同 completed |
| `COMPLETED` | 已提交成功结果经实际 source／intent／派生／账务重新核对 |

协调器遇到首个失败、不完整、预算耗尽、reservation 或发布不确定性立即停止。后缀仍列为未 dispatch，不继续尝试掩盖失败。`planned_candidates_exhausted` 仅表示这份有限计划中 eligible 候选的执行已结束，不表示连续延迟空间穷尽、真实市场概率、命题成立或未发现反例。没有 eligible 候选时可以记录 `no_eligible_candidates`，仍不产生 search finding。

停止记录保存协调器的终止原因及错误诊断；独立检查不只相信这个记录。Outcome 发布的返回路径可能报错但实际文件已经提交，检查应重审已提交的真实内容并保留原协调器错误，不自动将成功改成失败，也不发起第二次执行。进程直接中断可能来不及写停止记录；检查必须显示未决事实，不能补写终态或伪报成功。

## 存储与只读复核

执行记录位于原 `--runs` 根内独立的 `search-campaigns/<plan_id>/` namespace，包含 campaign、dispatch、reservation link、取得的 raw result 与停止记录。原 attempt ledger 仍拥有 reservation／intent／outcome。命名和文件大小有固定上限；POSIX no-follow、nonblocking 常规文件检查和原子 no-replace 发布保护读取及证据保存。提交后的同步错误保留可观察文件，不能自动覆盖修复。根及父路径是可信本地配置，不是访问控制或恶意宿主沙箱。

检查从实际 development source 重新构造 plan 与每个 dispatch 的 ScenarioIntent，核对 nonce、完整 reservation、原 slot、原 committed intent/outcome，以及 raw result 与结果绑定。成功结果沿用 `scenario_run_evidence` 的来源、派生及账务重审；失败 outcome 核对其原始 intent 和 reservation。只有成功经过实际场景审计的结果才有 `raw_result_audited=true`；失败时保留的 result 只是诊断，hash 不认证其账务或来自哪次物理调用。顶层 `outcomes_reaudited` 表示已重验可见 receipt／failure 的引用和绑定，不替未通过审计的 raw result 背书。未知、缺失、损坏或多个冲突关联不变成零成本、通过或 finding。

只读检查不构造 worker、不 reserve、不发布、不修复原文件，不需要 optional native extra。它只验证所引用内容和当前可见 ledger 前缀，不认证完整尝试历史、作者身份、数字签名、人类领域批准、原始断电耐久性或确认集隔离。该目录也不是新增的可迁移离线 source evidence 包；复核仍需要原数据、protocol、plan 和 runs 闭包。

## CLI

```sh
tickwitness run-search-plan PLAN_ID \
  --plans plans --store data --registry registry --runs runs

tickwitness inspect-search-campaign PLAN_ID \
  --plans plans --store data --registry registry --runs runs
```

两条命令均先拒绝 `--split confirmation`，再处理 ID、输入和任何 repository factory。坏 plan／source／绑定在建立新 campaign 或 runs 之前拒绝。缺失 runs 的 inspect 不创建目录。`--engine-python` 只在执行命令上选择可信的已安装引擎环境，不改变冻结预算或回放语义。

对于可重审的已记录停止状态，运行命令也保留机器可读 campaign report，并通过非零退出码区分预算、引擎或存储失败；inspect 对可验证的已停止／未决状态返回报告，不重试执行。请依据报告状态和具体错误处理，不能把 JSON 能解析或 inspect 成功当作搜索或研究结论成功。
