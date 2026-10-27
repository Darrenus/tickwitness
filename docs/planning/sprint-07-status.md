# Sprint 7 固定预算搜索状态

更新：2026-10-27（Asia/Singapore）。Owner 已合并 [PR #88](https://github.com/Darrenus/tickwitness/pull/88)，S07-01a 的候选规划能力已接受。当前 Sprint 7 基线 merge 为 `373d08a5c2196662c5116e02ea7b7fe3a98dc167`；`0.2.0.dev0` 保持未发行。真实访谈、采用和独立人类领域复核没有新增证据。

## 本轮切片与后续门

| 故事 | 切片与实际边界 | 状态 |
| --- | --- | --- |
| S07-01 / #19 | S07-01a 冻结网格／随机候选、来源、种子与完整 proposal journal；重建去重／拒绝及 source 派生预检 | Owner 已合并 #88 |
| S07-01 / #19 | S07-01b 自动评估、候选与真实 attempt/outcome 关联；原协议预算不重置 | [PR #89](https://github.com/Darrenus/tickwitness/pull/89) 远端验收通过，待 owner 接受 |
| S07-02 / #20 | Campaign 评估次数／时间／存储硬限额及完整停止原因 | 尚未实现 |
| S07-03 / #21 | 有范围的反例／预算内未发现／不可评价输出 | 尚未实现；本轮 findings 关闭 |

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

S07-01a 的提议计划已获 owner 接受；其交付时 #19 保持打开，自动评估及 durable attempt／outcome 关联、campaign 硬限额、搜索 finding、确认集 lifecycle 和完整统计试验历史仍由后续切片交付。未新增实际工时、真实访谈、性能或采用数据。

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

S07-01 的实现验收已覆盖规划、自动候选评估及原预算下的 attempt／outcome 追溯；[PR #89](https://github.com/Darrenus/tickwitness/pull/89) 待 owner 接受前 #19 保持打开。S07-02 的 campaign 总时间／存储硬限额、S07-03 搜索结论、S08 确认与封包、S10 通用恢复及真实访谈仍分别保留；不以测试通过补造工时、市场采用或研究收益证据。
