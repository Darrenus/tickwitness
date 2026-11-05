# Reduction Search v1

状态：S09-02实现与远端验收完成，[PR #99](https://github.com/Darrenus/tickwitness/pull/99)待owner接受，实际run／artifact见[Sprint 9验收记录](../planning/sprint-09-status.md#s09-02-远端验收记录)。Owner已合并[PR #98](https://github.com/Darrenus/tickwitness/pull/98)，接受merge为`3577be7b07fba10a7da70cc95c2d3e887fcb06fd`。本切片在[Reduction Input v1](reduction-input-v1.md)和[Reduction Execution v1](reduction-execution-v1.md)之上添加有限、可协作取消的局部搜索；决策见[ADR 0030](../adr/0030-bounded-local-reduction.md)。外部真人复验仍0／PENDING，原PR94转交归档不变。

## 1. 复用原证据与原预算

输入必须是完整、可独立验证的development search evidence，其中已存在completed／audited／false的原见证。先重审整个source、原finding authority和指定witness，再按原源数据重建合法完整初始preparation。原bundle／report／finding／predicate／protocol／claim／assumptions／scenario／spec／witness run全部绑定；调用方不能提供新criterion、threshold或state。

计划只冻结有限搜索规则，不赋予新attempt额度。所有实际候选都调用既有`run_reduction_input`，保留同一原`ExecutableProtocol`、已有live ledger、max_attempts／max_events／单次max_wall_seconds和完整origin warmup。Source快照中的全部已观察reservation prefix、候选intent／outcome和CAS必须与live ledger逐字节相同；合法新suffix可以存在。Portable包不能初始化空ledger或补建旧槽位。未在source中收录的baseline详细outcome仍是未观察，不伪造不存在或补造baseline。

原search campaign的journal、budget和stop不重新打开或续额。Reducer的max_steps与候选间admission elapsed cap只会进一步限制原attempt预算的使用；没有新的总存储额度、S07硬时限继承或预算refund。失败、超时、取消后的已执行候选及发布不确定的槽位均不退款。

## 2. 有限计划与严格下降

请求是精确的`reduction_search_request_v1`／schema1：

| 字段 | 范围 |
| --- | --- |
| witness_ordinal | 1..1024，必须选原报告中的实际false witness |
| focus_from_capture_seq | 实际源事件引用；冻结后不移动 |
| max_steps | 1..100，限制dispatch／admission数量 |
| max_wall_time_ms | 1..86400000，仅候选间的admission elapsed cap |

`reduction_search_plan_v1`／schema1保存完整source bindings、原请求、实际source capture列表、minimum through／delay、初始point、原预算和固定policy／scope。上限4MiB，canonical hash即plan ID；应用freeze、run和inspect都对完整source重建exact plan，不能信任自报scope或哈希。

初始point保留原完整输入和原witness delay。初始best是`SOURCE_WITNESS`，引用原已审计false run，既不是新执行也不算一次简化。每个point只含through_capture_seq、additional_delay_ns。真实成本为`(retained_event_count, additional_delay_ns)`，事件数量来自实际capture列表索引，不用capture编号相减。

固定policy为`halve_delay_then_trim_one_tail_event_v1`：

1. 先尝试将delay按整数向下除2；必须小于当前值且仍不低于原assumption minimum。
2. 再尝试移除最后一条实际源事件；不得越过冻结focus、strategy submission或stress anchor。
3. 只接受严格更小且`PRESERVED`的候选；接受后从新best的第一个算子重新开始。其他已评价结果只推进当前邻域游标。

每个候选重新生成原合法情景和完整origin→through前缀，使用原spec／账户／手续费／策略／seed／引擎。没有事件中间删除、checkpoint、额外EOF时钟、隐藏warmup、A状态启动B或对旧run flags的改写。若不存在下一个合法邻居，先记录neighborhood_checked；不能将“刚好达到max_steps”盖过已经检查完的邻域。

## 3. 反例保持的三值评价

`ReductionPreservationAssessment`只取原`SearchFindingProtocol`中的numeric criterion，在**实际缩减输入的观察范围**上重新应用。原finding／predicate IDs提供来源身份；新delay点不被插回原frozen eligible grid，不重写原finding、扩展其量词域或发出source-claim／baseline flip结论。

评价先独立重建`ReductionStateAudit`，精确核对原intent、owner／claim／source、实际result和audit的CAS绑定，再用真实replay evaluation得到观察：

| 实际运行与观察 | outcome／truth／value |
| --- | --- |
| completed、可估值、原criterion=false | PRESERVED／false／实际decimal值 |
| completed、可估值、原criterion=true | NOT_PRESERVED／true／实际decimal值 |
| incomplete、无成交或估值歧义 | NOT_EVALUABLE／null／null，并保留真实reason |
| hash／绑定／输入轨迹／会计错误 | 验证错误，不能降级为温和的NOT_EVALUABLE |
| 原生失败、未完成reservation或无槽位 | 显式执行失败／未执行记录，没有伪造assessment |

`reduction_preservation_assessment_v1`／schema1上限128KiB，保存outcome、criterion_observation、原source身份、candidate的run／intent／attempt／preparation／recipe／context／result／audit身份和固定scope。Metric／unit／comparator／threshold只来自原authority，无override参数。旧preparation与state-audit flags保持原值：新的保持评价不会把旧`witness_preservation_verified=false`改成true。

搜索报告给出已评价的有限subset、best-known合法见证、未知邻居与停止原因。`NOT_EVALUABLE`仍未知。即使neighborhood_checked，也不认证局部或全局最小，不声称因果、市场真实性、原作者身份或全局完整尝试历史。

## 4. 持久journal与失败边界

`LocalReductionCampaignStore`使用已有严格文件IO机制的独立`reduction-campaigns`namespace；原search namespace仍拒绝新路径和记录类型。Header是原canonical plan，freeze同一plan幂等且不会清空已有执行记录。

先持久提交dispatch及nonce，再由原ledger按nonce预留槽位；随后记录真实attempt link。既有reduction intent与四件preparation在engine构造前持久可读，实际receipt／result／audit留在原CAS。每个成功完成独立审计的候选将exact preservation assessment写入append-only result记录。Stop与cancel各有独立、不可覆盖记录，不能用假ordinal代表取消。

运行过的计划再次run只做inspect。Header-only计划可以首次执行；已有dispatch／link／result／stop不能被当作恢复授权、自动重跑或reset。故障保留已提交结果和最佳已知见证，诚实展示已消耗、unfinalized或unexecuted。Late publish／错ID不覆盖可能已经提交的成功receipt；`KeyboardInterrupt`等不被转换成自动重试或退款。

只读inspect重新认证source与原live ledger，按固定遍历顺序重建候选，调用既有`inspect_reduction_run`重算每个实际run，再从真实CAS重算assessment并逐字节比较journal。缺件、篡改、非法顺序或伪造truth失败；没有repair、补跑、reserve、native、网络或预算写入。给assessment改值并重新canonical编码，仍不能代替真实raw-result审计。

## 5. 取消与时间范围

取消是**候选之间的协作取消**。正式cancel接口幂等提交原plan的标记，绕过协调器锁以便在run期间发出请求。当前已预留的bounded attempt继续完成并持久提交实际outcome／assessment；下一候选dispatch前观察标记并停止。它不杀native worker，也不证明S10硬取消、进程组终止或crash恢复。

已terminal计划收到cancel只返回ALREADY_TERMINAL，不改已有stop。竞态中的晚marker不能重写先前stop；报告分别显示observed cancellation request和是否实际导致cancelled stop。

`max_wall_time_ms`使用单调时间，仅在候选admission边界检查。当前attempt仍由原max_wall_seconds约束，因此这不是硬总墙钟deadline。Journal以固定文件上限和100steps界定，但未实现总体managed-storage硬限额。原S07监督器的硬资源保证不能移植为这个新入口的未验证声明。

终止原因至少包含neighborhood_checked、step_limit、admission_deadline、cancelled、original_attempt_budget_exhausted、operational_failure。取消／步数／admission cap／邻域完成是controlled stop、exit0；原attempt耗尽exit8；unfinalized／发布不确定exit3，实际operational error按原分类保留7或3。Run即使exit8仍输出结构化report到stdout；非法请求等错误留在stderr。Inspect只要复验成功就exit0，不因历史stop是budget8而重新失败。

## 6. 应用与CLI

应用入口为freeze_reduction_search、run_reduction_search、inspect_reduction_search、cancel_reduction_search；全部在ID、source和factory IO前拒绝confirmation。Run只接受原timeout的trusted engine factory；单调时钟依赖不改变native数据时间。

```sh
tickwitness freeze-reduction-search SOURCE REQUEST --input-root ROOT \
  --expected-bundle-id BUNDLE_ID --expected-report-id REPORT_ID --runs EXISTING_RUNS
tickwitness run-reduction-search PLAN_ID --source-evidence SOURCE --input-root ROOT \
  --runs EXISTING_RUNS
tickwitness inspect-reduction-search PLAN_ID --source-evidence SOURCE --input-root ROOT \
  --runs EXISTING_RUNS
tickwitness cancel-reduction-search PLAN_ID --source-evidence SOURCE --input-root ROOT \
  --runs EXISTING_RUNS
```

SOURCE／REQUEST沿用严格input-root相对路径检查。Run可选`--engine-python PATH`，使用原bounded subprocess adapter，没有budget、criterion、checkpoint或resume覆盖参数。报告包含plan／source、ordered steps、best、真实stop、cancellation、counts及只读verification；steps分别显示真实dispatch、attempt／run、assessment或执行错误，不能把失败当作已否定或未发现。

## 7. 远端installed资格

新合成生命周期在任何执行前冻结原numeric criterion `lt -1.5 USD`及原11槽／60s／1000events。原baseline占1槽、实际source search占2槽；原eligible点0与2e9的实际metric预期为-2／-1，原finding仅ordinal3为false witness。旧gt0三槽golden、已接受S09-01b五槽资格与PR94手交包均不改。

资格准备调用既有replay-protocol并保留其原ProtocolEvaluation，用于构造真实source；报告中的baseline／source-claim=false限定reducer新增评价，不否认bootstrap已有基线评价，也不从两者另发baseline flip结论。

同一原protocol／live root／source依次执行：pre-start取消0槽；controlled hook在一次**真实SubprocessReplayAdapter**返回后、协调器提交前请求取消，占槽4并保留其真实结果；主计划占槽5..11；耗尽计划自然停止，无slot12或engine构造。Controlled hook是确定的资格注入点，不冒充外部真人或真实OS中断。

主计划固定focus4、delay-half优先，七个预期point为`(7,1e9)` NOT_PRESERVED、`(6,2e9)` PRESERVED、`(6,1e9)` NOT_PRESERVED、`(5,2e9)` PRESERVED、`(5,1e9)` NOT_PRESERVED、`(4,2e9)` PRESERVED、`(4,1e9)` NOT_EVALUABLE。最后best为4／2e9，但未知邻居不证明最小。1e9路径在cap5先第二次成交，再显式OrderCancelRejected清除在途命令；2e9路径在较早的benign cap4已能处理撤单。不得假设名义due time自动早于下一trade结算。

这些是必须实际验证的oracle，不能预填成功。Core-only安装只核confirmation pre-IO、旧source配missing／empty ledger拒绝和无native权限边界；actual-native由Ubuntu、macOS和实际sdist/wheel三条安装路径执行，再用独立core verifier检查。保存全部实际transcripts、journal、原始CAS、receipt／audit、真实解释器身份、内外同字节report和逐文件hash；失败保留诊断，不写accepted报告。所有项目运行、测试、安装、构建和格式化在远端CPU执行。

Owner接受、外部真人复验、S09-03比较、S10恢复和新release分别验收；CI或AI复核不替代这些门。
