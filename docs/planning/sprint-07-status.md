# Sprint 7 固定预算搜索状态

更新：2026-10-27（Asia/Singapore）。Owner 已合并 [PR #90](https://github.com/Darrenus/tickwitness/pull/90)，S07-01 的规划／持久自动评估及 S07-02 的 campaign 硬预算已接受。当前 Sprint 7 基线 merge 为 `935282c415d167bdcc8485569e47e5221e95b4c3`；`0.2.0.dev0` 保持未发行。真实访谈、采用和独立人类领域复核没有新增证据。

## 本轮切片与后续门

| 故事 | 切片与实际边界 | 状态 |
| --- | --- | --- |
| S07-01 / #19 | S07-01a 冻结网格／随机候选、来源、种子与完整 proposal journal；重建去重／拒绝及 source 派生预检 | Owner 已合并 #88 |
| S07-01 / #19 | S07-01b 自动评估、候选与真实 attempt/outcome 关联；原协议预算不重置 | Owner 已合并 #89 |
| S07-02 / #20 | 独立受控 profile 的评估数／执行阶段总期限／managed payload 容量硬门 | Owner 已合并 #90 |
| S07-03 / #21 | 有范围的反例／预算内未发现／不可评价输出 | 远端验收通过，PR #91 待 owner 接受 |

原故事验收、14h／12h／8h 专项估算及每 Sprint 15h 日常质量容量保持 [Sprint backlog](sprint-backlog.md#s7--固定预算反例搜索) 原意。切片不是额外工时承诺；实际工时未登记，代码或测试数量不能当作完成了全部研究或采用门。

## S07-01a 冻结内容

合同见 [Search Plan v1](../contracts/search-plan-v1.md)，决策见 [ADR 0021](../adr/0021-frozen-search-candidate-plans.md)。固定一个既有 `ExecutableProtocol v2`、来源绑定的 `AssumptionSpec`、capture anchor 和未校准 COUNTERFACTUAL_STRESS。单一维度为非负整数纳秒 additional_delay；不合并 tagged reconstruction 或旧 ghost 模型，不复用其 finding 权限。

Grid 保留列表原顺序，random 使用独立 search seed 与固定 SHA-256 counter rejection 政策；原执行 seed 不变。每个原始提议计数一次，包括重复或范围拒绝；不通过重抽隐藏成本。Journal 保留连续 ordinal、delay、ScenarioSpec 身份、最早 duplicate_of 及拒绝原因。Loader 重新生成完整 plan，应用从真实 source 再派生全部 eligible 唯一候选；整体工作量超过限额时拒绝，不能裁掉后缀伪称完整。

新计划单独持久冻结并提供 freeze／inspect CLI。两者拒绝 confirmation，既有 source、protocol、执行 ledger 和预算不变；本轮不构造 native、不占 attempt、不读取执行结果、不签研究 finding。Proposal 生成停止原因与执行／搜索停止原因分开。

## 验收门

- 严格 JSON／整数／单位／生成器版本；相同 source、种子与预算产生同一完整序列。
- Grid 重复与越界拒绝、random 无偏映射黄金向量及预算前缀；首见拒绝的重复仍可追溯。
- 冻结／inspect 实际 source 与派生重建，损坏闭包／身份／journal 拒绝，所有 hash 重算不能洗白错误。
- 缺失根不创建、确认集先拒、no-follow regular bounded 输入、原子 no-replace、只读与持久失败证据保留。
- 远端 core／native 回归、实际 wheel 与实际 source archive 的 core-only 安装闭环；本机不运行测试、build、formatter、安装或原生回放。

S07-01a 远端结果、代码 head、实际 merge checkout 与 artifact 身份见下节。当前不得宣称自动搜索、完整试验账本、执行预算或 alpha 门已完成。

## S07-01a 远端验收记录

功能代码 head `ad57f6d2c7946a34c618f4436d0d2abd9e5e485f` 的 [Engineering 40483167929](https://github.com/Darrenus/tickwitness/actions/runs/40483167929) 与 [Documentation 40483168061](https://github.com/Darrenus/tickwitness/actions/runs/40483168061) 共13 checks 全部通过；实际 merge checkout 为 `eb8e41b21dfc71051a11c8ddd49fa4eb49fbeba7`，与 PR head 分开。后续文档提交的 CI 不冒充同一代码 head。

核心 Ubuntu 24.04／macOS 15 × Python 3.12／3.13／3.14 六组合各 **2225 passed / 111 optional-native skips**；原生 Ubuntu 24.04 与 macOS 26／Python 3.12 各 **2334 passed / 2 core-only skips / 313 warnings**。Lint、194 文件格式、90 source files 严格类型检查、71 文档／381 本地链接通过；warnings 保留，不作为通过断言。所有测试、构建、格式化、安装和原生回放均在远端，本机只进行编辑、静态审阅、Git／gh 控制与下载报告读取。

| 实际核验 | 结果 |
| --- | --- |
| Grid 完整提议 | 4 次原始提议保持顺序，2 eligible／1 duplicate／1 rejected；duplicate 指向首见，越界保持 null scenario_id，不补抽 |
| Random 与种子 | 固定 SHA256 无偏整数映射与独立编码 oracle 对齐；0、1、2^63−1 三组 seed 的安装后序列保存为固定回归向量；原生 replay seed 不改变 |
| 原始预算与停止 | 较小预算严格为同一 journal 前缀；singleton 越界区间得到 R/D/D/D，eligible=0 仍不被包装成搜索结论；grid_exhausted 仅指列表生成完毕 |
| Source 与派生 | 每次 freeze／inspect 均重验实际 development source 与所有 eligible 派生视图；raw／quality／identity／anchor 不合格或组合规模超限即整体拒绝 |
| 持久化与攻击 | 并发幂等、原子 no-replace、损坏不覆盖；symlink／FIFO／目录／超限拒绝；提交后 fsync 异常保留已提交证据；完整重算 hash 的伪造 journal 仍拒绝 |
| 无执行副作用 | 安装后的 core-only guard 禁止 native import、worker、network 和 attempt ledger 构造；source／原 protocol registry 字节树不变，无 runs 或 attempt |
| 权限与读取 | confirmation 在 ID／请求／factory 前拒绝；缺失根不创建；重复冻结同身份，inspect 只读且完整重新生成 |

安装后验收报告为 `installed_search_plan_acceptance_v1`。功能 run 的 `search-plans-core-eb8e41b21dfc71051a11c8ddd49fa4eb49fbeba7` 与 `search-plans-source-wheel-eb8e41b21dfc71051a11c8ddd49fa4eb49fbeba7` artifacts 保留30天；后者使用实际 tar.gz 内脚本／样例和全新环境中的实际 wheel，不以 checkout 替代。两份报告 accepted=true，全部不变量为 true，candidate plans 与三组随机向量一致。

初轮远端发现新 CLI 在 Python 3.12 运行时求值 argparse 泛型注解而阻断导入；增加延迟注解并应用远端格式补丁后重验，未修改候选或拒绝 oracle 掩盖问题。AI 并行静态复核单独计为 AI 审阅，独立人类领域接受仍未取得。

S07-01a 的提议计划已获 owner 接受；其交付时 #19 保持打开，自动评估及 durable attempt／outcome 关联随后由下节 S07-01b 交付并接受。Campaign 硬限额、搜索 finding、确认集 lifecycle 和完整统计试验历史继续作为独立后续门。未新增实际工时、真实访谈、性能或采用数据。

## S07-01b 实现边界与验收门

合同见 [Search Execution v1](../contracts/search-execution-v1.md)，决策见 [ADR 0022](../adr/0022-persistent-search-execution.md)。同一 plan／runs 根只启动一次串行 campaign；后续调用只重审已有记录，不自动恢复、重跑或退还槽位。每个 eligible 候选先持久 dispatch 与 reservation nonce，再从原 v2 协议共同 slots 占槽、保存 link 和旧 scenario intent，最后构造原生 worker。Baseline、其它 plan 和失败尝试共同消费原预算，不把 SearchPlan 当新预算 owner。

每份实际 result 在独立账务审计前保存；不通过审计的原始结果保持诊断状态，不变成反例。只读 inspect 重验实际 source／plan／dispatch、原 reservation／nonce／intent／outcome 与账户；失败、未完成、预算耗尽、占槽或发布不确定均停止后缀。未知 nonce 分配不误报未消耗，槽位可见而 link 缺失时保留已占未决状态。

验收包含：基线先占槽后自动0／非0场景执行、duplicate／rejected不占槽、同plan重复调用不重放、并发末槽和同nonce拒复用、reserve提交后异常按nonce恢复、success outcome提交后回执丢失不改成failure、审计拒绝raw保留、KeyboardInterrupt未决与真实native EOF incomplete停止，以及实际wheel／sdist安装和core-only只读重审。新增测试、构建、格式化和原生执行全部远端。

本轮仍不签 search finding、不认证完整统计trial历史或真实市场概率；原scenario receipt的search_performed=false与tagged finding权限不改写。S07-02的campaign总时间／存储硬限额、S07-03的结论规则、S10恢复能力及真实访谈继续分别验收，工时与采用证据不补造。远端实际记录见下一节。

## S07-01b 远端验收记录

功能代码 head `96dff90c90593fa347773d3cb64bf3467e26945c` 的 [Engineering 40490382420](https://github.com/Darrenus/tickwitness/actions/runs/40490382420) 与 [Documentation 40490382427](https://github.com/Darrenus/tickwitness/actions/runs/40490382427) 共13 checks 全部通过；实际 merge checkout 为 `ec33e00b64d6eaa15f04116bf3eb497fa36682df`，与 PR head 分开。后续验收文档提交有独立 CI，不冒充相同代码 head。

核心 Ubuntu 24.04／macOS 15 × Python 3.12／3.13／3.14 六组合各 **2395 passed / 112 optional-native skips**；原生 Ubuntu 24.04 与 macOS 26／Python 3.12 各 **2505 passed / 2 core-only skips / 313 warnings**。Lint、205 文件格式、94 source files 严格类型检查、73 文档／390 本地链接与实际 wheel／sdist 验收全部通过；warnings 保留，不当作通过断言。所有测试、构建、格式化、安装和原生执行都在远端，本机仅编辑、静态审阅、Git／gh 控制和下载报告读取。

| 实际核验 | 结果 |
| --- | --- |
| 原预算下真实自动执行 | 先执行 baseline 占原协议 slot1，随后 ordinal1 的零延迟与 ordinal3 的2秒压力分别占 slot2／3；native 两候选均 completed，指标值为 −2／−1，原 scenario scope 与新 report 的 claim／finding 均不扩大 |
| 去重、拒绝与耗尽 | 4 次 proposal 保持 E/D/E/R，只有两条 eligible 派发；其它 seed 的新 plan 遭原协议 budget 耗尽，退出8、无新 reservation，后缀 NOT_DISPATCHED |
| 持久顺序与原始结果 | worker 构造前已有 dispatch nonce、原槽位、实际 link 和旧 scenario intent；原始结果在审计前保存，审计拒绝仍留 raw 诊断且 raw_result_audited=false |
| 失败与中断 | core 缺 optional extra 先占一槽并留持久 failure，退出6并停后缀；KeyboardInterrupt 留 reserved unfinalized；同plan重调仅重审，不恢复、不重放、不退款 |
| 不确定提交 | reserve 实际提交后抛错仍按预存 nonce 找回已消费槽；无匹配时 budget_consumed=null；success outcome 已提交后回执丢失保留真实成功结果，campaign仍按 publication_unconfirmed 停止 |
| 真实 EOF | 新原生集成案例产生真实 pending submit／INCOMPLETE，仅占首槽，第二候选不派发，退出7；保留原始 receipt／result／时钟／来源引用，不能伪称完成或反例 |
| 只读与完整性 | inspect 从原 source／plan／ledger 重建，不能用改写的 dispatch／link／result／stop 通过；缺 root 不创建，同plan复用不修复被删 ledger；同nonce及末槽竞争不双占；活动记录集合变化明确要求重读 |
| 安装闭环 | 两平台实际 native wheel 执行，由独立 core-only wheel 禁 worker／native import／network／ledger写入口后重审；实际 tar.gz 内脚本与样例配合新安装 wheel 再验证 |

`installed_search_execution_acceptance_v1` 报告及完整原创合成 source／registry／plans／runs 记录保留30天。Artifacts 为 `search-execution-core-ec33e00b64d6eaa15f04116bf3eb497fa36682df`、`search-execution-ubuntu-24.04-ec33e00b64d6eaa15f04116bf3eb497fa36682df`、`search-execution-macos-26-ec33e00b64d6eaa15f04116bf3eb497fa36682df` 和 `search-execution-source-wheel-ec33e00b64d6eaa15f04116bf3eb497fa36682df`。这些记录供重审，不冒充已经完成 S08 的可迁移 sealed search evidence 或认证完整试验历史。

初轮远端发现格式／导入、stop ordinal 与 CLI exit_code 类型，以及循环闭包和嵌套 with 的 lint 问题；修正后完整重验，未放宽结果、预算或停止 oracle。AI 静态交叉审阅另补强了活动快照、只读复用、无头 orphan 记录和失败 intent 闭包；该审阅仍属于 AI 辅助，不替代独立人类领域接受。

S07-01 的实现验收已覆盖规划、自动候选评估及原预算下的 attempt／outcome 追溯；owner 已合并 [PR #89](https://github.com/Darrenus/tickwitness/pull/89)，S07-01／[#19](https://github.com/Darrenus/tickwitness/issues/19) 已在此受限 profile 范围接受并关闭。S07-02 的 campaign 总时间／存储硬限额、S07-03 搜索结论、S08 确认与封包、S10 通用恢复及真实访谈继续独立验收；不以测试通过补造工时、市场采用或研究收益证据。

## S07-02 实现边界与验收门

合同见 [Campaign Budgets v1](../contracts/campaign-budgets-v1.md)，决策见 [ADR 0023](../adr/0023-supervised-campaign-resource-budgets.md)。独立预算与namespace不改写旧plan／campaign／scenario／原协议slots。新的run-bounded-search-plan受整份协调进程absolute monotonic deadline约束，native worker继承可统一终止的进程组；setup预检及终止收尾／只读重审另计，不声称硬实时CLI返回。

存储按平台新管理payload计量：32MiB控制及终端预留，每candidate执行前不可退款预留64MiB，容量不足在原slot之前停止。原ledger和campaign实际新文件写入前受guard检查，含stage及复制；stdin／stdout／stderr走有界内存pipes，无磁盘spools，coordinator禁止core dump。限额不覆盖文件系统元数据／块、RAM、运行时cache、既有inputs或其它campaign，不充当恶意宿主沙箱或整机配额。

新profile仍共用原协议attempt budget。评估数／容量／执行期限耗尽退出8，保留原始已提交结果、不可退款admissions和原slots；停止记录使用单独预留。重复命令只重审，不恢复或重新计时；修改冻结预算拒绝覆盖。验收包括首结果后耗尽、首slot前耗尽、<1秒期限、迟到结果拒收、洪泛／残留子进程清理、写入精确边界、提交后异常与readonly重审，以及实际wheel／sdist的core/native安装。测试／格式化／构建／安装和原生执行全部远端。实际证据见下节；S07-03 finding及S08/S10能力仍单独验收。

## S07-02 远端验收记录

功能代码 head `0b64d40b0cdf1774e36d43415452ca5598835f53` 的 [Engineering 40496997947](https://github.com/Darrenus/tickwitness/actions/runs/40496997947) 与 [Documentation 40496997915](https://github.com/Darrenus/tickwitness/actions/runs/40496997915) 共13 checks 全部通过；实际 merge checkout 为 `2de1e1647f71b8f3f33969d32c3425eafbb8926d`，与 PR head 分开。后续验收文档提交有独立 CI，不冒充同一功能代码 head。

核心 Ubuntu 24.04／macOS 15 × Python 3.12／3.13／3.14 六组合各 **2527 passed / 112 optional-native skips**；原生 Ubuntu 24.04 与 macOS 26／Python 3.12 各 **2636 passed / 3 core-only skips / 313 warnings**。Lint、222 文件格式、102 source files 严格类型检查、75 文档／400 本地链接与实际 wheel／sdist 安装验收全部通过；warnings 保留，不作为通过断言。所有测试、格式化、构建、安装和原生执行均在远端，本机仅编辑、静态审阅、Git／gh 控制与下载报告读取。

| 实际核验 | 结果 |
| --- | --- |
| 原预算下正常执行 | Baseline 占原 slot1，两个 native 候选占 slot2／3，指标 −2／−1；入场2次，预留160MiB。另一个 plan 被同一原协议预算拒绝，退出8且无新 reservation |
| 首结果后评估数／容量耗尽 | 两平台实际 native wheel 在 max_evaluations=1 或96MiB容量下均只提交首个候选的 −2 结果；第二候选保持 NOT_DISPATCHED，外层明确 evaluation_limit／storage_limit，退出8，原槽位不退款 |
| 首槽前容量耗尽 | 32MiB仅够控制预留，零入场、零原槽位，全部候选未派发；明确 storage_limit／退出8，不伪称空集完整搜索 |
| 总期限与结果保留 | 实际安装后的1ms期限均 time_limit／退出8，未建立内层头时显示 execution=null。真实子进程测试覆盖不足1秒期限、迟到退出／解析后结果拒收和子孙进程统一清理；首结果后时间耗尽的应用测试使用显式注入时钟与真实 saved-fixture ledger 提交，不冒充 native 物理耗时测量 |
| 写前硬门与收尾 | 精确 envelope 边界、超限写在 staging 前拒绝、control／terminal预留、失败预留不退款、ContextVar隔离与提交后异常保留通过；有界内存pipe洪泛拒绝，正常退出残存子进程及 KeyboardInterrupt 清理通过 |
| 只读与不可覆盖 | 每个安装案例 inspect 与 run 报告相同；core-only guard 禁 native／worker／network／ledger与campaign写入口后重审，重复运行不重放，文件字节树不变。修改冻结预算拒绝覆盖，confirmation先拒、缺root不创建 |
| 实际安装闭环 | 两平台 native wheel、core wheel，以及实际 tar.gz 中脚本／样例配合新安装 core／native wheel 均保留 accepted=true 的报告和原创合成记录；来源及原 protocol 不变 |

报告 kind 为 `installed_campaign_budget_acceptance_v1`。Artifacts 保留30天，均绑定上述实际 merge checkout：

- `campaign-budgets-core-2de1e1647f71b8f3f33969d32c3425eafbb8926d`（artifact ID `12730851720`）。
- `campaign-budgets-ubuntu-24.04-2de1e1647f71b8f3f33969d32c3425eafbb8926d`（`12731276600`）。
- `campaign-budgets-macos-26-2de1e1647f71b8f3f33969d32c3425eafbb8926d`（`12731910858`）。
- `campaign-budgets-source-wheel-2de1e1647f71b8f3f33969d32c3425eafbb8926d`（`12731496859`，含 core／native 两份报告）。

所有案例的只读相等、重复不执行及字节树保护不变量为 true。目录最终新增 payload 观察只作一致性检查；硬门由实际写前 guard 实施，采样不当作峰值空间或文件系统 block 配额证明。只读重审不重新施加历史时限，不认证物理资源使用、作者签名或完整统计试验历史。

远端修复保留了原预算／停止 oracle：mock worker 先确实退出再返回模拟pipe结果，PID ready文件改为完整同步后的原子发布；原同nonce并发占槽增加同进程互斥并保留跨进程文件锁及严格唯一slot断言。失败日志未打印该竞争异常的实际errno，因此不把候选平台根因写成已确认结论。AI静态交叉审阅另计为辅助审阅；独立人类领域接受未取得。

Owner 已合并 [PR #90](https://github.com/Darrenus/tickwitness/pull/90)，[S07-02 / #20](https://github.com/Darrenus/tickwitness/issues/20) 已在声明的执行阶段／managed payload 范围接受并关闭。S07-03 搜索结论、S08 确认／封包、S10 通用恢复和真实访谈继续独立验收；未新增发行版本、实际工时、性能或市场采用数据。

## S07-03 实现边界与验收门

合同见 [Search Findings v1](../contracts/search-findings-v1.md)，决策见 [ADR 0024](../adr/0024-scoped-search-findings.md)。独立 SearchFindingProtocol 绑定完整冻结 SearchPlan，把原数字 criterion 复制为新的条件压力谓词；不修改旧 plan、scenario receipt、baseline claim 或 tagged finding 权限，不允许新请求改选有利阈值。不认证规则曾在观察结果前预注册。

结论命令只从实际 bounded inspector 重新核对 source、候选派发、原 reservation／intent／result／outcome、admission 和停止证据；不接受外部自报 JSON report，不构造 worker、不占新 attempt、不写 runs。已审计 completed false 见证可给出有范围反例；非空 true 子集只有在正常完成或干净预算终止且所有入场候选可明确交代时，才可输出预算内未发现。集合、未评估后缀、生成停止、执行停止与两份预算分别列出；部分覆盖不判全计划谓词为 true。

合法的零覆盖、未知估值、失败、未完成、在途时间截断或无终态输出 NOT_EVALUABLE；错误来源、坏 hash 或篡改闭包仍是校验失败，不能洗成不可评价或未发现。先前有效 false 见证不会被后来执行故障抹掉，但故障仍在停止与覆盖中保留。报告为 LOCAL_REAUDITED，不冒充 S08 的 portable sealed FINAL。

验收包括 gt／ge／lt／le 的精确 Decimal 边界、false／true／unknown 全表、零候选、预算前缀、执行中与候选间时间耗尽、失败后不能 NO、有效反例后故障、完整重算 hash 的伪造输出、不同 plan／owner 拒绝、只读和原槽位不增、confirmation先拒，以及实际 core／native wheel 与 actual source archive 的安装闭环。所有测试／格式化／构建／安装和原生执行仍在远端；实际证据见下节。原8h估算及持续质量预算保持，未新增实际工时、访谈、独立人类复核或市场采用证据。

## S07-03 远端验收记录

功能代码 head `82ebe52c022d4d293db1f54183fe03985865e247` 的 [Engineering 40505668337](https://github.com/Darrenus/tickwitness/actions/runs/40505668337) 与 [Documentation 40505668186](https://github.com/Darrenus/tickwitness/actions/runs/40505668186) 共13 checks 全部通过；实际 merge checkout 为 `d2598756f3b99cef0378012aea011a7114b5d00a`。后续验收文档 head 的 CI 分开记录，不冒充相同功能代码或 artifact 身份。

核心 Ubuntu 24.04／macOS 15 × Python 3.12／3.13／3.14 六组合各 **2642 passed / 112 optional-native skips**；原生 Ubuntu 24.04 与 macOS 26／Python 3.12 各 **2751 passed / 3 core-only skips / 313 warnings**。Lint、233 文件格式、107 source files 严格类型检查、77 文档／405 本地链接和实际 wheel／sdist 安装闭环均通过；warnings 保留，不计作通过断言。本机未运行项目测试、formatter、构建、安装或原生执行。

| 实际核验 | 结果 |
| --- | --- |
| 有范围反例 | 两平台真实 native 的原 criterion gt0、指标 −2／−1 产生 CE；评估数／96MiB提前停止仍保留首个 false 见证，full-plan predicate=false，后缀保持未评估 |
| 全 true 有限集合 | 独立 −3 USD criterion 在该控制组执行前冻结；两候选均 true，输出 NO，精确 audited ordinals=[1,3]，仅此有限计划的 planned_predicate_truth=true |
| 预算内未发现 | 评估数1、96MiB及同原协议第三槽后耗尽三个 true 前缀均输出 NO；audited=[1]、unevaluated=[3]、完整覆盖=false、planned_predicate_truth=null。原预算共同使用，不给新 plan 充值 |
| 不可评价 | Core缺optional引擎的持久失败、零容量候选、1ms期限及零已评价的原预算拒绝均 NOT，finding_issued=false、全计划真值=null；不能把退出0的成功重审当成谓词成立 |
| 时间／未知／故障语义 | 显式注入时钟的真实 saved-fixture ledger 测试分别验证候选间干净时间边界 NO 和已消费在途槽位 NOT；完整账务但费用模型歧义仍未知。首 false 后多行诊断故障保留 CE；首 true 后同故障仅 NOT，原诊断完整保留。这些故障注入不是新 native 物理测量 |
| 只读与身份 | 各安装案例均在 core-only 禁 native／Popen／network／ledger、campaign和authority写入口下重审；重复报告完全相同，文件字节树不变。Scope绑定精确命题／预算与候选配对，snapshot hash从实际bounded inspector复算；旧 claim／finding旗标保持false |
| 损坏与权限 | 来源 raw 被改写继续报错3，不输出NOT洗白；authority／report重算hash的提权、错scope／候选pair、错误identity、布尔冒充整数与未知字段拒绝。nofollow／FIFO／超限、并发唯一提交、提交后异常保留通过 |

验收报告为 `installed_search_finding_acceptance_v1`：core 的3个案例与每个 native 报告的10个案例全部 accepted=true。实际 source archive 中脚本与样例配合新安装 core／native wheel，再分别得到3／10个一致案例。所有案例的 core-only重审、重复相等和字节树不变标记为true；native合成控制组的执行前冻结标记为true，core不执行该控制组，未冒充native资格结果。

报告及原创合成 source／registry／plans／runs／finding authority 记录保留30天。Artifacts 均对应上述实际 merge checkout：

- `search-findings-core-d2598756f3b99cef0378012aea011a7114b5d00a`（artifact ID `12734542957`）。
- `search-findings-ubuntu-24.04-d2598756f3b99cef0378012aea011a7114b5d00a`（`12735486282`）。
- `search-findings-macos-26-d2598756f3b99cef0378012aea011a7114b5d00a`（`12734608737`）。
- `search-findings-source-wheel-d2598756f3b99cef0378012aea011a7114b5d00a`（`12734903312`，含core／native两报告）。

远端修复包括由远端formatter生成并应用的补丁、测试协调器写库的显式create=True，以及合法多行failure诊断的兼容；旧停止、覆盖、false见证与共同预算oracle未放宽。AI交叉审阅发现的诊断兼容问题已进入first true／false后故障回归。此审阅仍是AI辅助，不替代独立人类领域接受。

[PR #91](https://github.com/Darrenus/tickwitness/pull/91) 待 owner 接受前 [S07-03 / #21](https://github.com/Darrenus/tickwitness/issues/21) 保持打开。Sprint 7 的这些实现不替代 S08 sealed search evidence／confirmation、S10恢复、全局统计trial账本或真实用户验证；未新增发行、实际工时、性能、采用或真实市场推断证据。
