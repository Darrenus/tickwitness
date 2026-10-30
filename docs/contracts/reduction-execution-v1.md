# Reduction Execution v1

状态：S09-01b 合同冻结，远端实现验收待完成。基线为 owner 已合并 [PR #97](https://github.com/Darrenus/tickwitness/pull/97)，merge `4e3691cccbe28f76b777814d1bac297082ed13c1`。决策见 [ADR 0029](../adr/0029-origin-prefix-execution.md)，静态准备沿用 [Reduction Input v1](reduction-input-v1.md)。本切片增加从原点实际回放与状态审计，不添加自动缩减、checkpoint 或反例保持结论。真实外部尝试仍 `0 / PENDING`。

## 1. 原始来源与共同预算

执行需要完整 search evidence、合法 preparation 的 expected ID，以及**已存在的原 live ledger**。先独立重审完整来源、原始 completed／audited／false witness 和全部 preparation bytes，再重建原始 `ExecutableProtocol` 与 `MaterializedReduction`。不能把旧包中的声明当成新增额度或绕过 source pins。

打开 ledger 使用 `create=False`。在 reserve 或 engine 构造之前，要求 source snapshot 的 `ledger_prefix_observed=true`，逐字节核对其全部 reservation 前缀和实际收录的候选 intent／outcome／CAS。Live ledger 可以拥有合法新后缀；不能比已观测前缀更短、缺件或替换旧记录。空根、另一份账本、缺少原槽位或错配原结果均拒绝；不从 portable 包导入／补建槽位、CAS 或数据库。

Search export 会收录全部已观测 reservation，但只有候选记录的详细 intent／outcome。Baseline slot1 的完整 outcome 可能未收录；未收录不是已证明不存在，不伪造 baseline 内容。这个合同限定受管理的本地 owner 与明确提供的内容，不认证其他机器、隐藏根或全局完整尝试历史。

每次真实回放只调用一次原 owner 的 `reserve`。原 `max_attempts`、`max_wall_seconds` 和 `max_events` 保持，不能传 budget override、另封一个 reduction 协议或恢复为空 ledger。01a 的 prepare 和 read-only inspect 不占槽；运行失败、超时、审计拒绝和未完成预留均不退槽。原预算耗尽退出8，不构造 engine。

## 2. 从原点执行与真实边界

先 durable bind 紧凑 intent 与四份 exact preparation artifacts：manifest、recipe、materialization、normalized。核对已绑定 bytes 后，才用原 `max_wall_seconds` 构造现有 bounded `ReplayPort` 并调用一次 `run(materialized.replay_input)`。不把最多256MiB的完整 source 包塞进16件 artifact 容量；完整来源仍是显式、不可变的复审输入。

实际输入从原始初始 snapshot 到 retained through，完整包括 warmup，使用新 prefix context ID；原始 spec／strategy／account／fees／seed／engine semantics 不改。不注入替代 snapshot、不另跑隐藏 warmup、不用上一次 A 的状态启动 B、不补未来事件或推进 EOF 时钟、不作额外行政撤单，也不接入 checkpoint 恢复。

状态投影边界固定为 **`after_native_run_before_dispose_v1`**。`engine.run` 可能已触发其 end／stop 行为；因此不能把该投影称为 pre-cleanup、pre-engine-end 或 focus 前状态。Native adapter／`ReplayResult`／observer／策略语义保持原样。盘口、队列、策略内部变量或 RNG 的完整隐藏状态未导出。

`ReductionStateAudit(materialized, result)` 先重新导出 preparation，再调用 `evaluate_replay(prefix_input, result)`，独立检查：

- 实际输入身份、每条原点至 through 的 input trace、warmup 引用与覆盖。
- 原点账户、成交及手续费、订单生命周期和最终账户的一致性。
- 真实 open orders、pending commands、processed/input counts、stop reason 与 execution completeness。

现金锁定只检查非负、`cash_free + cash_locked = cash_total` 等观测恒等式，不认证另一套独立保证金占用算法。保存实际 initial／final account rows 和 terminal pending／order 投影，不接受用户提供的 state。

实际 `incomplete` 的有效审计照样持久保存，状态保持 incomplete，相关 valuation 为 `not_eligible`。不制造 source criterion、reduced predicate、因果、最小性或 witness survival 真值。原始 failed／矛盾 trace／会计不守恒不能获得成功 audit。

## 3. Intent、结果与故障

`reduction_execution_intent_v1`／schema1 绑定**原始** protocol／claim IDs、完整原 engine document、上述边界和 preparation/source 内容身份。Bindings 包含 source bundle/report/run/finding、preparation、recipe、materialization、prefix context、normalized、replay spec、候选 scenario 与 preparation manifest IDs；后者与 preparation ID 相同。Intent 的静态 scope 不提前声称执行成功。

`reduction_run_receipt_v1`／schema1 含完整原 reservation、完整 intent、原 protocol／claim IDs、未改写的 `execution_status`，以及 `{replay_result_sha256,state_audit_sha256}`。实际结果与独立 audit 先进入 CAS，再提交 immutable outcome。`reduction_attempt_failure_v1` 使用同一 attempt／intent／owner 与有界真实错误。

Audit 上限128KiB；intent、receipt 和 failure 各16KiB。既有单 artifact16MiB／最多16件限制保持。Native 输入仍受原事件数、数据 bytes、时钟、序列与引擎范围约束，不裁掉超限后缀以包装成功。

| 实际情况 | 记录与返回边界 |
| --- | --- |
| source／prep／原账本前缀不符 | reserve 和 engine 前拒绝，无新槽 |
| bind、native、超时或独立审计失败 | 原槽已消耗；能发布时保存真实 bounded failure，不出成功 audit |
| `KeyboardInterrupt` 等中断 | 不自动捕获后重试；保留 consumed reserved-unfinalized |
| outcome publish 抛错或返回错误 ID | `attempt_outcome_unconfirmed`，无成功返回、不覆盖可能已提交的成功结果、不重跑或退槽 |
| 已保存结果缺件／损坏 | inspect 失败，不 repair、恢复或补跑 |

成功审计固定 flags：

| true | false |
| --- | --- |
| `from_origin_prefix_replayed`、`state_projection_audited` | `focus_state_captured`、`pre_engine_end_state_captured`、`initial_state_materialized`、`checkpoint_used`、`checkpoint_resume_verified`、`reduced_predicate_evaluated`、`witness_preservation_verified`、`margin_lock_algorithm_certified` |

这些 flags 描述已审计的回放结果与投影范围，不认证 native 作者身份或完整隐藏状态；inspect 本身不会重跑 native。

## 4. 应用与 CLI

`run_reduction_input(preparation, source, expected_preparation_id=..., split=..., ledger_factory=..., engine_factory=...)` 返回 `ReductionSubmission`：run／attempt／intent IDs、实际 execution status 和完整 state audit。`inspect_reduction_run(run_id, source=..., split=..., ledger_factory=...)` 从已提交记录和原 source 独立重建全部内容。两者 confirmation split 都先于 ID、package 或 factory IO 拒绝。

```sh
tickwitness run-reduction-input PREPARATION --source-evidence SOURCE --input-root ROOT \
  --expected-preparation-id PREPARATION_ID --runs EXISTING_RUNS
tickwitness inspect-reduction-run RUN_ID --source-evidence SOURCE --input-root ROOT \
  --runs EXISTING_RUNS
```

SOURCE 相对 input root，沿用严格源路径约束；PREPARATION 可位于独立安全目录。可选 `--engine-python PATH` 仅使用现有可信 `SubprocessReplayAdapter` 与原冻结超时；没有 resume、checkpoint、criterion、protocol 或预算覆盖参数。

Inspect 只读重载真实 reservation／intent／outcome／CAS，用保存的四份 preparation artifacts 重建包，并与完整 source 和原预算逐项比较。随后从实际 result 重新算 audit，exact-match 保存 bytes；不信任 saved flags 或外层重哈希。Guard 禁 reserve、publish、native、Popen 与网络，原字节树应不变。

既有错误分类保持：不合法 evidence 退出2、存储损坏退出3、缺件退出4、confirmation 退出5、引擎／执行错误按原分类、attempt budget exhausted 退出8。所有实际错误和诊断保留，失败 stdout 不伪装为成功报告。

## 5. 真实远端验收

新的 qualification lifecycle 在任何执行前冻结原协议 `max_attempts=5`。同一 live runs 根中，baseline 占slot1；原 frozen search 只允许两个实际 eligible candidates，分别占slots2/3（ordinal1 delay0、ordinal3 delay2e9）。实际 source finding 与完整 bundle 在已观测前缀1..3时导出；后续追加4/5不改写该包。Committed alpha corpus 的三槽预算已耗尽，原字节与 pins 不动。

| 实际 prefix case | 必须观察的 native 结果 |
| --- | --- |
| A：focus4／through4／delay1e9，实际输入1..4、warmup1..3，slot4 | 部分 fill1、fee1、position1、剩余1／PENDING_CANCEL、cap3发出的 command-1 尚在途；EOF incomplete |
| B：focus5／through6／delay1e9，实际输入1..6、warmup1..4，slot5 | 真实撤单完成、fill1／fee1、pending空，EOF completed；warmup含被改钟的cap4 |
| 再执行同一 preparation | 原五槽耗尽退出8，不构造 engine、不增加槽或改旧记录 |

精确原生 oracle 若不符应诊断真实语义，不修改为预填成功。A 和 B 各从原点新执行一次，均不宣称 CE 仍成立、恢复 checkpoint 或全局最小。

Distribution 的 core-only smoke 只验证已耗尽真实源不能配新空 ledger 续额、split／来源／存储边界和 read-only 检查，不制造 native CE。Core fake-port 测试覆盖跳过 warmup、错输入、凭空成交、账户／订单／pending 不守恒、伪 completed，以及失败／bind／超时／晚提交不确定；这些是受控单元负例，不冒充 native 证据。真实 native lifecycle 在 Ubuntu、macOS 和实际 sdist／wheel 三条安装链路执行，另以独立 core verifier 重算。

全部 runtime、测试、安装、构建和格式化在远端。Smoke 保存实际命令、ledger、不可变 source、preparations、result／audit 与失败诊断，异常不写 accepted 报告。验收只覆盖 S09-01b 的输入执行和投影审计；S09-02 自动局部缩减／预算与结论保持、S09-03 展示、真实外部参与和 release 另行验收。
