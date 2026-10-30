# Sprint 9 合法反例缩减状态

更新：2026-10-30（Asia/Singapore）。Owner 已合并 [PR #97](https://github.com/Darrenus/tickwitness/pull/97)，接受merge为 `4e3691cccbe28f76b777814d1bac297082ed13c1`，#96兼容性修复接受后进入S09-01b。S09-01a已由[PR #95](https://github.com/Darrenus/tickwitness/pull/95) merge `a2c711861d1d776c78b4b5f5471f8afa388d390f`接受；其功能基线及历史run保持原值。[S08-03 / #24](https://github.com/Darrenus/tickwitness/issues/24) 真实外部复验仍0／PENDING，owner请求的AI自动化回传另记技术证据。原PR94转交归档与pin不变，无新release。

## 切片与验收门

| 故事／切片 | 范围 | 状态 |
| --- | --- | --- |
| S09-01a / #25 | 合法缩减recipe、完整必要前缀输入准备与独立重建 | Owner已合并 [PR #95](https://github.com/Darrenus/tickwitness/pull/95) 接受软件 |
| S09-01b / #25 | 在原协议共同预算下真实从头执行前缀，持久关联intent／attempt／outcome，审计账户／订单／显式在途状态 | 13项远端检查通过，[PR #98](https://github.com/Darrenus/tickwitness/pull/98)待owner接受，#25继续打开 |
| S09-02 / #26 | 预算内自动局部缩减、取消、反例保持判定 | Planned，不能以准备好输入代替实际反例保持 |
| S09-03 / #27 | 原／缩减证据对比、实际首次分歧定位 | Planned，不能将输入字节差异提升为业务因果 |

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

[PR #95](https://github.com/Darrenus/tickwitness/pull/95) 仅交付S09-01a软件，现已由owner合并接受。#25因01b实际执行与状态验收未实现而继续打开；S09-02／03独立推进。#24继续打开，真实外部复验0／PENDING，现有PR94转交归档和pin不变；无新release、采用、访谈、实际工时或研究收益记录。

## S09-01b 实现与验收门

合同见[Reduction Execution v1](../contracts/reduction-execution-v1.md)，决策见[ADR 0029](../adr/0029-origin-prefix-execution.md)。真实执行仍从原始首snapshot开始，保留完整warmup与候选prefix，不向引擎注入静态盘口或旧账户状态。实际native结果经原有`evaluate_replay`独立核对全部输入、初始账户、fills／fees、订单生命周期、final账户和显式pending ledger。

执行前核对完整source/preparation及现有live ledger的全部已观察reservation prefix、候选intent／outcome和CAS。只允许同一源ExecutableProtocol拥有槽位，不从portable恢复空ledger、改protocol或返还预算；允许live追加合法suffix。记录中未观察的baseline outcome不伪造为“应当不存在”。原max_attempts、max_events、max_wall_seconds保持；本轮不延长既有搜索candidate journal或其campaign限额，也不实现S09-02的自动缩减循环。

每次运行先reserve，再持久绑定新reduction intent及4件准备CAS，确认可读后才构造worker。完整处理N个retained事件才允许成功state audit；EOF仍有挂单或命令可为INCOMPLETE，其估值保持原core规则的not_eligible，不变成反例保持。native失败、非法轨迹、超时、bind失败均消费原槽位；terminal发布异常／错ID只报不确定，不用failure覆盖已提交receipt、不重跑不退款。只读inspect重建准备与全部状态audit，缺件失败不修复、不占slot；reserved_unfinalized不是S10恢复授权。

状态边界固定为`after_native_run_before_dispose_v1`：这是engine.run返回后的账户／订单／显式在途投影，不能声称focus边界完整初态、engine.end前状态或可恢复checkpoint。native初始账户被核对且全部warmup真实回放；隐藏队列／RNG／策略内部状态不导出，cash lock只核非负及free+locked=total，不认证完整保证金分配算法。01a准备flags、真实run audit flags与当前只读inspect flags分别表达各自阶段，不改旧格式、engine语义或原source命题权限。

远端验收的新qualification协议从一开始冻结5槽：baseline1、两个实际search候选2／3，导出不可变source快照后再准备并执行两段前缀4／5，之后预算拒绝不构造引擎。旧3槽已耗尽golden保持原样。短prefix实际观察部分成交和取消在途的INCOMPLETE；较长prefix在cap5先发生第二次成交，随后显式OrderCancelRejected才清除在途取消，最终FILLED／pending为空。原固定语义按输入步先撮合再处理到期命令，不能从名义due time推断撤单必定先于下一条trade；精确oracle按该既有资格语义与实际轨迹修正，生产引擎不变。core-only安装只验证拒绝／审计边界，actual-native由Ubuntu、macOS与实际sdist安装链路单独执行，不能把fake port标成native。

实现和功能head远端验收已完成，owner接受待定；#25保持打开，S09-02／03另验，外部真人0／PENDING，无新release或研究收益声明。

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

[PR #98](https://github.com/Darrenus/tickwitness/pull/98)交付S09-01b软件，待owner审阅接受；#25继续打开。S09-02的自动缩减与反例保持、S09-03对比另验。外部真人复验0／PENDING，AI交叉审阅／CI／owner合并不充当外部真人尝试；原PR94转交归档及pin不变，无新release、实际工时、采用或研究收益记录。
