# Sprint 8 独立复核与确认窗口状态

更新：2026-10-28（Asia/Singapore）。Owner 已合并 [PR #93](https://github.com/Darrenus/tickwitness/pull/93)，基线 merge 为 `97822d7a74931a829bd3355fb40d85d4504de59d`；Sprint 7 与 S08-01／02 在各自声明范围接受。`0.2.0.dev0` 仍未发行。Owner 已表示会联系一位外部用户；外部复验实际记录尚未收到，不能把联系计划记成尝试、采用或人类领域接受。

## 切片与验收门

| 故事 | 实际范围 | 状态 |
| --- | --- | --- |
| S08-01 / #22 | 搜索数据／约束／候选／原预算槽位／结果／停止／版本完整闭包，离线重建 finding 和候选 trace diagnostics | Owner 已合并 [PR #92](https://github.com/Darrenus/tickwitness/pull/92)，#22 在受限profile范围接受并关闭 |
| S08-02 / #23 | 确认协议与一次性开启／暴露记账 | Owner 已合并 [PR #93](https://github.com/Darrenus/tickwitness/pull/93)，#23 在受限profile范围接受并关闭 |
| S08-03 / #24 | Alpha scorecard 与真实外部复验记录 | S08-03a软件与转交包实现中；外部0／PENDING，#24整体保持打开 |

原 [Sprint backlog](sprint-backlog.md#s8--独立复现与-alpha-门槛) 的12h／12h／8h专项估算与每Sprint持续质量容量保持；实际工时未登记，测试数量不替代外部验收。

## S08-01 实现边界

合同见 [Search Evidence v1](../contracts/search-evidence-v1.md)，决策见 [ADR 0025](../adr/0025-portable-search-evidence.md)。新包独立于旧8／12／14角色格式；变量角色通过严格inventory绑定显式缺省与真实存在的对象。包含development raw／normalized／quality／manifest、完整finding authority及内嵌plan／protocol／assumptions／候选journal、budget／admissions／stops、dispatch／link／captured result、原协议已观察reservation prefix、所选attempt的intent／outcome与全部必要CAS、原finding report和相邻已完成候选的trace诊断。

Export要求expected report ID，先重审当前实际来源，收集真实存储字节，再经内存ports重建并要求相同报告；缺对象不现场重造，不增加原attempt，不覆盖目的地。输出必须位于原source roots之外，避免向原控制namespace添加未知目录。256MiB／4096文件／2MiB manifest为独立受限profile，包含manifest的最终聚合上限在发布前核对；收集阶段也逐项限制，超限整体拒绝保留原件，不裁候选后缀。

Verify仅需包和core安装，不需要原SQLite／registry／ledger／workspace或native。它重新规范化raw并核对quality及manifest，复用原只读审计从闭包重建预算、派发、原槽位、账务、覆盖与三类finding；报告和诊断逐字节相等才返回FINAL。这里的重建是独立轨迹／语义审计，不重新启动native，`native_replayed=false`。FINAL只表示所供内容闭包，不认证作者、原始发布、完整历史、物理时间／存储或确认集；无inner header时明确未观察原ledger，而不是证明零尝试。

诊断复用既有ReplayComparison对相邻已完成且已审计候选比较声明条件和trace引用；raw轨迹完整保留。它不构造baseline对照、不新增baseline翻转或纯延迟因果判定。原报告的CE／预算内NO／NOT及旧claim权限不改变。

## 远端验收要求

从S07-03实际3个core／10个native案例导出，复制发行者workspace后删除全部原目录，移动包，再在禁止原stores、SQLite、native、Popen、network和写入口的core-only环境重审。检查report原字节、snapshot／diagnostic身份、预算前缀、失败／未知／在途和零执行；missing声明对象需精确role／hash错误，不能降成NOT。重算全部外层hash的报告／诊断／账务／停止篡改仍须被语义重建拒绝。

包括严格JSON／角色／别格式互拒、nofollow／FIFO／额外对象、dedup alias、聚合精确边界、原子不覆盖、并发唯一赢家、pre/postcommit故障保留，以及实际wheel和实际source archive安装闭环。全部测试、格式化、构建、安装和原生执行仍在远端；实际运行、head与artifact证据见下节。未满足外部复验与确认窗口门时不发行早期alpha。

## S08-01 远端验收记录

功能代码 head `1623aaccaa8f4e8f6432989e6a877e4b1790e4c8` 的 [Engineering 40662769753](https://github.com/Darrenus/tickwitness/actions/runs/40662769753) 与 [Documentation 40662769748](https://github.com/Darrenus/tickwitness/actions/runs/40662769748) 共13 checks 全部通过。实际 merge checkout 为 `42af1e23987835a9975cff1225175cbf3eec0bfb`，与 PR head 分开。后续验收文档提交须以 PR #92 最新 head 的独立 checks 为准，不冒充相同功能代码 head。

核心 Ubuntu 24.04／macOS 15 × Python 3.12／3.13／3.14 六组合各 **2752 passed / 112 optional-native skips**；原生 Ubuntu 24.04 与 macOS 26／Python 3.12 各 **2861 passed / 3 core-only skips / 313 warnings**。Lint、244 文件格式、112 source files 严格类型检查、80 文档／414 本地链接，以及实际 wheel／sdist 安装闭环全部通过；这些数字属于上述功能 run，warnings 保留。所有项目执行都在远端，本机只进行文本编辑、静态审阅、Git／gh 控制与下载产物读取。

安装验收报告均为 `installed_search_evidence_acceptance_v1`、accepted=true。下列 artifacts 内含报告和完整新格式包，保留30天；源码包链路使用实际 tar.gz 内脚本／样例和新安装的实际 wheel。

| 实际 artifact（共同后缀 `42af1e23987835a9975cff1225175cbf3eec0bfb`） | ID 与内容 |
| --- | --- |
| `search-evidence-core-…` | [12804168857](https://github.com/Darrenus/tickwitness/actions/runs/40662769753/artifacts/12804168857)：3个 core 案例 |
| `search-evidence-ubuntu-24.04-…` | [12804098468](https://github.com/Darrenus/tickwitness/actions/runs/40662769753/artifacts/12804098468)：10个 native 来源案例，由 core-only 复验 |
| `search-evidence-macos-26-…` | [12804534294](https://github.com/Darrenus/tickwitness/actions/runs/40662769753/artifacts/12804534294)：10个 native 来源案例，由 core-only 复验 |
| `search-evidence-source-wheel-…` | [12804454276](https://github.com/Darrenus/tickwitness/actions/runs/40662769753/artifacts/12804454276)：实际源码包／wheel 的 core3与native10案例 |

| 实际核验 | 结果与权限 |
| --- | --- |
| 脱离原目录 | 每个包导出后删除复制的完整发行者 workspace，移动包，再用禁止原stores、SQLite、临时恢复、native、Popen、network和研究写入口的core-only guard重审；全部保持相同原报告、snapshot与诊断，重复回执一致，只读字节树不变 |
| 三类结论 | core3均为 NOT_EVALUABLE；两个native平台及源码包native各为3个 COUNTEREXAMPLE_FOUND／4个 NO_COUNTEREXAMPLE_FOUND／3个 NOT_EVALUABLE；完整all-true集合的planned_predicate_truth=true，预算内true前缀仍为null，不扩大未访问候选覆盖 |
| 原预算及未知历史 | 有inner时重建完整已观察原protocol reservation prefix，保留baseline／其它plan已消费槽位，原预算耗尽案例不新增attempt；无inner的时间停止案例prefix／ledger重建旗标为false、reservations／attempts／CAS为空，仅表示历史未观察 |
| 具体分歧 | 各native报告有2对相邻已完成候选诊断，其他案例为0；source-normal首个记录差异为 `/input_trace/3/fields/native_ts_event_ns`，两侧仍指向capture_seq4的原始delta。该诊断不变成baseline翻转、纯延迟因果或全局最早业务原因 |
| 缺件与伪造 | 删除raw得到exit3及 `search_evidence_object_missing`，role=raw、hash=`89ace783f83ea99ba7e10a83ad667a95e2154e184b713136ec909d4654267789`；重算全部外层hash的finding／diagnostics篡改仍在语义重建时拒绝 |
| 发布与资源边界 | report／bundle错误pin、已存在目标覆盖均拒绝，同证据同包身份，原记录字节与slots不变；严格角色、精确聚合边界、nofollow／FIFO、dedup、并发唯一赢家与提交前后故障由远端回归覆盖；超profile整体拒绝并保留原记录 |
| 执行与认证范围 | 所有安装验收报告new_native_calls=false、new_attempts_reserved=false；FINAL仅为所供内容闭包，authorship／原发布／完整trial历史／原资源执行／confirmation认证保持false |

初轮远端发现格式／导入、nullable bytes循环变量与snapshot类型问题，应用远端格式补丁及类型修正后完整重验。安装smoke最初把无inner案例的ledger重建旗标写死为true，已改为精确匹配 `ledger_prefix_observed`，保持未观察语义，而非放宽报告oracle。AI 并行静态审阅另补强了输出必须位于原source roots之外；该审阅属于AI辅助，不宣称独立人类领域接受。

[S08-01 / #22](https://github.com/Darrenus/tickwitness/issues/22) 的实现与远端验收已由owner合并#92在上述受限profile范围接受并关闭；不发行新版本。S08-02确认窗口、S08-03真实外部复验与alpha scorecard、S10恢复和真实访谈继续独立验收，未新增实际工时、市场采用、研究收益或独立人类复验记录。

## S08-02 实现边界与验收门

合同见 [Confirmation Access v1](../contracts/confirmation-access-v1.md)，决策见 [ADR 0026](../adr/0026-one-shot-confirmation-exposure.md)。以独立ConfirmationProtocol冻结实际v1／v2源声明、确认窗口身份、完整来源footprint、最大事件数及整窗一次开启政策。旧source的development_only读取政策不改变。冻结允许内部结构／质量／forward-disjoint预检，但不向caller返回确认观测；只有显式open在持久提交后返回整个已绑定窗口，不截断、不分页、不评估原claim。

共享暴露账本固定在dataset root的confirmation-state，不接受按实验切换账本参数。同source／instrument／session的trade ID交集或book闭区间交叠继承已暴露状态，换名称、协议、registry、raw封装或支持的子集不恢复“未见”。内部预检失败不消费；一旦exposure提交，即使返回或stdout失败也不退款。并发重查与提交在同一全账本锁内；丢失、损坏或未确认持久化明确failclosed。固定初始化sentinel用于发现整个state误删；不自动修补已初始化状态。

确认读取最多1000个事件，且不超过源协议和本次冻结上限；origin2MiB、协议／单exposure各3MiB，整个账本最多256记录／32MiB，超限整体拒绝。无匹配记录仅表示本managed ledger未登记交叠，不能认证真实历史未见、预注册、外部来源或宿主owner保密。Owner改source/session、删除全部可信状态或另起store根仍属于配置／信任边界。平台底层数据工具不因此变成对owner的沙箱。

远端验收覆盖实际v1／v2冻结和整窗首次开启、重复／新名称／跨协议与registry拒绝、book重分段及trade来源交叠、独立窗口可开启、超限前拒、提交前后失败、同源并发唯一赢家、坏账本／缺件／符号链接与初始化不确定、旧探索confirmation在I/O前拒绝，以及实际wheel与tar.gz内脚本安装链路。全部执行仍在远端，报告和合成状态保留30天；实际head、运行、数量和artifact见下节。该切片不创建native执行、研究attempt／统计trial或确认finding，S08-03与独立人类复验门保持。

## S08-02 远端验收记录

功能代码 head `f1e0d8ae3783fe1999e71362b7a475b77a0d7adf` 的 [Engineering 40669710235](https://github.com/Darrenus/tickwitness/actions/runs/40669710235) 与 [Documentation 40669710220](https://github.com/Darrenus/tickwitness/actions/runs/40669710220) 共13 checks 全部通过，包含实际源码包／wheel安装链路。实际 merge checkout 为 `57efdadbaef012d5e4bd74299f8f3d1626d6d6a4`，不与 PR head 混同。

核心 Ubuntu 24.04／macOS 15 × Python 3.12／3.13／3.14 六组合各 **2870 passed / 112 optional-native skips**；原生 Ubuntu 24.04 与 macOS 26／Python 3.12 各 **2979 passed / 3 core-only skips / 313 warnings**。Lint、253 文件格式、116 source files 严格类型检查、82 文档／428 本地链接通过；这些数字属于上述功能 run，warnings 保留。全部项目测试、格式化、构建、安装与原生回放在远端，本机仅文本编辑、静态审阅、Git／gh控制与下载JSON读取。

安装报告为 `installed_confirmation_exposure_acceptance_v1`，实际报告与合成状态树保留30天。

| 实际 artifact（共同后缀 `57efdadbaef012d5e4bd74299f8f3d1626d6d6a4`） | ID 与内容 |
| --- | --- |
| `confirmation-core-…` | [12807482818](https://github.com/Darrenus/tickwitness/actions/runs/40669710235/artifacts/12807482818)：实际 core wheel |
| `confirmation-ubuntu-24.04-…` | [12807992994](https://github.com/Darrenus/tickwitness/actions/runs/40669710235/artifacts/12807992994)：Ubuntu 作业内独立 core-only wheel |
| `confirmation-macos-26-…` | [12807129401](https://github.com/Darrenus/tickwitness/actions/runs/40669710235/artifacts/12807129401)：macOS 作业内独立 core-only wheel |
| `confirmation-source-wheel-…` | [12808202589](https://github.com/Darrenus/tickwitness/actions/runs/40669710235/artifacts/12808202589)：实际tar.gz内脚本／样例配合新安装core wheel |

| 实际核验 | 结果与权限 |
| --- | --- |
| 完整首次开启 | 18个正常流程案例中有4次release，分别返回3／2／1000／1条完整观测，total_records与真实数组一致、truncated=false；包含实际v1和v2源声明，无策略或引擎执行 |
| 拒绝与继承 | 11个重复／交叠开启均exit5、`confirmation_already_exposed`并关联真实exposure IDs，stdout无观测；涵盖改名、跨source protocol／registry、首开前已冻结子集、raw重封、capture/time/payload、部分超集及book重分段；独立窗口正常开启 |
| 整窗上限 | 3个request cap／source cap／1001事件案例在暴露提交前exit2、`invalid_confirmation_protocol`，不通过截断或多次开启释放后缀 |
| 探索与重复早拒 | read-protocol-data、replay-protocol、run-scenario、freeze-search-plan 的confirmation路由均在I/O前exit5；重复open在构造实际source/data reader之前拒绝，inspect仅返回声明和关联 |
| 持久真实性 | 四类产物均accepted=true，合成records中的实际exposures.json与报告内完整4条记录逐对象相等；core／Ubuntu／macOS／source-wheel的protocol与exposure身份相同，除临时I/O路径外完整报告一致；独立SHA重算与文件名／回执匹配。同声明重复freeze为created=false，首开后变为ALREADY_EXPOSED_IN_LEDGER |
| 损坏与不确定 | 2个损坏／缺log安装案例均exit3、`confirmation_store_integrity_or_io_failure`，不伪称未见；远端回归另覆盖thread／subprocess原子竞争、提交前后replace／fsync失败、初始化失败、缺sentinel／整个state、符号链接／FIFO／超限、锁inode替换及256／257与精确字节边界 |
| 预算与来源 | 安装guard禁止native、worker、network、旧attempt／budget写入口；new_native_calls、new_attempts_reserved、old_budget_mutations均false，原immutable source证据／catalog保持不变；新增状态仅为明确的confirmation namespace及anchor |
| 认证范围 | historical_unseen_certified、host_owner_confidentiality_claimed及确认finding等认证旗标为false；owner仍可直接读取其文件。origin覆盖只约束同一可信managed root和声明来源，不冒充全局试验历史或预注册 |

初轮远端发现新增持久层测试fixture使用了旧v1协议不支持的clock policy，47个用例在进入目标逻辑前被拒绝；改为既有合法 `capture_order_unbound_v1` 后重验，不放宽领域规则或断言。同时应用远端格式补丁，修正异常链、循环闭包和一处冗余cast。AI交叉审阅补强了并发AlreadyExposed异常保留、全账本origin互斥与线性区间扫描；该审阅仍为AI辅助，不替代独立人类领域接受。

[S08-02 / #23](https://github.com/Darrenus/tickwitness/issues/23) 的实现与远端验收已由owner合并 [PR #93](https://github.com/Darrenus/tickwitness/pull/93) 在上述受限profile范围接受并关闭。后续文档提交有独立最新head检查，不冒充同一功能run；S08-03外部复验／alpha scorecard、S10恢复和真实访谈继续分别验收，不发行新版本，也不新增实际工时、市场采用或研究收益记录。

## S08-03a 实现边界与外部门

合同见 [Alpha Scorecard v1](../contracts/alpha-scorecard-v1.md)，决策见 [ADR 0027](../adr/0027-reproducible-alpha-scorecard.md)，转交步骤见 [外部复验手册](../alpha-reproduction.md)。本轮是原8h故事的软件切片：把实际历史native产生的两份合成证据、真实core wheel、手册与stdlib回执脚本封为严格kit，独立重建技术scorecard，外部真实尝试待对方执行后再记入原故事；不补记实际工时或扩充Sprint容量。

语料见 [examples/alpha](../../examples/alpha/README.md)，原字节来自owner接受的S08-01实际Ubuntu artifact12804098468；原生成head／merge与当前组装代码分开追踪。反例使用gt0 USD，完整all-true参考使用gt−3 USD，二者是不同冻结问题，不提供控制变量因果或真实市场收益证明。Kit不执行随包wheel或脚本；接收者在新core环境按独立渠道pin安装并运行。

每次qualify均重新审计两份search evidence；完整clean要求全eligible已审计且全true，预算内未发现不顶替clean。无效扰动从实际冻结assumption上界+1ns构造，并调用真实validator取得指定范围拒绝。Publication probe在新目录实际执行正常／重复拒绝／提交前同步失败／提交后父目录同步失败；后者保留完整目录、返回不确定错误而不产生成功发布回执，保留内容仍需重新语义核验。不据此认证真实断电、历史磁盘状态或S10恢复。

Kit为独立32MiB／512files／256KiB manifest profile，wheel≤4MiB、guide与runner各≤64KiB；超限整体拒绝。所有路径、hash、完整文件集、有界普通文件与原子no-replace受检查。保存的scorecard必须当场重算并逐字节相同，不能只信已存PASS。原研究attempt预算、native执行、确认访问和claim权限不变。

外部runner使用真实安装CLI，保留成功、失败或超时及环境／退出码／诊断，自报participant role只标 `SELF_REPORTED_UNREVIEWED`，不会自动把gate改成已完成。Owner会联系真实外部用户，实际记录收到并核实前external_attempts=0／external_successes=0／PENDING；CI、AI审阅、维护者复跑和合并均不计外部尝试。#24整体保持打开，不发行alpha、不新增采用或独立人类领域接受记录。

远端验收门包括实际wheel与tar.gz内脚本／guide／原始语料、独立cwd与迁移后kit、无native／network／原stores／SQLite／budget写入口、真实fault probe、新saved receipt重算、重hash伪造拒绝、限额与安全IO、runner automation真实成功和真实错误留痕。报告、kit、probe与未审阅submission保留30天；实际运行、head与artifact待回填，所有项目运行仍在远端。
