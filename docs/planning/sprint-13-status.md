# Sprint 13 执行信任与隔离状态

## 当前接受与S13-03准备：2026-11-27

Owner已在本次项目对话中明确回复“接受”，接受精确提交`89e12eb3e2e371ea7a4939f277bab57cd3c7843e`及已披露限制。[PR115](https://github.com/Darrenus/tickwitness/pull/115)按正常matching-head流程实际合并为`40aede39b4d7b051b00b0dd604738e736d3f4c25`，由Darrenus于2026-11-27 17:58:53 Asia/Singapore完成；合并树与接受源码相同。必需documentation／engineering通过；实际18 SUCCESS／1非必需legacy REFUSED–FAILURE／0pending保留。Owner接受这一有界交付及已披露例外，不把失败改称通过，不构成对后续PR的全局豁免。

S13-02／#38的软件交付已接受；参考资格仍仅QUALIFIED_REFERENCE_ONLY，固定24PASS／本轮24+历史21=45及CLOSED63回传不变。产品M1未集成且DISABLED，M2不支持。独立真人安全复核NOT_PERFORMED，reviewer UNASSIGNED；外部真人复验0/0/PENDING、#24 OPEN。

S13-03／#39开始内部准备切片：[安全审阅与能力降级包](../security/s13-03-review-and-degradation.md)及[采用观察快照](s13-03-adoption-observation-2026-11-27.md)。候选材料不等于真人审阅或采用；整体故事仍OPEN／in-progress，依赖参与者的工作不记Ready／Done。原8h暂分6h内部准备及远端检查、2h有真实输入后响应，均为计划分配而非实际工时；S13仍10+16+8=34h，持续质量容量不变。

本轮只整理既有证据和关闭规则，没有运行探针、研究、replay、旧ACK/export或AWS启动；原协议预算、5/8/11、golden、PR94与全部封存记录不改。新文档提交的检查须单独记录，不能继承89或合并提交的绿灯。

## 接受之前的状态快照（历史）

下列Draft、owner PENDING、#38 in-progress和#39 Planned均为接受前记录，已由上面的真实接受／合并及当前切片取代；旧实测结果、失败和未知不回写。

当前状态，2026-11-27 Asia/Singapore：[v3实机与后续只读收证](../security/ec2-reference-recovery-v3-evidence-2026-11-27.md)
已记录固定run0004在资格源码`908d56db32439f38686346687a5b43239b1b7264`上的完整24项PASS，
本轮24／历史21／累计45；实际成功report、持久终态和原boot receipt相符，
仅为 **QUALIFIED_REFERENCE_ONLY**。原handoff已过期，controller实际退出74，
qualifier／export各退出0、ACK不存在；后续收证不把该失败改写为已确认ACK。

独立只读readback已CLOSED，63文件索引SHA256
`24172392588984a1c56fa314f029c630d7ba92bb29a8f60a29d39440c0cf1788`；
它链接而不改写原CLOSED604文件审计。固定558项pins及10文件资格源码闭包不变，
实际reader来自`e9ff318efc9ea2c333dcb241d0871150c3d30446`，与资格源码分开记录。
2026-11-27 15:08:26 Asia/Singapore的独立AWS读回确认Stopped／无公网IPv4或DNS。
本次文档修订前基线`b5ee94808861ed6eff085f71073bb703bfd7d6f9`的远端专用91项、
Engineering全部16项及Documentation已SUCCESS；旧GHA参考拒绝另列，不能洗成通过。

[S13-02 owner审阅材料](../security/s13-02-owner-review.md)已整理当前交付与独立门槛；
owner接受仍PENDING，PR115保持Draft，#38仍OPEN／in-progress，不记Done。
M1产品未集成且DISABLED，M2不支持；独立真人安全复核NOT_PERFORMED，
外部真人研究复验0 attempts／0 successes／PENDING。S13-03／#39仍Planned，
HTTP／MCP仍为有需求证据后的条件性S14或以后工作，本轮没有实际推进。

以下2026-11-19至2026-11-27的冻结／失败／实施中记录为历史快照；其中“当前”及
“后续仅计划”的状态已由上述2026-11-27实测与只读收证记录取代（SUPERSEDED），
原始结果、扣额、许可与审计字节均不回写。

2026-11-27续作：owner明确要求继续实际AWS验证。[v3合同](../contracts/restricted-reference-ec2-recovery-v3.md)
和[ADR0050](../adr/0050-one-use-detached-ec2-qualification.md)经独立静态审阅，以提交
`72c83a02d47a403d5f9d33aad2f84ccaba7ec6a4`实际推送、读回后才开始实现。
固定第四次资格保留历史21槽，新完整24项／累计上限45，原研究共同预算不变。
新增收证控制器在原期限内等待独立下载校验及绑定当前boot／unit／进程的ACK，
随后由原hook自动Stop；断连、坏ACK和期限耗尽不授重跑。当前源码实现及远端回归
进行中，尚未获得v3实机结果；M1关闭、PR115 Draft、真人PENDING均不变。
下列此前“仅计划／未授权第四窗口”的记录是已被此冻结取代的历史快照。

2026-11-27实测续作：[修复版v2实机证据](../security/ec2-reference-recovery-v2-evidence-2026-11-27.md)
已完整取回并封存：第1–18项PASS，第19项detached已准入UNKNOWN，后5项未准入；
本轮19charged／19confirmed，历史2，累计21／21，pending及ACK不确定均0。
持久状态TERMINAL／NOT_QUALIFIED、poisoned=false，成功report SHA与receipt均null。
完整原archive与旧journal独立解码逐字节相同；取证后AWS独立确认Stopped／无公网IP。
v2一次性许可已消费，剩余5项不变成重试额度。当前工作仅修正detached成员筛选、
远端回归及[下一次验证计划](../security/ec2-reference-next-validation-plan.md)；
拟议新24项／累计45仅PROPOSED／NOT_AUTHORIZED，不实现或自动启动第四窗口。
M1仍DISABLED、PR115 Draft、#38未完成，外部真人0/0/PENDING、独立安全NOT_PERFORMED。

2026-11-27冻结记录：owner明确要求修复版继续在真实AWS验证。新的
[固定一次性恢复v2合同](../contracts/restricted-reference-ec2-recovery-v2.md)／
[ADR0049](../adr/0049-one-use-corrected-ec2-qualification.md)经独立静态交叉审阅，
已在仅两份文档的提交[`5ef1945`](https://github.com/Darrenus/tickwitness/commit/5ef1945c154cc944900a6d042f947bba0d620fd9)
实际推送并读回后才开始实现。只允许固定第三次技术资格窗口：前两次2槽和全部
原始记录保留，新最多24项／600s／30s setup，累计最多26，不重置研究协议预算，
不自动授第四窗口。新路径／schema2与旧v1隔离，具体过程见
[v2操作说明](../security/ec2-reference-recovery-v2-operations.md)。第三次实际结果见上，
不得用源码绿色替代完整主机资格。下列两次失败及原始合同继续保留。

2026-11-26实测续作：[一次性恢复验证](../security/ec2-reference-recovery-evidence-2026-11-26.md)已实际执行，仍为NOT_QUALIFIED。来源`d5f5fab`的远端Engineering全部16项及Documentation通过后，原主机新boot中的正例在独立进程限额读回门拒绝；固定Python已给出readiness，但未获GO，不能算正例或负例通过。本次1charged/1accepted、与旧记录累计2/2，0pending/0ACK未知，其余23项未入场；原始limits文本未保留，尾部列填充解析问题仅有独立静态源码证据。归档完整校验后，AWS明确Stopped／无公网IP／InstanceInitiatedShutdown。原一次恢复许可已消耗，保留全部历史和消费记录，不自动授第三窗口。后续源码修正保留原hard/soft限额并补真实Linux读回回归及失败观测；源码成功不续资格。M1仍DISABLED，PR115仍Draft、#38未完成；真人0/0/PENDING和安全NOT_PERFORMED不变。

2026-11-26续作：[一次性恢复合同](../contracts/restricted-reference-ec2-recovery-v1.md)／[ADR0048](../adr/0048-one-use-ec2-recovery-qualification.md)已在仅两份文档的提交[`a19cff3`](https://github.com/Darrenus/tickwitness/commit/a19cff330df5a04e405c83baebcfb0bddf3498fa)实际推送并读回后才开始实现。明确追加一次技术资格24项／600s，旧1次扣额与失败记录永久保留，累计最多25次实际提交；不续旧时钟、不拼接剩余23项，也不增加研究协议预算。固定全局单次消费、只读旧claim互斥、独立恢复schema及初始／最终记账阶段见合同和[操作流程](../security/ec2-reference-recovery-operations.md)。当前仍无恢复实机通过结果，M1仍DISABLED，PR115仍Draft，#38未完成；外部真人与独立安全状态不变。

2026-11-25续作：专用EC2自动停机异常分支已完成[更正后的实测验收](../security/ec2-lifecycle-evidence-2026-11-25.md)，最后AWS明确Stopped。原日志查询格式／空输出误判已保留并撤回早期PASS，用新读回补证，未重跑原场景或重置研究预算。[独立EC2合同](../contracts/restricted-reference-ec2-v1.md)／[ADR0047](../adr/0047-dedicated-ec2-reference-admission.md)在提交[`5a86b8a`](https://github.com/Darrenus/tickwitness/commit/5a86b8a98d815da609b540f0ef91f9605ae3bcf0)实际推送并读回后才开始实现。新来源不用伪造GHA身份，也不改旧opaque拒绝结论。[首次EC2实测](../security/ec2-reference-evidence-2026-11-25.md)已完成：政策加载／bootstrap成功，正例因输入目录权限拒绝而未到guest gate，真实计费1槽、其余23项未入场；保留poisoned终态，NOT_QUALIFIED，之后AWS明确Stopped。M1产品仍DISABLED，PR115仍Draft、#38未完成；外部真人0/0/PENDING及独立安全NOT_PERFORMED分别保留。下面2026-11-19记录为上轮历史，不覆盖此续作状态。

EC2接入完成静态实现及交叉审阅；源版本ae3d8e7的远端Engineering45626224529全部16项及Documentation45626224572通过，首次实机资格仍失败。真实来源／九文件source lock、同一原始持久预算、单次票据、独立manifest家族和双记录终态验收见[操作流程](../security/ec2-reference-operations.md)。当前修正仅针对private umask下新建输入目录的显式权限，并补实际文件系统回归；不重开原run，不把源码修复当实机通过。后续恢复须另行审阅，不自动换身份或清账。冻结文档触发的远端Engineering45622351548另暴露既有只读smoke在SQLite journal轮换时的拒绝竞态，已仅在harness原10s期限内补严格分类重试并保留每次拒绝；产品完整性门、worker执行及原研究预算未改。

更新2026-11-19 Asia/Singapore。Owner已合并[PR114](https://github.com/Darrenus/tickwitness/pull/114)，真实merge `6c350b9fe32dfed96392edd2b856e937f767e342`，2026-11-19T13:09:12Z（21:09:12 Asia/Singapore），接受S13-01的威胁模型、三模式及文件／环境／网络／资源缺口；#37已关闭Done。候选 `48c27b71b9250d737ee39295f1489177e887090d` 与实际CI checkout `dd3b24e633d6a58701e59eed3ab2c33c5c76f7b3` 不是owner merge；原307成员封存逐项复核不变，实际接受另存，不回写旧owner=false或首轮故障记录。

上游S12已由owner合并[PR113](https://github.com/Darrenus/tickwitness/pull/113)接受，真实merge `df10923663a3d3c09b5b917995fbb554da60ea40`，2026-11-18T16:03:09Z；SDK契约回归／实际文档执行、#36与S12三项故事均已接受。模型、材料和软件接受不计真人激活或本轮隔离资格。

| 故事 | 原容量 | 当前状态 |
| --- | ---: | --- |
| S13-01 / [#37](https://github.com/Darrenus/tickwitness/issues/37) | 10h | [执行信任与威胁模型](../contracts/execution-trust-v1.md)／[ADR0044](../adr/0044-explicit-execution-trust-boundaries.md)已随PR114实际接受；M0／M1／M2是信任文档标签，不是SDK模式开关 |
| S13-02 / [#38](https://github.com/Darrenus/tickwitness/issues/38) | 16h | 固定v3实机24PASS／本轮24+历史21=累计45，QUALIFIED_REFERENCE_ONLY；独立只读readback63文件已CLOSED，原handoff过期74／ACK不存在分别保留，AWS已Stopped。见[证据](../security/ec2-reference-recovery-v3-evidence-2026-11-27.md)及[owner审阅](../security/s13-02-owner-review.md)；PR115 Draft、owner接受PENDING，#38仍OPEN／in-progress，M1产品未集成／DISABLED，不记Done |
| S13-03 / [#39](https://github.com/Darrenus/tickwitness/issues/39) | 8h | Planned；独立安全复核准备／能力降级与真实采用观察尚未完成，尚未开展实际故事工作；不能用安全准备替代真人激活／复用 |

原S13专项容量仍10+16+8=34h，持续质量容量不变，不补造实际工时。本轮属于infrastructure／operations边界，不新增领域聚合、SDK方法、CLI模式、Job/Catalog schema、研究结果或远程服务。

## 先冻结后实现

[Restricted reference v1](../contracts/restricted-reference-v1.md)／[ADR0045](../adr/0045-restricted-reference-qualification.md)已作为仅两份文档的提交[`5fc3377`](https://github.com/Darrenus/tickwitness/commit/5fc3377834831a00e4a4929d9f3196c3621912ad)实际推送并核验远端ref，然后才开始实现。资格家族固定为远端GHA CPU、Ubuntu24.04/Linux x86_64；rolling runner标签不是精确镜像pin。每台实际VM的OS／kernel／ImageVersion、TCB／bwrap／probe／BPF摘要、身份和机制先冻结manifest，再在同机运行固定探针；新tuple不继承旧成功，未知字段不补造。

具体数字与语义以合同为准：root控制器在cgroup外，child先入独占leaf再降UID/GID61184／清groups／NNP；显式required namespace、只读根／runtime／输入、唯一16MiB／512inode tmpfs、final-exec seccomp。CPU为每100ms最多25ms的fair-class带宽，不是累计CPU秒上限；内存256MiB、swap0、task32、FD64、单文件8MiB、core0／RTPRIO0。每探针原10s入场期限、另2s停止确认、stdout／stderr各64KiB，最多24固定合成探针共用原600s资格入场窗口。host证据和日志另有界，不把guest盘额称为宿主全盘配额。

缺控制器、AppArmor/userns/NNP启动失败、挂载／身份／FD／filter或停止事实不明时拒绝／UNKNOWN／NOT_QUALIFIED，不能移除NNP、关闭全局AppArmor/sysctl、用optional unshare、静默跳过负例或回退M0运行不可信代码。root/proc只读不是递归口号，实际每个mount和可写面均需核查。

## 已观察的参考环境阻塞

本节保留2026-11-19 GHA环境的历史拒绝，作为“当前环境仍未获资格”的结论已于
2026-11-27由上述专用EC2 v3参考结果取代（SUPERSEDED）；它不变成GHA通过，
也不授予任何M1产品支持。

兼容政策及具体setup上限已在独立提交`0860658`／`aceda2c`实际推送后才实现loader／pre-NNP transition。具名unconfined是userns授权例外，不是额外MAC隔离；仍不得关闭全局AppArmor/sysctl、卸载宿主政策或移除NNP。参见[兼容合同](../contracts/restricted-reference-apparmor-v1.md)／[ADR0046](../adr/0046-explicit-reference-userns-authorization.md)。

实际run44548411070/head`8b9d8ff`在加载前发现124个已加载profile中100个attachment为`<unknown>`，无法建立无冲突闭包，按原门拒绝。外部命令0／load_submitted=false；资格步骤SKIPPED，无ReferenceRunner manifest、探针预算计数或payload-start记录，不能编造24个攻击结果或0次已计费admission。之前run44536018240与44538107915各自真实消耗的1次启动admission及失败／UNKNOWN记录保留。

这不是隔离负例通过；T01–T08实际完整攻击与停止／回收仍未获资格。政策加载、显式transition及guest控制均未在本兼容实现上验证。源代码测试／类型／构建成功也不补足这些证据。当前选定环境NOT_QUALIFIED，PR115保持Draft，#38保持OPEN／in-progress；后续需要先冻结具有可观察loaded attachment闭包的专用参考环境，再执行新的资格。不能只为绿色跳过opaque规则、盲目重试相同VM、卸载政策造空或引入未评审DFA解码／policy namespace。

## 三模式与证据门

| 文档标签 | 当前支持状态 | 边界 |
| --- | --- | --- |
| M0 TRUSTED_LOCAL | 仅现有已资格内置profile及受支持环境 | owner／解释器／依赖／宿主可信；源码冻结不执行任意Python；远端单owner仍是M0 |
| M1 RESTRICTED_SINGLE_HOST | **产品入口关闭；未集成、未开放任意源码** | 内部reference选择与实际控制资格不自动授予SDK／CLI执行权限；独立安全复核及原模型门仍需满足，不把普通CI绿色当M1产品支持 |
| M2 HOSTED_UNSUPPORTED | 不支持需独立用户／租户身份权限的托管／协作服务 | 无跨租户授权、秘密、配额和服务运维资格；单机参考负例成功也不能提供这些边界 |

正例需证明固定任务确实在选定控制内运行；负例需有start nonce、固定payload摘要、真实退出与宿主独立控制器／canary／成员／停止证据；仅非零退出或worker自报不算通过。未执行、缺宿主事实、跳过及unknown均不能洗成成功。成功退出或stop request不等于cgroup已空；未确认停止或owned mount／inode不一致时保留scratch／诊断，停止后续admission，不强制／lazy卸载或删除调用者路径。

当前候选的实际远端检查、主机tuple、具名攻击结果与缺口须在发生后另行记录；本状态入口不继承PR114旧绿色，也不将文档或测试配置的存在计为通过。内部后端只运行固定合成探针，不把现有Job的Popen换成runtime CLI，不把launcher PID／wait4当真实compute。未来产品集成须另冻结原槽之前的preflight、core-only ACK／已提交短路、真实执行身份／资源、原deadline、停止与发布fencing映射。

## 原预算和真人状态

固定OS探针不构造／打开研究Job/Catalog／ledger，不调用native回放引擎，不预留研究槽或产生finding；24／600仅为技术资格入场限制，不授予协议权限。原5／8／11、协议／Job／family身份、golden、PR94及历史封存不重置／退款。真实研究重跑需同一原协议新槽；已提交结果只复核／ACK，失败／中断／未知不变成免费重试。

独立外部安全复核仍 **NOT_PERFORMED**，与外部真人研究复验分别计门；CI、AI和owner合并不是独立真人安全审批。M1产品入口在足够实际证据／复核前保持关闭；HTTP／MCP仍为S14或以后的条件性工作，无listener或托管授权。

外部真人研究复验保持 **0 attempts／0 successes／PENDING，#24 OPEN**；实际自有案例登记为空，联系／回复／意图UNKNOWN。[招募缺口](s12-02-recruitment-gap.md)与[自有案例流程](../user-onboarding.md)继续分别记录技术成功、真人参与、激活、价值和30天复用。全部项目／测试／攻击／构建／格式／类型／native执行继续仅远端CPU。没有release、GPU、新服务器、采用／收益声明、自动合并或外发联系。
