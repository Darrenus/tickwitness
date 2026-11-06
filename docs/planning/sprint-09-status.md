# Sprint 9 合法反例缩减状态

当前状态：2026-11-06（Asia/Singapore），owner 已合并 [PR #100](https://github.com/Darrenus/tickwitness/pull/100)，接受 merge `6e5d48db480e2e7f471c3f743c4d97eb18be88ee`。S09-03 已接受，#27 已关闭；进入 [Sprint 10](sprint-10-status.md)。下述日期与 run／artifact 记录保留各自的历史验收背景，外部真人复验仍 0 / PENDING。

更新：2026-11-05（Asia/Singapore）。Owner已合并[PR #99](https://github.com/Darrenus/tickwitness/pull/99)，接受merge `2aaef3e66edba87035a32779122d4858810da2c1`；S09-02已接受，#26已关闭，进入S09-03。此前#98接受merge `3577be7b07fba10a7da70cc95c2d3e887fcb06fd`、#97兼容性修复接受merge `4e3691cccbe28f76b777814d1bac297082ed13c1`与#95准备接受merge `a2c711861d1d776c78b4b5f5471f8afa388d390f`及历史run保留，S09-01已接受、#25已关闭。[S08-03 / #24](https://github.com/Darrenus/tickwitness/issues/24)真实外部复验仍0／PENDING，owner请求的AI自动化回传另记技术证据。原PR94转交归档与pin不变，无新release。

## 切片与验收门

| 故事／切片 | 范围 | 状态 |
| --- | --- | --- |
| S09-01a / #25 | 合法缩减recipe、完整必要前缀输入准备与独立重建 | Owner已合并 [PR #95](https://github.com/Darrenus/tickwitness/pull/95) 接受软件 |
| S09-01b / #25 | 在原协议共同预算下真实从头执行前缀，持久关联intent／attempt／outcome，审计账户／订单／显式在途状态 | Owner已合并[PR #98](https://github.com/Darrenus/tickwitness/pull/98)接受，#25已关闭 |
| S09-02 / #26 | 预算内自动局部缩减、候选边界取消、原false数值见证保持判定 | Owner已合并[PR #99](https://github.com/Darrenus/tickwitness/pull/99)接受，#26已关闭 |
| S09-03 / #27 | 原／缩减证据对比、实际首次分歧定位 | Owner 已合并 [PR #100](https://github.com/Darrenus/tickwitness/pull/100) 接受，#27 已关闭 |

原 [Sprint backlog](sprint-backlog.md#s9--合法反例缩减) 的14h／12h／8h专项估算和持续质量容量保持；01a／01b是同一14h故事的验收拆分，没有新增实际工时或重估容量。没有完整运行态checkpoint的现引擎不能用盘口快照代替策略、账户、队列和在途命令。

本轮依赖S08已接受的完整软件证据与稳定事件引用，可以在外部参与者准备期间独立实现；这不宣布S08整体完成、不豁免外部发行门，也不启动S10恢复资格。

## S09-01a 实现边界

合同见 [Reduction Input v1](../contracts/reduction-input-v1.md)。从完整已验证、已审计且真值false的development搜索见证中选择原candidate，绑定原bundle／report／protocol／claim／predicate／run／spec／assumptions。先验证整个source，再按原源数据重建完整候选情景，最后保留从原始首snapshot到真实through事件的连续前缀。只允许右端截短和冻结范围内减小该见证的额外延迟；focus左界仅控制审阅范围，完整warmup仍在执行输入内。

每个准备包只有manifest、recipe、materialization和normalized四个固定文件。独立verify需要原source evidence和显式preparation ID，重新计算所有语义和输入字节；重算外层hash无法把伪造descriptor变成有效准备。目标必须在原输入root之外，以原子不覆盖方式发布；提交前失败清理stage，提交后同步不确定保留完整目标并报错。

`prefix_context_id`表示计划输入上下文，`PreparedReplay`仅静态预检。所有回执明确 `native_replayed=false`、`initial_state_materialized=false`、`attempt_reserved=false`、`witness_preservation_verified=false`，必须从原点完整重放。原始预算已耗尽的portable见证不能恢复成空ledger、新增额度或授权实际缩减执行。截短EOF可能改变未成交、部分成交、在途取消和估值范围；实际完成度由01b真实运行审计，反例保持真值留待S09-02按原命题另行评价。

## 远端验收要求

全部项目测试、格式化、构建和安装在GitHub Actions远端CPU执行。本机仅编辑文本、静态审阅、Git／gh控制及下载产物读取。验收使用已提交的真实合成证据，而非自填成功报告：7事件identity正对照，focus4..6必须保留1..6且warmup1..3，延迟变化重算整个候选情景及prefix context；非法端点、删中间事件、快照／checkpoint注入和完整source损坏均拒绝。包移动后由安装的core-only wheel重算，禁native、网络与研究写入口，原始证据字节树和预算槽位不变。

Ubuntu与macOS的核心／原生回归、实际wheel及实际sdist重新构建安装、严格类型／格式／文档检查独立验收。受控发布故障只证明所观察边界，不认证历史durability或S10断电恢复。本切片不宣称真实运行态、缩减反例、最小性、研究收益、市场采用或外部复验。

## S09-01a 远端验收记录

功能代码 head 为 `471a5978dea6d9b135f56f250156210d80feab86`，[Engineering 40688297721](https://github.com/Darrenus/tickwitness/actions/runs/40688297721) 与 [Documentation 40688297566](https://github.com/Darrenus/tickwitness/actions/runs/40688297566) 共13 checks全部通过。actual merge checkout 为 `6ad72789de5b79a2c8471efc509fc7b5272c9875`，与PR head分开记录。后续验收文档提交有独立的最新head检查，不冒充相同功能head。

Ubuntu 24.04／macOS 15 × Python 3.12／3.13／3.14 六组合各 **3092 passed / 112 optional-native skips**；原生 Ubuntu 24.04 与 macOS 26／Python 3.12 各 **3201 passed / 3 core-only skips / 313 warnings**。Lint、275文件格式、126 source files严格类型检查与89文档／456本地链接均通过；这些数字属于上述功能run，warnings保留。全部项目执行在远端，本机仅编辑文本、静态审阅、Git／gh控制与下载产物读取。

| 实际 artifact（共同后缀 `6ad72789de5b79a2c8471efc509fc7b5272c9875`） | 内容与来源 |
| --- | --- |
| `reduction-input-core-…` | [12816445729](https://github.com/Darrenus/tickwitness/actions/runs/40688297721/artifacts/12816445729)：实际core wheel独立安装 |
| `reduction-input-ubuntu-24.04-…` | [12816218225](https://github.com/Darrenus/tickwitness/actions/runs/40688297721/artifacts/12816218225)：Linux原生作业内的独立core-only verifier |
| `reduction-input-macos-26-…` | [12816645843](https://github.com/Darrenus/tickwitness/actions/runs/40688297721/artifacts/12816645843)：macOS原生作业内的独立core-only verifier |
| `reduction-input-source-wheel-…` | [12816976157](https://github.com/Darrenus/tickwitness/actions/runs/40688297721/artifacts/12816976157)：实际sdist内脚本／语料与重建后安装的core wheel |

四份实际报告均为 `installed_reduction_input_acceptance_v1`、accepted=true，各含5个正例、17个拒绝场景和28份真实执行transcripts。每份保留目录的141个文件哈希已逐一核验，外部report与目录内report字节相同；包与诊断保留30天。五个preparation IDs跨四条安装链路相同，运行解释器身份按实际venv记录，不能把路径别名当环境分离。聚焦前缀preparation ID固定为 `f19cf603140cd1ff4c46b08a842619ee07f57dbba028062908c418a31f95c2ab`。

| 实际核验 | 结果与权限 |
| --- | --- |
| 完整与缩短输入 | 五例event_count／warmup_count分别为7／0、6／3、6／3、6／4、4／3；no-op保留原完整情景，focused-prefix逐字节等于其前6行，必要warmup前3行SHA为 `d757fbefd6807a1241cf3278414c187dff87beb6a6166fb4f57d894a5b9c3d39` |
| 变化与绑定 | 2e9→1e9ns重派完整候选情景，再截取；capture1..6及其它字段保留，受影响warmup、scenario／view／context身份实际变化；不声称收益单调或局部最小 |
| 移动与重复复算 | 删除复制的issuer／旧prepared目录，源包与准备包移位后guarded installed core复验；每个verify只将原回执status改为RECOMPUTED_PREPARATION_ONLY，其余完全一致 |
| 实际拒绝 | pre-IO tripwire得到8次unsafe request与2次confirmation拒绝；17个CLI拒绝含真实clean control／错误pin／端点／锚点／checkpoint、3个外层重hash语义攻击、2个缺件／字节篡改及2个confirmation拒绝，实际退出分别与预期2／3／5一致 |
| IO边界 | 远端回归覆盖精确role上限、canonical／unknown／nofollow／FIFO、源root与alias排除、原子不覆盖、发布竞争、提交前write／sync清理和提交后sync不确定完整保留；只证明观察到的边界 |
| 源与权限 | relocation后的两份完整source逐字节等于committed golden，CE仍只有原reservation1..3；guard禁止native import、SQLite／原stores、网络／worker及原预算写入口。9项flags精确，只有requires_full_prefix_replay=true，其余均false；无新attempt、运行态、checkpoint、缩减finding或confirmation权限 |

初轮远端发现格式／导入排序问题，应用远端生成补丁；CLI测试夹具抄写bundle pin漏了两位，按实际manifest SHA修正后原严格断言通过，没有放宽身份校验。并行交叉审阅与下载产物审计均为AI辅助，不冒充外部用户、人类领域接受或完整历史认证。

[PR #95](https://github.com/Darrenus/tickwitness/pull/95)仅交付S09-01a软件并由owner合并接受；当时#25因01b缺口继续打开，现已随owner合并#98接受01b而关闭。S09-02／03独立推进。#24继续打开，真实外部复验0／PENDING，现有PR94转交归档和pin不变；无新release、采用、访谈、实际工时或研究收益记录。

## S09-01b 实现与验收门

合同见[Reduction Execution v1](../contracts/reduction-execution-v1.md)，决策见[ADR 0029](../adr/0029-origin-prefix-execution.md)。真实执行仍从原始首snapshot开始，保留完整warmup与候选prefix，不向引擎注入静态盘口或旧账户状态。实际native结果经原有`evaluate_replay`独立核对全部输入、初始账户、fills／fees、订单生命周期、final账户和显式pending ledger。

执行前核对完整source/preparation及现有live ledger的全部已观察reservation prefix、候选intent／outcome和CAS。只允许同一源ExecutableProtocol拥有槽位，不从portable恢复空ledger、改protocol或返还预算；允许live追加合法suffix。记录中未观察的baseline outcome不伪造为“应当不存在”。原max_attempts、max_events、max_wall_seconds保持；本轮不延长既有搜索candidate journal或其campaign限额，也不实现S09-02的自动缩减循环。

每次运行先reserve，再持久绑定新reduction intent及4件准备CAS，确认可读后才构造worker。完整处理N个retained事件才允许成功state audit；EOF仍有挂单或命令可为INCOMPLETE，其估值保持原core规则的not_eligible，不变成反例保持。native失败、非法轨迹、超时、bind失败均消费原槽位；terminal发布异常／错ID只报不确定，不用failure覆盖已提交receipt、不重跑不退款。只读inspect重建准备与全部状态audit，缺件失败不修复、不占slot；reserved_unfinalized不是S10恢复授权。

状态边界固定为`after_native_run_before_dispose_v1`：这是engine.run返回后的账户／订单／显式在途投影，不能声称focus边界完整初态、engine.end前状态或可恢复checkpoint。native初始账户被核对且全部warmup真实回放；隐藏队列／RNG／策略内部状态不导出，cash lock只核非负及free+locked=total，不认证完整保证金分配算法。01a准备flags、真实run audit flags与当前只读inspect flags分别表达各自阶段，不改旧格式、engine语义或原source命题权限。

远端验收的新qualification协议从一开始冻结5槽：baseline1、两个实际search候选2／3，导出不可变source快照后再准备并执行两段前缀4／5，之后预算拒绝不构造引擎。旧3槽已耗尽golden保持原样。短prefix实际观察部分成交和取消在途的INCOMPLETE；较长prefix在cap5先发生第二次成交，随后显式OrderCancelRejected才清除在途取消，最终FILLED／pending为空。原固定语义按输入步先撮合再处理到期命令，不能从名义due time推断撤单必定先于下一条trade；精确oracle按该既有资格语义与实际轨迹修正，生产引擎不变。core-only安装只验证拒绝／审计边界，actual-native由Ubuntu、macOS与实际sdist安装链路单独执行，不能把fake port标成native。

实现和远端验收已完成，现已由owner合并#98接受，#25已关闭；S09-02／03另验，外部真人0／PENDING，无新release或研究收益声明。

## S09-01b 远端验收记录

功能head `5ebd9e8dbcb190849853076a2af15ff7042f3add` 的[Engineering 41015920228](https://github.com/Darrenus/tickwitness/actions/runs/41015920228)与[Documentation 41015920219](https://github.com/Darrenus/tickwitness/actions/runs/41015920219)共13 checks全部通过。实际merge checkout为 `835429bfca761443eba8bfd6467c7a31095aa0e7`，与PR head分别记录；后续验收文档提交有独立的最新head检查，不冒充相同功能head。

Ubuntu 24.04／macOS 15 × Python 3.12／3.13／3.14六组core各 **3156 passed / 112 optional-native skips**；Ubuntu 24.04与macOS 26／Python 3.12的native各 **3265 passed / 3 core-only skips / 313 warnings**。Lint、284文件格式、129 source files严格类型检查、91文档／470本地链接通过。数字属于上述功能run，warnings保留。全部项目测试、运行、格式化、构建和安装在远端CPU执行；本机只有文本编辑、静态审阅、Git／gh控制及产物读取。

| 实际artifact（共同后缀 `835429bfca761443eba8bfd6467c7a31095aa0e7`） | 安装与审计范围 |
| --- | --- |
| `reduction-execution-core-…` [12959194347](https://github.com/Darrenus/tickwitness/actions/runs/41015920228/artifacts/12959194347) | 独立core wheel，native_execution=false；52个声明文件哈希、9份实际transcript |
| `reduction-execution-ubuntu-24.04-…` [12959584304](https://github.com/Darrenus/tickwitness/actions/runs/41015920228/artifacts/12959584304) | 实际native wheel＋独立core verifier；277个声明文件哈希、30份实际transcript |
| `reduction-execution-macos-26-…` [12959607587](https://github.com/Darrenus/tickwitness/actions/runs/41015920228/artifacts/12959607587) | macOS实际native wheel＋core verifier；277个声明文件哈希、30份实际transcript |
| `reduction-execution-source-wheel-…` [12960201647](https://github.com/Darrenus/tickwitness/actions/runs/41015920228/artifacts/12960201647) | 实际sdist内脚本与语料、重建安装的native／core wheel；277个声明文件哈希、30份实际transcript |

四份报告均为`installed_reduction_execution_acceptance_v1`且accepted=true；内外report字节相同，声明哈希逐一静态核验。清单不自含`artifact-files.json`：core目录实际53文件，native各278文件，另各有外部report。Core退出分布0×5／2×1／4×1／5×2；native各0×24／2×2／4×1／5×2／8×1，实际退出与expected全部一致，成功stderr和拒绝stdout均空。Producer实际native版本1.231.0，verifier未安装native；venv prefix与base prefix分别核对，macOS `/tmp`／`/private/tmp`别名不当作环境隔离。产物与诊断保留30天。

| 实际核验 | 观察与范围 |
| --- | --- |
| 原协议共同预算 | qualification在第一次执行前冻结max_attempts=5、max_events=1000、max_wall_seconds=60；campaign只允许2次搜索evaluation。真实slot1为baseline，2／3为原search，4／5为新reduction；before前三槽与after前三槽exact相等。旧三槽golden与其复制包不变，不能由portable证据创建或补建live预算 |
| A：完整必要前缀 | input／processed均4，原refs1..4，warmup1..3；初始cash10000／pos0／orders空。最终fill1／fee1／pos1、订单剩1／PENDING_CANCEL、cap3发出的command-1在途，EOF INCOMPLETE且valuation not_eligible |
| B：追加事件后的真实路径 | input／processed均6，原refs1..6、warmup1..4，前4行与A逐字节相同；独立从cash10000／pos0重放。fills在cap3／5各1、fee各1；cap5的3s先OrderFilled且command-1仍pending，随后同cap5／同3s的OrderCancelRejected才清空pending。最终FILLED／剩0／pos2／fee2、open／pending空，COMPLETED；没有OrderCanceled |
| 会计与边界 | A终cash9999=free9699+locked300，B终cash9998=free9798+locked200；实际余额与独立fills／fees／订单审计一致。这里只认证非负与分量守恒，不认证另一套margin lock算法。边界始终after_native_run_before_dispose_v1，未导出focus初态、pre-engine-end或隐藏可恢复state |
| 持久化与只读复验 | intent与4件preparation先于engine可读；实际result／audit／receipt绑定CAS。独立core guard禁止native、worker、reserve、publish、旧研究stores、SQLite及网络，重新构造全部audit，字节树不变，inspect本身不再次执行或消耗槽位 |
| 实际拒绝 | 5槽后再次run真实退出8且没有slot6；改变focus_state_captured并重算audit／receipt／outcome外层哈希仍inspect退出2，原结果不变。两次confirmation CLI退出5，应用pre-IO tripwire另核2次；旧源配missing ledger退出4、existing empty ledger退出2，无恢复槽位 |
| 受控故障回归 | core domain／application／ledger测试独立覆盖错输入／漏warmup、账户／成交／订单／pending矛盾、fake completed、bind／native／timeout失败、中断保留consumed unfinalized、晚publish／错ID不覆盖成功receipt。这些不冒充installed native故障注入、物理断电或S10恢复认证 |

Ubuntu实际原protocol ID为 `b632cb5786b96056fb1ff5f574808a5d18c266ca31820f2053aa2a1046ab54a2`，source bundle为 `dda14f172427e447b60f1ce56f60f87807c90bef40fc3efb10dca196ea353ea9`。A run／audit分别为 `97593d9b1e2885083cbc37da8e2aa4ce80a838732a977044f2599a8d88614bec`／`b0c70e8c96b058b50814a5964bb1fa27040010fc57c290c3f952c26b9ae3f27a`；B分别为 `439d8eb9465886cc586232ea59e59da8ca5e83d3355fd3c6bbccb390ff1a45e2`／`0ed3bee4a14bd9a9c6ee664b06973b5f4551f271810516f29ca8b4d98a94d8b4`。各安装路径的nonce／时间与source绑定会产生不同run／preparation IDs，只核各自完整内容链，不要求跨生命周期同ID。

远端迭代暴露并修正了pin抄写、结构无效的负例夹具、open_orders与account订单字段位置，以及B被预设为撤单成功的错误oracle。B修正依据既有时钟资格与两平台实际轨迹：名义due2.5s不是独立推进时钟，cap4仅2.000000001s，下一步cap5 trade先撮合再处理到期撤单。生产引擎与原协议预算均未放宽；严格oracle新增fill-before-rejection与pending清理顺序检查。

[PR #98](https://github.com/Darrenus/tickwitness/pull/98)交付S09-01b软件，已由owner在2026-10-30合并接受，merge `3577be7b07fba10a7da70cc95c2d3e887fcb06fd`；#25已关闭。S09-02自动缩减／数值保持与S09-03对比另验。外部真人复验0／PENDING，AI交叉审阅／CI／owner合并不充当外部真人尝试；原PR94转交归档及pin不变，无新release、实际工时、采用或研究收益记录。

## S09-02 实现与验收门

合同见[Reduction Search v1](../contracts/reduction-search-v1.md)，决策见[ADR 0030](../adr/0030-bounded-local-reduction.md)。原source finding只能证明其原冻结eligible集合中的false条件见证，不能授予baseline翻转或新输入量词域权限。本步独立评价原authority复制的numeric criterion在实际合法prefix终点是否仍为false，不修改01a准备和01b执行／state-audit的既有flags。

固定focus，按延迟减半、末尾移到前一真实事件的顺序尝试邻域；每次重新构建完整warmup并从原点真实回放。只有PRESERVED且(retained event count,delay)严格下降才更新best并重启邻域。NOT_PRESERVED与NOT_EVALUABLE分别保留；未知或未执行点不当作true。初始best明确引用SOURCE_WITNESS，既不占新slot，也不算新简化或新native执行。即便检查完当前邻域，也只报告已知保持简化及检查范围，不认证局部／全局最小。

所有执行继续使用原ExecutableProtocol／live ledger。新plan的step与elapsed准入限制只额外收紧，不增加原attempt／events／单次timeout、不重开旧search campaign资源预算。Elapsed和取消都在候选边界检查；不宣称总时间／总storage硬限额或S10强制kill。当前有界attempt可先提交，再停止新dispatch。Dispatch先持久化nonce，随后关联原attempt／intent／outcome和独立assessment；重跑已有execution只读inspect，不续跑、退款、修复或覆盖。晚发布不确定必须可见，之前的best与已提交结果保留。

远端资格从第一次执行前冻结新的合成protocol criterion lt(-1.5 USD)及原预算11槽；不修改旧golden或真实source条件。Baseline与原search占1..3；pre-start取消占0槽；受控hook在第一次真实native返回后请求取消，占slot4并保留实际结果；正式7次邻域执行占5..11，实际依次NOT_PRESERVED／PRESERVED／NOT_PRESERVED／PRESERVED／NOT_PRESERVED／PRESERVED／NOT_EVALUABLE。最后沿用同原source／ledger的新plan自然预算停止，没有slot12或engine构造；实际run与产物审计见下文验收记录。

Core wheel、Ubuntu／macOS native wheel与实际sdist安装链路分别保存原始journal、CAS、执行／状态／保持判定和transcripts；独立core-only inspector禁止native与预算写入，重算而不信任保存的flags。#26已随owner合并#99接受关闭；S09-03、S10、外部真人PENDING及发行门均另验。

## S09-02 远端验收记录

功能head `0bca087c7c113ccb7fab30ede9a7a25205d0d994` 的[Engineering 41274239441](https://github.com/Darrenus/tickwitness/actions/runs/41274239441)与[Documentation 41274239404](https://github.com/Darrenus/tickwitness/actions/runs/41274239404)共13 checks全部通过。实际merge checkout为 `6fdb0a5e3f53048133fab14c543fbee99bc955a4`，与PR head分别记录；后续验收文档提交须另核最新head，不能冒充本次功能run。

Ubuntu 24.04／macOS 15 × Python 3.12／3.13／3.14六组core各 **3256 passed / 112 optional-native skips**；Ubuntu 24.04与macOS 26／Python 3.12的native各 **3365 passed / 3 core-only skips / 313 warnings**。Lint、296文件格式、135 source files严格类型检查、93文档／483本地链接通过。以上数字属于功能run，warnings保留。全部项目运行、测试、格式、构建和安装在远端CPU执行；本机只有文本、Git／gh控制及静态产物读取。

| 实际artifact（共同后缀 `6fdb0a5e3f53048133fab14c543fbee99bc955a4`） | 安装与静态审计范围 |
| --- | --- |
| `reduction-search-core-…` [13070491989](https://github.com/Darrenus/tickwitness/actions/runs/41274239441/artifacts/13070491989) | core wheel；49个声明文件哈希、10份真实transcript，native_execution=false；只验证拒绝／guard，不冒充成功缩减 |
| `reduction-search-ubuntu-24.04-…` [13070837445](https://github.com/Darrenus/tickwitness/actions/runs/41274239441/artifacts/13070837445) | 实际native wheel＋独立core verifier；503个声明文件哈希、60份真实transcript |
| `reduction-search-macos-26-…` [13071495265](https://github.com/Darrenus/tickwitness/actions/runs/41274239441/artifacts/13071495265) | macOS实际native wheel＋独立core verifier；503个声明文件哈希、60份真实transcript |
| `reduction-search-source-wheel-…` [13070534027](https://github.com/Darrenus/tickwitness/actions/runs/41274239441/artifacts/13070534027) | 实际sdist内脚本及语料＋本轮构建并安装的native／core wheel；503个声明文件哈希、60份真实transcript |

四份报告均为`installed_reduction_search_acceptance_v1`且accepted=true，内外report同字节，逐文件SHA与exact文件集合静态核对。清单不自含`artifact-files.json`：core records共50文件，native各504文件，外部report另计。Core实际退出为0×4／2×1／4×1／5×4；native各0×51／2×2／4×1／5×4／8×2，actual均等于expected。两次budget8为结构化stdout report，其他拒绝在stderr；所有非预期stream均空。Producer实际native版本1.231.0，独立verifier未装native；core profile的producer／verifier实际共用同一core venv，不冒充两个独立环境。按真实prefix／base_prefix核对venv，macOS的`/tmp`／`/private/tmp`只作同一路径别名。产物和诊断保留30天。

| 实际核验 | 观察与边界 |
| --- | --- |
| 原协议与source | 首次运行前冻结criterion lt(-1.5 USD)与max_attempts=11／max_events=1000／max_wall_seconds=60。Baseline1、原search2／3后导出source；原已观察前三槽、intent／outcome／CAS与source逐字节不变，合法新增suffix到11；不恢复空ledger、不修改旧3槽golden或PR94手交包 |
| 原false来源 | 原search实际0／2e9两点的值为-2／-1；原finding仅ordinal3为false见证。Bootstrap的ProtocolEvaluation保留，reducer不另发baseline／source-claim flip、不把新delay插回原冻结eligible集合 |
| pre-start取消 | 正式cancel marker在任何dispatch前提交，cancelled stop、0新attempt；初始best仍为SOURCE_WITNESS，不虚构新运行或简化 |
| 真实run后取消 | controlled helper先委托真实SubprocessReplayAdapter，返回后／协调器提交前通过正式API发cancel；slot4实际NOT_PRESERVED结果先持久完成，再候选边界停止。不是native kill或外部真人操作 |
| 主循环 | 固定focus4，slot5..11实际依次(7,1e9)NOT_PRESERVED、(6,2e9)PRESERVED、(6,1e9)NOT_PRESERVED、(5,2e9)PRESERVED、(5,1e9)NOT_PRESERVED、(4,2e9)PRESERVED、(4,1e9)NOT_EVALUABLE；均实际回放完整origin前缀，保留warmup1..3 |
| 数值与会计 | 三个P的实际值-1、1fill／fee1／position1、订单CANCELED；三个NP为-2、2fills／fee2／position2、订单FILLED。最后NE为INCOMPLETE／PENDING_CANCEL、remaining1、command-1在途，truth/value均null；不将未知当true或false。初始cash10000／position0／orders空，最终账户与原始fills／fees／订单审计一致 |
| 既有时钟语义 | 1e9路径cap5的trade先成交，再显式OrderCancelRejected清除pending；2e9路径cap4处理撤单。完整input receive/native时钟逐点核对，未注入额外EOF时钟或改变生产引擎顺序 |
| best与停止 | best由7个事件缩到4个，delay仍2e9，origin=REDUCTION_RUN。当前邻域检查完以neighborhood_checked停止，但未知邻居保留，local／global minimum flags均false |
| 耗尽与不可重跑 | 同原source／protocol／live root的新plan持久dispatch后自然触发原预算拒绝（exit8），报告STOPPED／original_attempt_budget_exhausted，无slot12、link／result或engine。重复run只inspect、重复freeze不reset，terminal cancel不改stop；原数据字节树不变 |
| 独立只读核验 | 独立core guard禁止native／worker、reserve／publish、旧研究stores、SQLite／网络与journal写入口；重新认证完整source、exact plan、greedy顺序和每个实际receipt／state-audit／assessment，核对dispatch nonce、原reservation/link、intent与CAS。重hash且自洽改值的伪assessment仍实际inspect退出2；原journal未受影响 |
| 故障回归 | 远端domain／app／store／CLI覆盖三值／exact threshold、非法轨迹与owner/CAS绑定、预算／步数／elapsed、in-flight取消、KeyboardInterrupt、晚publish／错ID、只读重跑、stop／cancel／assessment篡改与confirmation pre-IO。离线端口夹具另标，不冒充原生故障或物理断电认证 |

Ubuntu本次原protocol为 `caff3df37816f27c6e80157ae8bcb26490465553538ad95ca07194c1330f7cb8`，source bundle为 `034f4000b0f09d3d95daaf3f2bfe1cd5c650244b47cc4e9cbe080d76b3e74057`。Best run为 `d669f3c6911e862dcc9c83740cfee4c2b593b2a482ffc73274a58632051a26ff`，assessment为 `4dcb68e5164edf2ca79a4e4b5a6f46ae2fc93503684563323c2c2395006c8243`。各安装路径的nonce／时间和source bindings不同，核各自完整内容链，不要求跨生命周期同run ID。

远端迭代先发现pytest同名测试模块导致collection失败，以及格式／类型问题；修正后再实际执行。手续费歧义负例误把独立夹具与golden输入混合，被严格字节断言拒绝，现完整沿用该夹具的input／spec／result并增加实际prefix bytes／data SHA核对；NOT_EVALUABLE/null oracle与生产校验未放宽。全部修正经后续远端完整检查。

[PR #99](https://github.com/Darrenus/tickwitness/pull/99)交付S09-02软件，已由owner于2026-11-05合并接受，merge `2aaef3e66edba87035a32779122d4858810da2c1`，#26已关闭。取消和elapsed仅候选间协作／准入限制，不宣称硬总deadline、总storage额度、native进程组kill或S10恢复。S09-03对比、外部真人0／PENDING与发行门另验；CI、AI交叉审阅和owner合并不替代真人复验。无新release、实际工时、采用或研究收益记录。

## S09-03 实现与验收门

合同见[Reduction Comparison v1](../contracts/reduction-comparison-v1.md)，决策见[ADR 0031](../adr/0031-reduction-evidence-comparison.md)。比较原false scenario见证与一个已提交的实际reduction run；原见证不是baseline。先完整复验source与原live ledger已观察前缀，再重新派生原输入及缩减preparation，重审两版实际result／receipt／state及原criterion。保持、不保持与不可评价分别输出，未知仍为null。

审阅者可定位原点保留前缀、必要warmup、固定focus、实际移除尾部事件，以及保留事件的接收时间变化。Raw与既有business投影逐通道定位首次差异，保留JSON pointer、稳定source引用和raw值；各通道的ordinal不是全局时间序，不发因果或全局最早结论。两版EOF及估值终点独立展示，不把不同观察范围的数值差当作可比收益效果。

Compare输出严格canonical JSON导出或同一重算结果的Markdown视图，verify以显式comparison／source pins在原证据上独立重算。重新hash保存的比较报告不能替代真实结果。整个比较／复验过程无worker、reserve、写入、补跑、退款或修复，也不扩原finding量词域或认证最小性；S09-02旧flags不改。

远端installed资格复用S09-02原11槽内已实际执行的original与8条reduction结果（7main＋1取消后结果），在耗尽之后由独立core-only verifier比较／复验，原source、ledger和上游包字节不变。Core安装只验证拒绝边界，不伪造成功native证据。Ubuntu／macOS及实际sdist内脚本／语料对安装wheel的三条正例链路、Markdown、语义伪造、缺件／CAS损坏和confirmation pre-IO均已实际验证，见下文验收记录。

#27保持打开直到owner接受；原8h预测、持续质量预算与外部真人0／PENDING不变。没有新release、采用、实际工时或研究收益声明。

## S09-03 远端验收记录

功能head `09fdd5c8f26c17c3eeb297b5f55c66bd904a2123` 的[Engineering 42052172007](https://github.com/Darrenus/tickwitness/actions/runs/42052172007)与[Documentation 42052171976](https://github.com/Darrenus/tickwitness/actions/runs/42052171976)共13 checks全部通过。实际merge checkout为 `6edffcfa67b5ecc28a09595d9eeee92a347f59de`，与PR head分别记录；后续验收文档提交须独立核最新head，不冒充本次功能run。

六组Ubuntu 24.04／macOS 15 × Python 3.12／3.13／3.14 core各 **3345 passed / 112 optional-native skips**；Ubuntu 24.04与macOS 26／Python 3.12的native各 **3454 passed / 3 core-only skips / 313 warnings**。Lint、303文件格式、138 source files严格类型检查、95文档／497本地链接通过。以上数字属于功能run，warnings保留。全部项目运行／测试／格式／构建／安装在远端CPU，本机仅静态文本、Git／gh控制与产物读取。

| 实际artifact（共同后缀 `6edffcfa67b5ecc28a09595d9eeee92a347f59de`） | 安装与静态审计范围 |
| --- | --- |
| `reduction-comparison-core-…` [13426409527](https://github.com/Darrenus/tickwitness/actions/runs/42052172007/artifacts/13426409527) | core wheel；60个声明文件哈希、6份实际transcript；只证明拒绝／guard，不冒充正例 |
| `reduction-comparison-ubuntu-24.04-…` [13429165181](https://github.com/Darrenus/tickwitness/actions/runs/42052172007/artifacts/13429165181) | 已实际执行的Ubuntu native源记录＋core-only比较／复验；894个声明哈希、32份transcript |
| `reduction-comparison-macos-26-…` [13428151877](https://github.com/Darrenus/tickwitness/actions/runs/42052172007/artifacts/13428151877) | 已实际执行的macOS native源记录＋独立core-only比较／复验；894个声明哈希、32份transcript |
| `reduction-comparison-source-wheel-…` [13428358094](https://github.com/Darrenus/tickwitness/actions/runs/42052172007/artifacts/13428358094) | 实际sdist内脚本／语料＋本轮构建并安装的wheel；894个声明哈希、32份transcript |

四份新报告均为`installed_reduction_comparison_acceptance_v1`且accepted=true，内外report同字节。Core records共61文件，带原生源证据的各895文件，外部report各另计；仅根`artifact-files.json`不自包含，嵌套上游manifest必须保留在新清单中。逐文件SHA与exact文件集合均静态核对。上游core的49个／正例的503个声明哈希、两份上游report和manifest绑定也分别重验，原包字节不变。

实际退出均等于expected：core为0×2／2×1／4×1／5×2；三个正例profile各0×21／2×5／3×1／4×3／5×2。所有成功stderr及拒绝stdout为空；新CLI的JSON成功输出为无尾换行的canonical bytes，另有1份实际Markdown及其真实transcript，runtime／tripwire／ledger辅助命令按各自JSON契约保留。解释器runtime、identity文件和report逐项匹配，比较解释器均为installed core、native_distribution=null；venv prefix与base prefix按真实路径核对，macOS `/tmp`与`/private/tmp`只作别名。

新比较报告的native_execution／native_replayed／native_execution_performed在**所有profile均false**，new_attempts／new_native_runs均0。三个正例的upstream_native_evidence_reused=true，只表示重新审计同作业内已真实执行的原生记录。脚本的8次复用计目标reduction results（7main＋1取消后结果），原false scenario见证另行重审，不是新增8次原生执行或完整全局历史认证。

| 实际核验 | 观察与边界 |
| --- | --- |
| 原预算与source | 上游qualification首次执行前冻结lt(-1.5 USD)、原11槽／1000events／60s。比较开始时槽1..11已耗尽，before／after原reservation、intent／outcome／CAS与source字节全相同，无slot12；guard禁止reserve、publish、native／worker、旧研究stores、SQLite／网络，ledger必须create=False |
| 两版实际证据 | 每个比较重新绑定完整source、原scenario receipt/result/evaluation、目标reduction receipt/result/state-audit/assessment及原intent／slot／nonce；canonical report ID与独立verify输出精确一致。完整source之外未观察的历史仍未认证，原见证不是baseline |
| 七点实际结果 | 原false scenario完整7事件、delay2e9、value=-1。目标点依次(7,1e9)NP、(6,2e9)P、(6,1e9)NP、(5,2e9)P、(5,1e9)NP、(4,2e9)P、(4,1e9)NE；both_false_witnesses分别false／true／false／true／false／true／null，最后truth/value仍null |
| 最佳已知见证审阅 | 目标4事件／delay2e9保持false；retained refs1..4、warmup1..3、review4，实际移除cap5 trade／cap6 delta／cap7 delta。Removed payload保留原情景2e9派生时钟，行SHA不含LF；完整实际事件对象可在Markdown和JSON审阅，不用capture编号相减推测数量 |
| 实际首次差异 | 最佳案例raw／business的input首差为`/input_trace/4`：原cap5 trade存在，缩减侧缺失，两侧source refs分别原cap5与null。1e9路径raw首差落在cap4时钟；business保留真实订单变化和第二次成交，其中cap5填单在cancel rejection之前。各通道独立ordinal与JSON顺序，不称全局最早或因果 |
| EOF与数值范围 | 两版各自完整输入、through、执行状态、completeness、valuation_status和mark保留；相同事件数也不授予相同运行条件。较短EOF不是长run的共同中间状态，shared_terminal_state_captured与numeric_effect_comparable均false，无收益差额效应或baseline flip |
| 独立导出与审阅 | 7份主比较export分别实际verify，重复best export同字节；实际Markdown包含comparison／source／两run身份、输入覆盖、移除内容、时钟变化、原数值条件、raw/business差异及scope。比较pin哈希report而非envelope；strict canonical／有界常规JSON输入验证，非法编码／ID在source或ledger IO前拒绝 |
| 三类语义伪造 | 分别自洽改写数值保持条件、被移除事件与相应行SHA、business首次差异，并重算comparison ID；三者实际verify均exit2。原证据不修改，saved flags与自算hash不能替代独立source/run重建 |
| 缺件与确认拒绝 | 错source pin实际exit2，缺run／实际audit CAS分别exit4；给audit CAS附加空格则实际完整性exit3。负例保留独立副本，原记录不修复。两个CLI confirmation拒绝exit5，应用pre-IO helper另证2操作拒绝；core只验证这些拒绝与guard边界 |
| 回归范围 | 远端覆盖合法非1起点capture与source line分离、非法同流gap拒绝、no-op、保留区时钟变化、native ID业务映射、exact原false阈值、P／NP／NE、会计／slot／环境／绑定攻击、读取期间变化、报告上限与编码。离线一致性夹具明确标记，不能代替本轮已有原生记录的installed资格 |

Ubuntu本次source bundle为 `1e7300b79c48ca8629064166d730f1b5b9d2199f469cfccde2d9ac798e2f5780`；best comparison为 `a7dd027a32981e3eff989721eae7e9c1e043eef71d734d810fb7c7c9f4c993e0`，对应实际reduced run `2f8156d69686cb3c963634e04b0d9c4d6600090558cafd60649d7a9f58349d3c`。不同安装生命周期的nonce／run／source ID不同，逐一核各自实际字节链与相同有范围观察，不要求跨生命周期同ID。

首轮远端发现导入／格式问题，应用其实际生成补丁；一个gap引用夹具在源冻结阶段被既有预检拒绝，现以合法连续capture10..16测试line与capture分离，另以负例明确拒绝gap，生产校验未放宽。原生3454个测试完成后，旧15分钟CI总窗口不足以稳妥容纳整套安装资格，因此只把native-replay的CI作业窗口改为20分钟；原协议11槽／1000events／每次60s不变，旧取消run不冒充安装资格通过。

[PR #100](https://github.com/Darrenus/tickwitness/pull/100)交付 S09-03 软件，已由 owner 于 2026-11-06（Asia/Singapore）合并接受，merge `6e5d48db480e2e7f471c3f743c4d97eb18be88ee`，#27 已关闭。S10 恢复／强取消、外部真人 0／PENDING 和发行门分别验收；CI、AI 静态审阅及 owner 合并不替代真人复验。原 PR94 手交包与 golden 不变，无新 release、实际工时、市场采用或研究收益记录。
