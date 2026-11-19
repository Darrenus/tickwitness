# Sprint 13 执行信任与隔离状态

更新2026-11-19 Asia/Singapore。Owner已合并[PR114](https://github.com/Darrenus/tickwitness/pull/114)，真实merge `6c350b9fe32dfed96392edd2b856e937f767e342`，2026-11-19T13:09:12Z（21:09:12 Asia/Singapore），接受S13-01的威胁模型、三模式及文件／环境／网络／资源缺口；#37已关闭Done。候选 `48c27b71b9250d737ee39295f1489177e887090d` 与实际CI checkout `dd3b24e633d6a58701e59eed3ab2c33c5c76f7b3` 不是owner merge；原307成员封存逐项复核不变，实际接受另存，不回写旧owner=false或首轮故障记录。

上游S12已由owner合并[PR113](https://github.com/Darrenus/tickwitness/pull/113)接受，真实merge `df10923663a3d3c09b5b917995fbb554da60ea40`，2026-11-18T16:03:09Z；SDK契约回归／实际文档执行、#36与S12三项故事均已接受。模型、材料和软件接受不计真人激活或本轮隔离资格。

| 故事 | 原容量 | 当前状态 |
| --- | ---: | --- |
| S13-01 / [#37](https://github.com/Darrenus/tickwitness/issues/37) | 10h | [执行信任与威胁模型](../contracts/execution-trust-v1.md)／[ADR0044](../adr/0044-explicit-execution-trust-boundaries.md)已随PR114实际接受；M0／M1／M2是信任文档标签，不是SDK模式开关 |
| S13-02 / [#38](https://github.com/Darrenus/tickwitness/issues/38) | 16h | 先实际推送参考合同／ADR0045，再实现有界内部控制后端和固定合成负例；[实际环境预检拒绝](../security/restricted-reference-evidence-2026-11-19.md)，NOT_QUALIFIED／PR115 Draft；源代码回归另计，负例资格及owner接受未完成 |
| S13-03 / [#39](https://github.com/Darrenus/tickwitness/issues/39) | 8h | 独立安全复核准备／能力降级与真实采用观察尚未完成；不能用安全准备替代真人激活／复用 |

原S13专项容量仍10+16+8=34h，持续质量容量不变，不补造实际工时。本轮属于infrastructure／operations边界，不新增领域聚合、SDK方法、CLI模式、Job/Catalog schema、研究结果或远程服务。

## 先冻结后实现

[Restricted reference v1](../contracts/restricted-reference-v1.md)／[ADR0045](../adr/0045-restricted-reference-qualification.md)已作为仅两份文档的提交[`5fc3377`](https://github.com/Darrenus/tickwitness/commit/5fc3377834831a00e4a4929d9f3196c3621912ad)实际推送并核验远端ref，然后才开始实现。资格家族固定为远端GHA CPU、Ubuntu24.04/Linux x86_64；rolling runner标签不是精确镜像pin。每台实际VM的OS／kernel／ImageVersion、TCB／bwrap／probe／BPF摘要、身份和机制先冻结manifest，再在同机运行固定探针；新tuple不继承旧成功，未知字段不补造。

具体数字与语义以合同为准：root控制器在cgroup外，child先入独占leaf再降UID/GID61184／清groups／NNP；显式required namespace、只读根／runtime／输入、唯一16MiB／512inode tmpfs、final-exec seccomp。CPU为每100ms最多25ms的fair-class带宽，不是累计CPU秒上限；内存256MiB、swap0、task32、FD64、单文件8MiB、core0／RTPRIO0。每探针原10s入场期限、另2s停止确认、stdout／stderr各64KiB，最多24固定合成探针共用原600s资格入场窗口。host证据和日志另有界，不把guest盘额称为宿主全盘配额。

缺控制器、AppArmor/userns/NNP启动失败、挂载／身份／FD／filter或停止事实不明时拒绝／UNKNOWN／NOT_QUALIFIED，不能移除NNP、关闭全局AppArmor/sysctl、用optional unshare、静默跳过负例或回退M0运行不可信代码。root/proc只读不是递归口号，实际每个mount和可写面均需核查。

## 已观察的参考环境阻塞

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
