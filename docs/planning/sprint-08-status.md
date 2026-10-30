# Sprint 8 独立复核与确认窗口状态

更新：2026-10-29（Asia/Singapore）。Owner 已合并 [PR #94](https://github.com/Darrenus/tickwitness/pull/94)，接受 merge 为 `3ab62bf97dd21609638e9f887f68f450bc345aaf`；S08-03a 软件在下述受限技术范围接受，后续[S09-01a](sprint-09-status.md)也已通过owner合并#95接受。`0.2.0.dev0` 仍未发行。已收到的补充回传由owner明确确认为Claude自动化，不计真实外部用户；真人门仍为0／PENDING，#24保持打开。兼容性问题先归入[#96](https://github.com/Darrenus/tickwitness/issues/96)处理，不把AI执行、联系计划或软件合并记成外部采用与人类领域接受。

## 切片与验收门

| 故事 | 实际范围 | 状态 |
| --- | --- | --- |
| S08-01 / #22 | 搜索数据／约束／候选／原预算槽位／结果／停止／版本完整闭包，离线重建 finding 和候选 trace diagnostics | Owner 已合并 [PR #92](https://github.com/Darrenus/tickwitness/pull/92)，#22 在受限profile范围接受并关闭 |
| S08-02 / #23 | 确认协议与一次性开启／暴露记账 | Owner 已合并 [PR #93](https://github.com/Darrenus/tickwitness/pull/93)，#23 在受限profile范围接受并关闭 |
| S08-03 / #24 | Alpha scorecard 与真实外部复验记录 | Owner 已合并 [PR #94](https://github.com/Darrenus/tickwitness/pull/94) 接受S08-03a软件；S08-03b外部0／PENDING，#24整体保持打开 |

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

远端验收覆盖实际wheel与tar.gz内脚本／guide／原始语料、独立cwd与迁移后kit、无native／network／原stores／SQLite／budget写入口、真实fault probe、新saved receipt重算、重hash伪造拒绝、限额与安全IO、runner automation真实成功和真实错误留痕。报告、kit、probe与未审阅submission保留30天；实际运行、head与artifact见下节，所有项目运行仍在远端。

## S08-03a 远端验收记录

功能代码 head `1de34c661b34e23fcc0826d294ce16c43bd5d3bf` 的 [Engineering 40680161528](https://github.com/Darrenus/tickwitness/actions/runs/40680161528) 与 [Documentation 40680161350](https://github.com/Darrenus/tickwitness/actions/runs/40680161350) 共13 checks全部通过，包含实际源码归档／wheel组合安装验收。实际 merge checkout 为 `b89bc2ac27bb4e8811b84138f32dce85afb8fd31`，与 PR head、原始语料生成revision分别记录。

核心 Ubuntu 24.04／macOS 15 × Python 3.12／3.13／3.14 六组合各 **3005 passed / 112 optional-native skips**；原生 Ubuntu 24.04 与 macOS 26 各 **3114 passed / 3 core-only skips / 313 warnings**。Lint、265 文件格式、121 source files严格类型检查、86 文档／442 本地链接通过；这些数字属于上述功能 run，warnings保留。所有项目运行、测试、格式化、构建、安装与原生回放均在远端，本机仅文本编辑、静态审阅、Git／gh控制、下载与JSON／SHA读取。

安装报告为 `installed_alpha_scorecard_acceptance_v1`。报告、完整kit、真实probe目录、未审阅automation提交、可转交归档与handoff保留30天。

| 实际 artifact（共同后缀 `b89bc2ac27bb4e8811b84138f32dce85afb8fd31`） | ID 与内容 |
| --- | --- |
| `alpha-core-…` | [12811533995](https://github.com/Darrenus/tickwitness/actions/runs/40680161528/artifacts/12811533995)：实际core wheel、scorecard与转交包 |
| `alpha-ubuntu-24.04-…` | [12813090562](https://github.com/Darrenus/tickwitness/actions/runs/40680161528/artifacts/12813090562)：Ubuntu作业内独立core-only wheel |
| `alpha-macos-26-…` | [12811704525](https://github.com/Darrenus/tickwitness/actions/runs/40680161528/artifacts/12811704525)：macOS作业内独立core-only wheel |
| `alpha-source-wheel-…` | [12812314605](https://github.com/Darrenus/tickwitness/actions/runs/40680161528/artifacts/12812314605)：实际tar.gz内脚本／guide／语料与新安装core wheel |

| 实际核验 | 结果与权限 |
| --- | --- |
| 真正固定输入 | 两个原native合成包的bundle／report pins保持 [语料来源](../../examples/alpha/README.md) 原值；反例为完整已审计false见证，clean为非空全部eligible已审计且全true；两谓词分别gt0和gt−3 USD，不作同命题配对因果解释 |
| 独立环境重建 | 实际wheel在无源码依赖的core环境、独立cwd中组装kit；移动kit并删除复制的assembly输入后qualify／repeat／verify saved／postcommit retained／归档解压复验得到同一完整技术回执；kit与原source字节树不变 |
| 真实invalid校验 | 从实际assumption最大值2,000,000,000ns推导2,000,000,001ns，先通过可执行ScenarioSpec结构，再由真实validator精确拒绝冻结范围；不跑native、不占原研究槽位、不输出该无效情形的finding |
| 实际发布边界 | 新目录正常发布读回、重复目标拒绝且原字节不变；提交前同步故障无最终目标且stage清除；提交后父目录同步故障无成功回执并保留完整目标，其两份actual case再独立重审。技术PASS仅表示观察到这些受控失败，不认证历史durability或断电恢复 |
| 重hash仍拒绝 | 改invalid上界／挑战值／ScenarioSpec ID再重算scorecard ID，使伪造文档仍满足严格shape；验证实际重跑新probe后拒绝exact receipt不一致。缺README、额外隐藏文件、错误pin均精确拒绝，不能降成技术通过 |
| 实际转交闭包 | 每个平台独立核kit manifest／全部payload SHA、wheel SHA、archive SHA与handoff；tar仅含唯一顶层kit，不夹带probe或automation记录；解压后再用guarded installed core复验。安装前校验命令在pip之前，要求owner独立渠道确认归档digest |
| 真实自动化提交 | 原样stdlib runner使用同一core解释器，成功VERIFIED时runner／CLI均exit0；错误pin的真实FAILED记录为runner10／CLI3并保留原stderr，无scorecard成功文件。两条实际submission及saved receipt与报告逐对象一致，身份均automation／SELF_REPORTED_UNREVIEWED |
| 严格guard与资源边界 | 主qualify／saved重验禁native import、原stores、SQLite、network、研究worker及旧预算写入口；独立runner子CLI原样执行，报告如实标runner_subprocess_guarded=false而非伪称全程instrumented。边界回归覆盖32MiB／512files及单件tighten、unsafe／missing／alias／额外目录、并发nooverwrite、提交前后write／sync故障和输出／启动失败留痕 |
| 外部与权威 | gates保持technical PASS、external_attempts=0／external_successes=0／PENDING，scope八项均false。CI／AI／owner不计外部用户；participant role自报不能改gate，保存PASS不能替代当场重验。无新release、native研究attempt、confirmation访问、claim扩权或S10资格 |

初轮远端同时捕获了verify命令positional注册顺序与冻结CLI合同相反的问题；按KIT再SAVED修正，没有改手册命令或弱化断言。macOS实测请求为 `/tmp/tickwitness-tagged-verifier/bin/python`，runtime为 `/private/tmp/tickwitness-tagged-verifier/bin/python`；其prefix与resolved requested venv均为 `/private/tmp/tickwitness-tagged-verifier`，且不同于base framework。现以同一解释器实际sys.executable／prefix／base_prefix精确比较runner命令，确认别名属于同一venv；失败先保留诊断树而不产accepted报告。归档按各平台实际SHA校验，实测Mac归档SHA不同于Linux，kit内容身份与技术语义仍一致。格式问题使用远端生成的补丁处理。最终交叉静态审阅未发现P1／P2阻塞，但仍属于AI辅助，不替代独立人类领域接受。

[PR #94](https://github.com/Darrenus/tickwitness/pull/94) 的S08-03a软件与可转交包已在上述profile内通过远端验收，并由owner合并接受；[#24](https://github.com/Darrenus/tickwitness/issues/24) 因S08-03b真实外部复验未完成而保持打开。Owner将联系外部参与者，实际回执／失败原文收到并核对前不填外部尝试、不发alpha、不宣称采用。交付给外部用户的现有PR94归档与pin保持原样，不因S09工程变化而替换；S10恢复、真实访谈及研究收益记录没有新增。

## 自动化补充回传与 #96 兼容性修复

Owner已明确确认本批记录全部来自其请求的Claude自动化。指定目录有5个唯一submission：01／02／03／05为VERIFIED、06为FAILED；另有Python3.9.6的前置安装／启动失败日志而无submission。四份成功scorecard逐字节相同，5个canonical submission IDs与原PR94的kit／归档／wheel pins静态核验吻合，8份normal／postcommit probe树与原kit一致。此审计未执行回传harness；环境与执行过程仍属供方报告，不认证真实OS、容器隔离或独立人类参与。回传矩阵的external-user标题与实际automation角色冲突，以原始角色记录和owner确认为准，原件不改。

Alpine回执保留runner10／CLI3和缺失libc原子发布入口的错误，无scorecard、probe为空；不把这一失败改成通过。两份Linux日志显示shasum不可用、sha256sum替代成功。Python3.9被pip正确拒绝，继续启动旧runner得到UTC导入traceback。具体musl版本、raw syscall探针或统一glibc版本下限未独立确认，不能据此扩大支持矩阵。

[#96](https://github.com/Darrenus/tickwitness/issues/96) 本轮实现范围：手册与新sidecar提供macOS／Linux系统checksum命令，实际运行正确与错误digest校验；精确说明发布能力并补missing API安全失败回归；独立runner在版本相关导入／包加载／worker／输出前拒绝不支持Python，exit2且无submission。真实Python3.9拒绝路径在远端core wheel与实际sdist安装链路验证，不扩展项目Python支持、不加入syscall回退。S09-01b真实执行在后续独立切片实现。

[#96](https://github.com/Darrenus/tickwitness/issues/96)修复已在[PR #97](https://github.com/Darrenus/tickwitness/pull/97)完成下述远端验收，并由owner合并接受，merge `4e3691cccbe28f76b777814d1bac297082ed13c1`。所有测试／格式／构建／安装仍在远端；不新增Sprint容量、实际工时、外部尝试、release或研究权限。旧PR94归档和返回材料保持原样，新guide／runner／wheel的kit与sidecar单独记录；软件合并不解锁#24外部真人门，也不授权发行或自动替换旧归档。后续进入[S09-01b原预算前缀执行](sprint-09-status.md)。

## #96 远端兼容性验收记录

修复功能head为 `f6872189772ce7c93dec382a1a3fb2889662f356`，[Engineering 40860037902](https://github.com/Darrenus/tickwitness/actions/runs/40860037902) 与 [Documentation 40860037822](https://github.com/Darrenus/tickwitness/actions/runs/40860037822) 共13 checks全部通过。actual merge checkout为 `4f8780d6cc9ecdf573835d1dfeb40768e7634375`，与PR head分开。后续验收文档提交另有独立最新head检查，不冒充同一功能head。

六组Ubuntu 24.04／macOS 15 × Python3.12／3.13／3.14核心回归各 **3103 passed／112 optional-native skips**；Ubuntu 24.04及macOS 26／Python3.12原生回归各 **3212 passed／3 core-only skips／313 warnings**。Lint、276文件格式、126 source files严格类型检查与89文档／464本地链接通过；这些数字仅属于上述功能run，warnings原样保留。实际wheel／sdist安装闭环也通过，构建日志明确为先source distribution、再wheel from source distribution；源码包内脚本／guide／runner及实际新装wheel分别核验。所有项目runtime、格式、测试、构建与安装在远端，本机只做文本编辑、静态审阅、Git／gh控制与产物下载核查。

| 实际artifact（共同后缀 `4f8780d6cc9ecdf573835d1dfeb40768e7634375`） | 内容与状态 |
| --- | --- |
| `alpha-compatibility-core-…` | [12891665752](https://github.com/Darrenus/tickwitness/actions/runs/40860037902/artifacts/12891665752)：实际Python3.9.25启动拒绝与已安装core环境 |
| `alpha-core-…` | [12891860238](https://github.com/Darrenus/tickwitness/actions/runs/40860037902/artifacts/12891860238)：新手册、runner、archive、双系统命令及既有完整技术复验 |
| `alpha-ubuntu-24.04-…` | [12891217630](https://github.com/Darrenus/tickwitness/actions/runs/40860037902/artifacts/12891217630)：Linux原生作业内独立core verifier及实际checksum命令 |
| `alpha-macos-26-…` | [12891387227](https://github.com/Darrenus/tickwitness/actions/runs/40860037902/artifacts/12891387227)：Mac host实际checksum命令及独立core verifier |
| `alpha-compatibility-source-wheel-…` | [12892515095](https://github.com/Darrenus/tickwitness/actions/runs/40860037902/artifacts/12892515095)：实际sdist内runner／guide与真实3.9.25启动拒绝 |
| `alpha-source-wheel-…` | [12892370736](https://github.com/Darrenus/tickwitness/actions/runs/40860037902/artifacts/12892370736)：实际sdist内脚本／语料／guide／runner、wheel、可转交新归档与handoff |

六份实际报告均accepted=true；两个兼容报告的外部report与目录内report字节相同，四个alpha报告中的handoff及checksum对象与保存JSON内容一致。每个兼容产物14个、每个alpha产物1381个声明文件SHA均已逐项核验，保留30天。兼容报告中的实际Python为3.9.25，无TickWitness或native安装；core支持端为独立的Python3.12.3环境，有TickWitness、无native。每条兼容链路7份真实命令transcripts为3次成功的runtime／help探测，以及4次预期退出2；没有把模拟version_info的单元测试当成真实3.9。

| 实际核验 | 结果及范围 |
| --- | --- |
| 3.9直接启动 | 原样runner在新输出／已有输出两例均stderr单行`unsupported_python_version`、stdout空、exit2且无traceback；不存在kit和新submission，已有marker不变 |
| 3.9带监控启动 | 两例保持同一真实解释器与未改runner字节；harness先预载标准库`__future__`并明确记录，随后观察runner只导入`__future__`与`sys`，IO／worker／network tripwire保持启用；不声称Python冷启动加载自身标准库也完全无IO |
| 新handoff与手册 | 旧singular checksum字段等于新map.macos，map只有macos／linux；HANDOFF、guide与实际归档pin一致。四条安装链路分别在各自Linux或Mac host实际执行available的`shasum`与`sha256sum`，均正确digest为0／OK／空stderr，错误digest为1／FAILED；报告区分host与命令profile，不能单凭profile名宣称平台执行 |
| 信任与顺序 | 手册及handoff要求接收者先由owner独立渠道确认digest，再系统checksum，成功后解压／安装。CI内部处理自建可信归档，验证闭包与系统命令可用性，不认证独立渠道或模拟真实外部用户完整安装顺序 |
| 缺少发布API | 远端回归通过真实lookup路径注入缺少libc符号，验证新／已有目标与CLI均明确失败、无stage残留、无成功scorecard且原kit／目标字节不变；这是能力缺失回归，不是Alpine环境认证，没有新增raw syscall或覆盖式fallback |
| 既有语义及外部门 | 正常技术复验、重复核验、真实automation成功与失败留痕仍按旧受限合同；外部0／0／PENDING，八项scope仍false。没有原预算新slot、native研究、确认访问、发行或人类接受 |

首轮远端发现格式问题及两个期望字符串的ENdash lint，应用远端格式补丁并以相同Unicode转义保留实际消息。真实3.9直接运行已正常拒绝，但监控harness首次加载`__future__`时触发内部`_io`导入而被拦截；已通过harness预载标准库修正，并保留导入白名单、全部IO限制和明确的preloaded标记，没有放宽runner oracle。并行静态审阅及产物审计属于AI辅助，不替代外部真人复验。

新候选kit ID为 `dd6750d9b6eb27d10ba15ab10af098d2301f162b2a06a640fcd97c67a974af33`，wheel SHA为 `d5c3f69f6129f18d158b43215791a076dc82081f7bdfd9b00b9a5adcef390b4d`。本次Linux归档SHA为 `db233fc9b952aec04e57200cec0e80233ebe9a955bab34ccf1d0e7ffbb0e823c`，Mac归档为 `64f989e86e4910c8fb4aebeac2bc7e0bd3df2786f0d3507dd4146aefdac8abf3`；各自按实际sidecar核验，不把压缩归档SHA与kit内容身份混同。原PR94归档仍为 `0d70d81486c4286c0dbe60d2858ee6afcdd8a05d9f54c9c511b9101d7ef80f8f`，本轮未修改或替换；后续文档head的新归档也必须使用自己的实际pin。
