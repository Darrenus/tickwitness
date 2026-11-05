# Reduction Comparison v1

状态：S09-03实现与远端资格完成，[PR #100](https://github.com/Darrenus/tickwitness/pull/100)待owner接受，2026-11-05；实际run与artifact见[Sprint 9验收记录](../planning/sprint-09-status.md#s09-03-远端验收记录)。Owner已合并[PR #99](https://github.com/Darrenus/tickwitness/pull/99)接受S09-02，merge `2aaef3e66edba87035a32779122d4858810da2c1`。本合同连接[原点前缀执行](reduction-execution-v1.md)、[原数值条件保持判定](reduction-search-v1.md)与审阅者的差异视图；决策见[ADR 0031](../adr/0031-reduction-evidence-comparison.md)。外部真人复验仍0／PENDING，原PR94转交包不变，无新release。

## 1. 比较对象与权限

左侧是source evidence实际选中的、completed／audited／false的**原情景见证**，不是baseline；右侧是一条已提交的reduction run。右侧可以来自S09-01b的手动前缀执行或S09-02的有限搜索，不要求它是某个搜索的best。调用方不能另换左侧run、criterion、threshold、source或budget。

应用先固定并重验完整portable source及显式bundle／report pins，再验证原live ledger的全部已观察reservation prefix、intent／outcome和CAS。右侧通过既有`inspect_reduction_run`独立重建preparation、原协议owner、执行receipt及完整`ReductionStateAudit`。左侧从该preparation绑定的原witness读取实际`ScenarioRunReceipt`与raw replay，重算`ScenarioEvaluation`及原冻结numeric criterion；左侧必须仍为可估值的false见证。两个run须为不同原attempt，且engine／environment一致。

领域构造器`ReductionComparison`重新核对typed authority、materialization、两个receipt和两个raw result；不能用调用方自报的审计flags代替原始证据。右侧继续用`ReductionPreservationAssessment`重算PRESERVED／NOT_PRESERVED／NOT_EVALUABLE，非法会计、输入、哈希或绑定是验证错误，不被降级为未知。

整个比较与复验是只读操作：不创建或恢复ledger、不占slot、不启动native／worker、不导入portable预算、不改原intent／outcome／journal、不补跑或修复。已耗尽的原11槽ledger仍可以审阅。报告中的`native_replayed`与`attempt_reserved`始终false；实际原生运行来自被复验的既有记录，不能解释成比较入口再次执行了两版。

## 2. 输入分区与被移除内容

`input_difference`按实际源事件顺序给出：

| 字段 | 含义 |
| --- | --- |
| source_event_count／retained_event_count／removed_event_count | 原完整情景、保留前缀、被移除后缀的实际事件数 |
| origin_ref／focus_ref／through_ref | 原点、固定审阅focus、实际前缀终点 |
| retained_refs／warmup_refs／review_refs | 保留的完整原点前缀、focus之前的必要warmup、focus到through的审阅区间 |
| original_additional_delay_ns／reduced_additional_delay_ns | 两次实际输入各自绑定的额外延迟 |
| removed_events | 每条移除事件的原稳定引用、完整原情景事件对象及该canonical原行SHA |
| changed_retained_events | 保留事件的引用、两版canonical行SHA及实际receive_time_ns字段差异 |

稳定引用为`{line,capture_seq,event_type}`：line是原源中的1-based实际位置，capture_seq可以从非1值开始，两者不能混用。当前回放预检仍拒绝同流capture缺口；报告按实际位置构造引用，不授予非法gap执行权限。所有retained、warmup和removed列表都来自实际事件索引。Focus只控制审阅范围，不能删除左侧warmup或充当运行态checkpoint。

`removed_events.original_event`包含**原见证情景派生后的时钟**，不是未施加原延迟的原始tape；同时保留其事件类型、交易、盘口和序列字段。行SHA是canonical事件对象的SHA-256，不含换行。保留区域重新按合法算子派生，除已声明的receive_time_ns延迟变化外，其余事件载荷必须相同。没有中间删除、左端截短、状态注入或隐藏EOF事件。

## 3. 观察范围与数值条件

`horizon.policy`固定为`whole_recorded_runs_including_unequal_eof_v1`。报告保留两侧实际event count、through引用、execution_status、completeness、valuation_status与mark。`same_input_horizon`只表示输入事件数未缩短，不证明相同运行条件；`shared_terminal_state_captured=false`明确没有从两个完整run提取同一中间边界的策略／账户／队列／在途状态。

两版各自在自己的真实终点重用**同一原numeric criterion**：

| 右侧实际评价 | both_false_witnesses | 解释 |
| --- | --- | --- |
| PRESERVED | true | 原见证及当前缩减run的实际终点均可估值且criterion=false |
| NOT_PRESERVED | false | 缩减run可估值，但criterion=true |
| NOT_EVALUABLE | null | 当前终点incomplete、无成交或估值歧义，value／truth保持null |

原观察给出metric、unit、comparator、threshold、value、truth、reason、evaluation policy和mark；右侧保留完整重算assessment。两侧mark或EOF范围可能不同，因此没有将数值差额标为可比较因果效应，也不发出baseline flip、source claim verdict、原finding改写或eligible量词域扩张。

## 4. 原始差异与业务投影

`trace_comparison`复用既有`compare_scenario_traces`，同时保留raw与business视图、每通道的首次差异、实际trace引用和两侧raw value。通道展示顺序为input_trace、decision_trace、order_trace、fill_trace、account_trace、execution_status、completeness；每个通道按recorded ordinal、再按排序后的JSON字段寻找差异。这个顺序不是跨通道的全局时间顺序，也不建立因果归属。

业务投影沿用`coupled_stress_business_projection_v1`。它去除已声明的receive/native时钟字段、native trade ID，并只在明确的order字段映射各自唯一submit order ID及已知的cancel-rejection模板。原事件时间和载荷、未知字段、pending commands、订单／账户与停止状态仍参与比较。投影的excluded_paths和ID映射规则完整写入报告，原值与source refs保留；旧投影及旧比较格式不改变。

对不同长度的run，移除的input row及EOF、final account差异照实出现。报告不隐藏这些差异，也不把较短run的EOF状态解释成原长run的同一中间状态。展示的`first_divergence`只是固定通道顺序下的首项，`global_earliest_claimed=false`、`causal_attribution_issued=false`。

## 5. 格式、身份与独立复验

`reduction_comparison_v1`／schema1包含固定scope、source及两侧执行bindings、input_difference、original_observation、完整reduced_assessment、trace_comparison、condition_differences、horizon、both_false_witnesses和领域verification。完整report上限16MiB。Bindings包括原bundle／report／finding／predicate／protocol／claim／witness身份，以及两个attempt、intent、raw result、evaluation／audit和assessment身份。

导出是精确的canonical `reduction_comparison_export_v1`／schema1：`comparison_id`为**report canonical bytes**的SHA-256，`report`为完整对象。它不是整个envelope文件的SHA。Export上限16MiB＋64KiB；拒绝重复JSON字段、浮点／非有限数字、未知顶层字段、非canonical编码及hash不一致。比较命令的JSON stdout没有尾随换行，可以直接保存并交给verify；Markdown是审阅视图，不代替canonical export。

`verify_reduction_comparison`先检查显式expected comparison ID及bounded export，再从调用方指定的run ID、完整source pins和已有live ledger独立重算整个比较。保存的report和scope即使结构合法、内部数值自洽且外层hash已重算，也必须与实际重算字节完全相同。最终再次核对source prefix、相关intent／outcome，拒绝读取期间发生变化的证据；不会写入repair记录。

领域verification只声明自己的输入、轨迹和数值重算，`live_ledger_reaudited=false`；CLI复验receipt另以应用已完成的重验声明source_package_reaudited、observed_live_prefix_matched、original_witness_reaudited、reduction_run_reaudited、comparison_recomputed、saved_report_matched=true。其余native执行、占slot、写证据、baseline／source claim、全局最早／因果、confirmation、完整历史、作者签名和真人审批权限均false。

## 6. CLI与审阅工作流

```sh
tickwitness compare-reduction-run RUN_ID --source-evidence SOURCE \
  --input-root ROOT --runs EXISTING_RUNS \
  --expected-bundle-id BUNDLE_ID --expected-report-id REPORT_ID

tickwitness compare-reduction-run RUN_ID --source-evidence SOURCE \
  --input-root ROOT --runs EXISTING_RUNS \
  --expected-bundle-id BUNDLE_ID --expected-report-id REPORT_ID --format markdown

tickwitness verify-reduction-comparison RUN_ID exports/comparison.json \
  --expected-comparison-id COMPARISON_ID --source-evidence SOURCE \
  --input-root ROOT --runs EXISTING_RUNS \
  --expected-bundle-id BUNDLE_ID --expected-report-id REPORT_ID
```

SOURCE与export均使用严格input-root相对路径；export必须为有界常规`.json`文件。Ledger只以`create=False`打开。全部命令在读取ID、source、export或factory之前拒绝confirmation。错误沿用原taxonomy：非法证据／请求exit2、IO或完整性存储错误exit3、缺件exit4、confirmation拒绝exit5。比较入口不申请attempt，因此没有正常的预算耗尽exit8路径。

JSON export、复验receipt和Markdown均由同一独立重算对象生成。审阅者可先查看保留／warmup／移除区间，再查看各自数值观察范围与per-channel first差异，最后用source、原live记录和comparison pin重复verify。这个过程复验了两版既有实际运行，不伪称在耗尽预算后又新跑两版。

## 7. 远端安装资格与边界

新资格脚本消费同一个CI作业中已执行的S09-02实际结果，复制完整workspace及原报告，再以安装的core-only verifier调用新CLI。原协议在首次运行前冻结11槽／1000events／60s：source占1..3、实际native后取消占4、七次主缩减占5..11。新比较全过程维持这11槽及所有原字节，不创建第12槽、不调用engine。

三个有实际native源记录的安装profile检查七次主运行与一次取消后运行。强oracle定位原完整7事件、focus4、三次P／三次NP／一次NE，精确核对移除的原情景事件、receive clock变化与行SHA；raw时钟差异和business投影差异各自保留。保存canonical exports并逐个verify，重复best export必须同字节，另保存实际Markdown。自洽改写数值保持判定、被移除内容及业务首次差异的重hash伪报告均必须实际拒绝；错误source pin、缺失run、缺失／损坏CAS和confirmation分别检查。

Core-only profile没有actual reduction run，资格只证明实际confirmation pre-IO及缺失ledger／非法export拒绝，`lifecycle=null`，不冒充正例原生比较。所有profile的新比较动作均`native_execution=false`、`native_replayed=false`；`upstream_native_evidence_reused`区分是否复用了上游真实native证据。

四条路径分别保存core、Ubuntu、macOS及actual-sdist scripts/data＋installed wheels的独立产物：`reduction-comparison-{core,ubuntu-24.04,macos-26,source-wheel}-<actual github.sha>`。每份保存原完整upstream source／ledger／CAS／journal、原报告、新export／receipt、实际命令transcripts、解释器身份、内外同字节验收报告和逐文件hash manifest。失败保留诊断且不写新的accepted比较报告。具体通过数和artifact链接只在远端实际完成后记录。

全部项目执行、测试、格式、构建和安装在远端CPU。Owner接受、外部真人复验、S10恢复和新release分别验收；CI、AI审计和owner合并均不能替代外部真人。没有最小反例、全局完整历史、市场真实性、采用或研究收益声明。
