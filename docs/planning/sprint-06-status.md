# Sprint 6 队列约束与资格状态

更新：2026-10-26（Asia/Singapore）。Owner 已合并 PR #79–86；Sprint 5、S06-01 的资格／共同预算／持久双模型执行，以及 S06-02a/b/c 的语义资格／守恒 tagged reconstruction／可迁移证据进入 `main`。本轮基线为 #86 merge `62fc66b563528fcd03713ec8597ddb66e4d9c870`。已有技术预览 `0.1.0a1` 保持原发行物，`0.2.0.dev0` 仍未发行。

已接受的 [PR #86](https://github.com/Darrenus/tickwitness/pull/86) 实现 S06-02c；历史远端记录见下文。本轮继续 S06-02d：独立冻结 finding 签发权限与确定性报告合同，明确有限条件见证、拒签和 FINAL 内容闭包。原执行协议／旧包权限不改写，不扩大市场或统计推断范围。

| 故事 | 当前切片与接受边界 | 状态 |
| --- | --- | --- |
| S06-01 / #16 | S06-01a/b 已接受；冻结共同预算、持久前后模型执行与独立审计 | Owner 已合并 #83 |
| S06-02 / #17 | S06-02a/b/c 已接受；S06-02d 独立 finding 权限与报告通过远端验收 | In progress；[PR #87](https://github.com/Darrenus/tickwitness/pull/87) 待 owner 接受，结论仅限显式冻结的条件 profile |
| S06-03 / #18 | 真实近期问题访谈累计 8–12 次，反馈关联工作流阻力 | 未取得新增访谈证据；不虚填次数、采用或独立领域验收 |

原故事验收与容量仍见 [Sprint backlog](sprint-backlog.md#s6--l2-队列解释与证据不足判定)。实际投入工时尚未登记。S06-01 原估算不因生成代码自动视为已完成；复杂执行能力需要单独可验收切片，不通过修改旧协议或跳过预算提前打开。

## 为什么先资格化

当前 `ReplaySpec v1` 和 `ExecutableProtocol v2` 没有可变队列解释，冻结的是现有 pinned native semantic；独立账务审计同样只支持该 profile。S05 的 scenario intent 仅表示额外接收时间压力，S05 的比较器要求相同 engine/spec/environment。它们不能静默接纳新的 queue profile，也不能把 `queue_position=True/False` 直接改名为相容的 Q-front/Q-back。

已资格验证的公开组合为 `queue_position=False`、公开 `FillModel` 和 `SimulationModule.pre_process`，在同一份固定 L2 观测上驱动显式影子队列约束。影子模型的观测簿不包含策略自己的模拟订单；聚合观测与策略成交的反馈、市场影响和真实交易所队列位置仍未证明。有限 fixture 复放成功仍只能报告 `MODEL_SENSITIVITY`，不能签发真实历史相容性。

新模型需要逐事件的输入引用、价位总量、gross additions/cancellations、trade 分配及队前/队后状态，以便独立检查守恒与非负。仅凭净深度下降不能知道撤单数量或位置；不能把同一成交同时扣作 trade 和 cancellation。未记录的 gross 分解属于明示模型条件，不因一份自洽的 JSON 变成观测事实。精确请求与输出见 [Queue Constraints v1](../contracts/queue-constraints-v1.md)。

## 已接受 S06-01a 的读写边界

`validate-queue-constraints` 读取已有 v2 protocol 和实际 development 输入，注入并核对来源绑定，再检查声明的受限 frame。确认集在请求文件或任何仓库访问前拒绝。它不运行 native、不给策略 fill/PnL、不占 attempt、不改变输入或协议，也不发布新的 catalog dataset、intent 或 outcome。

一份约束检查成功仅说明来源绑定及所列算术/顺序约束成立；旧 v2 protocol 不因此授权新的 queue profile。报告必须保留模型类别、未知撤单位置及执行未批准状态。无效 frame、引用、单位、整数、来源或不可支持状态都明确拒绝，不作为亏损或反例。

## S06-01a 验收门与历史记录

| 门 | 所需实际记录 |
| --- | --- |
| 声明与不可变身份 | exact JSON、单位、整数、重复字段与未知字段负例；detached document；任一来源/约束变化产生新身份 |
| 约束可行性 | 同观测两种受限分配、逐步守恒/非负、未知位置、非法引用/重复计量/不支持 frame 拒绝；不生成策略 fill 或 PnL |
| 权限与只读 | confirmation 先拒、缺失根不创建、完整字节树无改动、无 ledger/engine 调用、不会读取 confirmation 数据 |
| 固定原生资格 | pinned engine/environment、相同观测、两个显式撤单分配、逐步 queue trace 与原始 native 输出；失败和不匹配保留，不改 oracle 掩盖结果 |
| 分发与回归 | 远端 core/native 矩阵、安装后 CLI、实际 wheel/source archive 样例、已有 baseline 与 S05 对比路径继续严格 |
| 人类接受 | Owner 对该切片的审阅；独立人类领域复核仍有缺口，AI 交叉审查单独标识 |

### 实际远端记录

代码 head `eaf9afa7d85b9fb076a32a8b4934624b22dc13d9` 的 [Engineering 40254415805](https://github.com/Darrenus/tickwitness/actions/runs/40254415805) 与 [Documentation 40254415820](https://github.com/Darrenus/tickwitness/actions/runs/40254415820) 共 13 checks 全部通过；实际 merge checkout 为 `cae607747c161d82039b0b59d7b1550afd94b6d7`，不与 PR head 混记。核心六组合各 1207 passed / 38 optional-native skips；原生 Ubuntu 24.04、macOS 26 / Python 3.12 各 1243 passed / 2 core-only skips。145 个 native warnings 保留，未当作通过断言。实际 wheel 与其实际 sdist 中的脚本/样例在新环境完成 core/native 安装验收。

两平台固定资格报告均为 9 cases / 144 checks 全部通过，artifact 名为 `queue-models-<os>-cae607747c161d82039b0b59d7b1550afd94b6d7`，保存声明的 gross flows、原观测、独立约束 trace、原生 hook/order/fill/fee/account/接受点和 EOF 证据：

| 案例 | 实际核验结果 |
| --- | --- |
| front/back cancel | 同一观测字节、同一 gross flows；front 原生成交 1 手/费用 1 USD，back 0 手/0 USD，双方 capture 6 明确撤单并完成 |
| gross churn checkpoint | 声明新增 1、撤 4（净减 3），后续 trade 2；不以净量推 gross，两边外部状态与独立 oracle 一致，原生数量/费用仍 1/0 |
| no-cancel / same-time | 干净无撤单对照和同刻 capture 顺序符合各自预设；不是仅比较模型名称 |
| repeated public hook / non-trade | 显式诊断重复 hook 不重复授予容量，非 trade 返回空 book；不把诊断调用假称为 native 自动重试 |
| late acceptance | 真实接受点为 capture 5，队前量取当步外部量 2，不在接受前偷授容量 |
| EOF open / pending insert | 源输入结束后保持 incomplete/未决命令，不补 guard、不虚构接受或撤单回执 |

安装后 `validate-queue-constraints` 对真实 sealed source 重复检查身份稳定，原目录字节树不变、无 runs/ledger/worker；重复扣成交的 gross 负例被拒。所有新增测试、构建、回放和资格实验均在远端，本机仅编辑/审查文件、Git/gh 控制及读取下载报告。实际工时、性能数据、真实访谈和独立人类领域接受仍不补造。

## S06-01b 实现与验收门

本轮已实现先冻结同一观察源、队列约束／两政策、engine/adapter semantic、策略和共同预算。每次引擎调用在同一族下占一次 attempt；两个模型没有各自克隆的预算。执行前持久不可替换 intent，失败、超时与中断不退款。双调用逐次提交，失败即停止并明确报告 partial；未结束 reservation 仍可见且占预算。

新 queue trace、reservation/intent/receipt/failure 与审计均显式版本化；旧 v2、baseline receipt/bundle 和 S05 比较器继续拒绝新模型。独立审计从 actual source 重建 flow、FIFO frontier 和分配额度，核对真实接受、实际 native fills/fees/account、终态回执。只读 inspect 重算存档，不调用 native。合同见 [Queue Family v1](../contracts/queue-family-v1.md)，决策见 [ADR 0016](../adr/0016-frozen-queue-family-execution.md)。

新增验收覆盖同族末槽竞争、失败／未决不退款、先 intent 后 worker、原生结果审计失败后的持久诊断、错误来源与时钟、gross flow/重复授予/费用/现金/订单回执篡改、confirmation 提前拒绝、实际 wheel/sdist 的 CLI 闭环。所有测试、构建、格式化和 native 执行继续在远端，本机仅文件编辑、Git/gh 控制与报告读取。

两解释是否真正代表同观测下的可行世界仍需另行接受；保持 `MODEL_SENSITIVITY`，不签发 valuation/claim verdict，S06-02 的不可识别 finding 关闭。共同预算不是跨协议的统计试验账本，未补齐多重检验校正。实际工时、性能数据、访谈和独立人类领域接受均不补造。

### S06-01b 远端结果

代码 head `0038617b8b09902424217d5214ed60a3ffff3720` 的 [Engineering 40258276638](https://github.com/Darrenus/tickwitness/actions/runs/40258276638) 与 [Documentation 40258276628](https://github.com/Darrenus/tickwitness/actions/runs/40258276628) 共 13 checks 全部通过；实际 merge checkout 为 `33ed00e0509f07c7937f7e1c85bdcd1576e9300e`。本节为该已验证实现的验收记录，随后的文档提交不冒充同一代码 head。

核心 Ubuntu 24.04 / macOS 15 × Python 3.12/3.13/3.14 六组合各 **1444 passed / 49 optional-native skips**；原生 Ubuntu 24.04 与 macOS 26 / Python 3.12 各 **1491 passed / 2 core-only skips / 190 warnings**。lint、129 文件格式、61 source files 类型检查、文档链接、核心／原生回归、实际 wheel 及实际 sdist 的全新安装验收均通过。warnings 保留，不作为通过断言。初轮格式／类型门和两项新攻击测试的夹具金额字符串错误均有失败记录；修复后重新验证，未放宽 oracle 来遮盖原生差异。

两平台安装后的真实 CLI 均从 sealed development store 冻结同一个族，按 front/back 执行并重新 inspect；第三份验收使用实际 source archive 内脚本／样例及实际 wheel。远端 artifacts 名为 `queue-execution-<os>-33ed00e0509f07c7937f7e1c85bdcd1576e9300e` 与 `queue-source-wheel-execution-33ed00e0509f07c7937f7e1c85bdcd1576e9300e`，保留完整 family/source/intent/receipt/result/evaluation、账户、队列／hook／实际接受和共享预算检查，保存 30 天。

| 实际核验 | 结果 |
| --- | --- |
| 同一原创合成输入与 gross flows | front 实际成交 1 lot / 费用 1 USD；back 0 lot / 费用 0 USD；两者真实接受时目标外部量均为 5 |
| 终态与共同预算 | 双方 capture 6 收到真实原生 OrderCanceled；使用同一 family ID 的 2 个不同 attempt，remaining=0 |
| 无退款与部分成功 | 启动失败、超时、审计拒绝和中断消耗槽；第二模型失败保留第一模型成功并停止，CLI 返回非零；竞争末槽不双占 |
| 来源／分配／金融审计 | 时钟／future 引用、gross flow、重复或遗漏正额度、漏成交、费用／现金／仓位／回执等篡改拒绝；取得但未通过的原生结果持久保留诊断 |
| 超出固定样例常量 | 两政策另测非 1 的 price/size increments、不同资金／数量／价格和最终 cancel capture；gross churn、相同接收时刻及干净对照均通过 |
| 只读与分发 | inspect 不调用 native、不消耗预算，完整文件字节树不变；耗尽重试 exit 8，不新增槽；core 安装缺 extra 明确失败并保留已耗尝试 |

AI 并行静态复核单独计为 AI 审阅：发现并修复过“正容量漏成交也可能 verified”的漏洞与 worker 输入错误分类；独立人类领域复核仍待实际取得。上述结果不增加真实访谈次数或市场相容性结论，也不改变 S06-02 的关闭状态。

## S06-02a：观测与真假语义资格

合同见 [Queue Semantics Qualification v1](../contracts/queue-semantics-qualification-v1.md)，推导与远端实验见 [研究记录](../research/sprint-06-observation-semantics.md)。实际执行入口 `qualify-queue-pair` 只重审 committed run、实际源和共同条件，分别报告外部投影与一个指定插单投影的必要数量残差；所有生产 claim 真值仍为 null，findings 为空。候选 flat-zero／最终 bid 标记政策仅用于固定资格实验，不接受任意用户数据的免费重跑或事后改写 claim。

硬 oracle 为原样例 −1/0 且 gt0 为 F/F；独立最终 bid102 样例 +1/0 且 gt0 为 T/F、ge0 为 T/T。正值 own fill 暴露 external 全扣 trade 后再额外 fill 的单次分配矛盾；该反例只针对明确指定投影，不否定所有 ghost 数学模型，无残差亦不构成完整世界证明。非法、未完成、未批准、费用歧义和缺证不能当 false。

本切片见 [PR #84](https://github.com/Darrenus/tickwitness/pull/84)。实现 head `6ffdc4d45e08593af82f25786a3830f1dd16ddbd` 的 [Engineering 40260800327](https://github.com/Darrenus/tickwitness/actions/runs/40260800327) 与 [Documentation 40260800224](https://github.com/Darrenus/tickwitness/actions/runs/40260800224) 共 13 checks 全部通过，实际 merge checkout 为 `6c676acac65dcff9b5df16a73777f82cedb0d567`。核心六组合各 1534 passed / 57 skips，原生两平台各 1589 passed / 2 skips / 190 warnings；两平台、实际 wheel 与实际 source archive 均通过 8 cases / 210 checks。完整 artifact／oracle／失败修复与后续文档提交的 head 区分见 [研究验收](../research/sprint-06-observation-semantics.md)。S06-02 整条故事尚未接受；需要后续独立冻结 queue claim、观测／干预合同及 sealed evidence 流程，才能考虑实际 finding。

## S06-02b：冻结新命题并守恒地重建标记参与者

本轮合同见 [Tagged Queue v1](../contracts/tagged-queue-v1.md)，决策见 [ADR 0018](../adr/0018-conserved-tagged-queue-reconstruction.md)。源总量已含标记订单，入口仅把原有队尾 q 标记为己方，初始 `(A,R,B)=(Q-q,q,0)`。公开投影 `Q=A+R+B`；新增到 B，外部撤单跳过 R，trade 按 A→R→B 恰好分配一次。任一政策不可行均拒绝整份冻结。

新协议拥有独立 claim revision、engine semantic、投影／干预／终止／估值政策和共同预算。完整 source v2 与旧约束只提供数据、单位、费率和 gross 声明 lineage；旧 claim、ghost trace 和旧 1/0 结果不改写。原生首 capture 接受标记为 reconstruction proxy，不能当成真实历史所有权或到达证据。

`observed_window → claim_horizon → post_horizon_cleanup` 固定先观测与标记估值、再行政撤单；无虚构行情、时钟推进或 EOF guard。原生缓存仍标为 recorded observation cache，清理后的预测总量 Q−R 另行记录。模拟 private fills 和清理不纳入 public projection，当前并未读取或验证真实 private execution observations。

预设手算 oracle 为初始 Q5／q2、add3／cancel3／trade3：front ownfill2／external1，back ownfill0／external3，双方最终 Q2。费率1%且价格100时 fee2/0、mark100 net−2/0，gt0 为 F/F；独立 mark102 时 net+2/0，gt0 为 T/F、ge0 为 T/T。这些要求在运行前确定；实际远端结果见下文。

验收门包括：严格合同／来源／预算／双侧可行性；逐事件总量与 trade 单次分配；真实接受／fill／费用／账户与 horizon 前后生命周期；失败／中断不退款及先 intent 后 worker；只读重审闭包；Linux／macOS native 与 core 矩阵；实际 wheel／sdist 安装 CLI 闭环。项目测试、构建、原生回放和格式化全部在远端，本机仅文件编辑、静态审查、Git／gh 与下载报告读取。

即使这两条有限条件解释都通过，也不宣称实际插单预测或无冲击市场相容性。findings 始终为空；sealed tagged evidence、最终 `NOT_IDENTIFIABLE_WITHIN_MODEL`、确认集 lifecycle、跨协议试验账本和独立人类领域接受继续作为后续门。工时、访谈、性能与采用数据没有新增实证时不补造。

### S06-02b 远端验收记录

最终代码 head `e127668fffe0add89bfdfa1b1fe73721ba2bcbdc` 的 [Engineering 40286175944](https://github.com/Darrenus/tickwitness/actions/runs/40286175944) 与 [Documentation 40286175861](https://github.com/Darrenus/tickwitness/actions/runs/40286175861) 共 13 checks 全部通过；实际 merge checkout 为 `9e33d7dfd51a47eb12ea6ca996708ca90f189923`。本节是该已验证代码的记录；后续文档提交有独立 CI，不冒充相同 head。

核心 Ubuntu 24.04／macOS 15 × Python 3.12／3.13／3.14 六组合各 **1724 passed / 107 optional-native skips**；原生 Ubuntu 24.04 与 macOS 26／Python 3.12 各 **1829 passed / 2 core-only skips / 292 warnings**。lint、160 文件格式、75 source files 严格类型检查、文档链接、实际 wheel 及实际 sdist 的全新 core／native 安装验收全部通过。warnings 保留，不用作通过断言；初轮格式失败及远端修正补丁有记录，没有修改成交 oracle 来掩盖差异。

| 实际核验 | 结果 |
| --- | --- |
| 单次 trade 分配与总量 | 两平台及安装后 CLI 均得到 own fill2/0、external consumed1/3；每笔之和等于原始 trade3，每个 checkpoint 的 A+R+B 等于原观测；horizon Q2/2 |
| 独立命题与标记 | 标准 fee2/0、net−2/0、gt0 F/F；独立 bid102 冻结数据得到 net+2/0、gt0 T/F；native 测试另冻结 ge0 得 T/T。只评价新 tagged claim，source claim 不评价，findings=[] |
| 非固定常量与容量 | 非1的 price/size increments、q3、不同资金／价格得到 native3/1；gross churn、无撤单控制、同接收时刻、重复 hook 和空容量均符合各自 oracle |
| 接受、horizon 与 cleanup | 真实首 capture 接受检查 inclusive Q5 与 A3/R2；front 最终 FILLED，无多余撤单；back horizon R2，之后同一原生时刻真实 CANCELED，预测总量0，观测缓存仍按原源记录 |
| 持久化与攻击 | 先 intent／源工件后 worker；第二模型失败保留首个成功；flow、来源、时钟、金额、horizon、cleanup、生命周期及费用攻击拒绝，取得的原始结果保留诊断；失败／中断不退款 |
| 预算不确定性与配对条件 | 实际提交槽后注入 reserve 异常，返回 budget_consumed=null，inspect 可见已消费未决槽；实际两次 native 运行注入不同环境标签，各自 verified，配对仍为 ineligible |
| 只读与分发 | 同一协议2个不同 attempt，共同预算 remaining0；耗尽退出8且不占新槽；inspect 不调用 native，完整字节树不变；core 缺 extra 明确失败并保留已耗尝试 |

实际安装报告保存原始 synthetic observations、冻结协议、intent／receipt、native result／独立 evaluation、horizon／cleanup、共享预算和只读检查。Artifacts 为 `tagged-queue-execution-<os>-9e33d7dfd51a47eb12ea6ca996708ca90f189923`、`tagged-queue-source-wheel-9e33d7dfd51a47eb12ea6ca996708ca90f189923` 和 core 缺 extra 报告，保留30天。源包验收使用实际 tar.gz 内的脚本／样例及实际安装的 wheel，没有用 checkout 替代发行物。

AI 静态交叉审查单独计为 AI 审阅：补强过提前伪称 cleanup hook、已占槽后异常误报未消耗，以及配对环境不一致时仍报告真假关系的问题。独立人类领域复核与真实市场／采用证据仍未取得；本轮不据此增加访谈或工时记录。

## S06-02c：移交双模型证据并由 core 独立重建

合同见 [Tagged Pair Evidence v1](../contracts/tagged-pair-evidence-v1.md)，决策见 [ADR 0019](../adr/0019-portable-tagged-pair-evidence.md)。新固定十二角色目录同时包含完整 tagged protocol、development 原始来源闭包、两份真实 result／evaluation／receipt，以及确定性 assessment。旧 baseline 八角色 reader 保持严格，不通过改 kind 或放宽原 loader 接纳新模型。

导出前重新审计实际 committed run、accepted development 数据和两份独立 reservation；导出本身不启动 worker、不占新 attempt、不退款。相反参数顺序按 policy 排列后应产生同一 bundle ID；已有目标不覆盖，发布后 parent fsync 未确认时保留完整目标并报告持久性未知。

离线核验在无 native、数据库、原 registry／ledger 或网络的 core 环境，从 raw 重新生成 normalized／quality report、两侧 witness／实际回调审计和 assessment。源、单位、gross flow、分配、费用、账户、回执、horizon 或 claim 不能靠重算外层 hash 洗成 verified。两份 attempt ID／index 必须不同且符合冻结共同预算，但包不宣称证明完整 attempt 历史、原 ledger commitment 或作者身份。

预设验收包含 F/F、T/F、T/T 的独立冻结案例、原生生成后移交并删除原状态、core 环境拦截 native／SQLite／network／worker／store 构造仍能复核、严格类型隔离、可信 bundle ID pin、不改文件字节，以及完全重算 hash 后的守恒攻击拒绝。实际 wheel 和实际 sdist 中的脚本／样例均须执行同一链路，报告及原始 sealed bundles 保存30天。

本轮测试、构建、格式化和原生执行全部在远端，实际记录见下文。findings 保持空数组，模型范围仍限于声明的有限 public 路径下 tagged reconstruction；最终 finding、确认集 lifecycle、跨协议试验账本、外部人类复核与真实采用证据仍是后续门。

### S06-02c 远端验收记录

最终功能代码 head `b103f60dcfdbe81929466de71289fc93b22daac3` 的 [Engineering 40292165942](https://github.com/Darrenus/tickwitness/actions/runs/40292165942) 与 [Documentation 40292165780](https://github.com/Darrenus/tickwitness/actions/runs/40292165780) 共13 checks 全部通过；实际 merge checkout 为 `3afd7b5d04fa047b2374b6025653cc80e3ad3f36`。本记录是该已验证代码的文档补充，后续文档 head 有独立 CI，不与功能 head 混记。

核心 Ubuntu 24.04／macOS 15 × Python 3.12／3.13／3.14 六组合各 **1918 passed / 111 optional-native skips**；原生 Ubuntu 24.04 与 macOS 26／Python 3.12 各 **2027 passed / 2 core-only skips / 313 warnings**。lint、171 文件格式、79 source files 严格类型、文档、实际 wheel 以及实际 sdist 的独立 core／native 安装验收全部通过。warnings 保留，不作为通过断言。首轮 identity 调用签名与格式／unused variable 失败有远端记录；修复实现，没有放宽 oracle。

| 实际核验 | 结果 |
| --- | --- |
| 新生成原生配对 | 两平台及实际 sdist／wheel 各独立冻结3案例：bid100／gt0 为 F/F，bid102／gt0 为 T/F，bid102／ge0 为 T/T；均封存完整 source／result／evaluation／receipt／assessment |
| 删除原状态后移交 | 原 store／registry／ledger 和请求目录删除，包移动至新目录后由另一份实际安装的 core wheel 复核；native、SQLite、network、worker 和原 store 构造均被护栏阻断，复核仍通过 |
| 历史证据回归 | core 矩阵及安装后的 core 使用 #85 实际 [原生记录](https://github.com/Darrenus/tickwitness/actions/runs/40286175944/job/121450395382) 的两份 golden，重新构建原 source manifest 并核对已记录 dataset ID；没有用模拟 callback 替代历史证据 |
| 全量 hash 重算攻击 | 修改 trade 分配并重算 result、evaluation、receipt、assessment 和 manifest 所有相关 hash，仍被独立守恒审计拒绝；虚假净值／真值、时钟、接受、费用、horizon、cleanup 和坏回执同样拒绝 |
| 配对与发布绑定 | 两 attempt ID／index 均须不同；同一槽换 nonce 不能伪装两次尝试；反序参数和反序执行 index 可按 policy 正规配对；exporter 返回另一份合法配对也明确拒绝 |
| 身份／未知与只读 | expected bundle ID 错误拒绝；环境不同保留审计但配对 ineligible，费用歧义不得当 false；重复导出不同目录身份相同，既有目标不覆盖，复核完整字节树不变 |
| 固定树与失败恢复 | 未知／隐藏／缺件／symlink／FIFO、schema／大小／数量预算、旧新格式混用拒绝；no-replace 并发只有一个提交，ENOSPC 与发布后 fsync 故障区分并保留已发布目标 |

报告与实际 sealed 目录以 `tagged-pair-core-3afd7b5d04fa047b2374b6025653cc80e3ad3f36`、`tagged-pair-evidence-<os>-3afd7b5d04fa047b2374b6025653cc80e3ad3f36`、`tagged-pair-source-wheel-3afd7b5d04fa047b2374b6025653cc80e3ad3f36` 保存30天。source-wheel 报告同时区分历史 golden 复核与3个 fresh native cases，实际脚本／样例来自 tar.gz，验证器为实际 wheel 的全新 core 安装。本机只做文本编辑、静态审查、Git／gh 和下载报告读取。

AI 静态交叉复核单独记录为 AI 审阅，补强了 assessment 深层序列化校验及 exporter 返回错误合法包的边界。验证的是选定证据的来源闭包与模型内经济算术；离线不证明 native 日志真实出处、原 ledger commitment、完整尝试历史或作者身份。独立人类领域复核、真实市场和采用证据仍未取得，工时／访谈／性能记录未新增。

## S06-02d：独立冻结 finding 签发与报告合同

合同见 [Tagged Findings v1](../contracts/tagged-findings-v1.md)，决策见 [ADR 0020](../adr/0020-frozen-tagged-finding-authority.md)。原 tagged execution／pair assessment 的 finding 权限和完整字节不改写；新权限显式绑定完整 subject、新 claim、观测／gross／ReplaySpec、固定两政策、eligibility、真值映射与限制。冻结不读取行情、不解封确认集、不占研究 attempt，也不证明事前预注册或人类审批。

预设规则为 F/F→COUNTEREXAMPLE_FOUND，T/F 或 F/T→NOT_IDENTIFIABLE_WITHIN_MODEL 与 COUNTEREXAMPLE_FOUND，T/T→已列政策范围内的 NO_COUNTEREXAMPLE_FOUND。NOTID 的目标是每个隐藏分配下谓词 P(w) 的真值能否由同一公开观测确定；COUNTER／NO_COUNTER 的目标是 U_S=∀w∈S P(w) 的已列集合稳健满足检查。相反见证已使 U_S 为 false，不能将该聚合命题称为不可识别。每份结论带明确 conclusion_target、可沿封存内容核对的 run／attempt／intent／result／evaluation 见证与同一 scope。两政策覆盖完整不等于所有 admissible worlds 穷尽；条件反例不是对真实历史实现的反驳，新命题与 source v2 原命题分开，不预测真实插单、历史所有权、市场冲击或未来收益。

同环境、可评价的两份布尔见证是签发前提。有效但 ineligible 的源包保留原评价，退出9且不发布报告目录；坏证据、缺件、未完成、模型或费用矛盾不得转成 false、INSUFFICIENT_EVIDENCE 或任何 finding。

十四角色新包包含原十二角色闭包和独立 finding_protocol／finding_report，旧八／十二角色 reader 保持严格。领域候选只声明 source CONTENT_CLOSED／publication UNASSERTED；应用在完整十四角色封存并复核或离线读取复核后返回 FINAL，仅表示内容闭合，不认证作者、人类领域审批、原始发布、完整 ledger 或断电持久性。撤回／更正 lifecycle 尚未实现。

预设验收在前序原生配对流程中新增独立冻结的 bid100／ge0（F/T），与 F/F、T/F、T/T 共四种真值方向一起签发；F/T 的反例只应引用 front。报告流程复用这些真实 native 配对和保留的历史记录，再删除 issuer 的 source pair 副本与 finding registry，仅由独立 core 安装复核；签发自身不新增 native 运行或 attempt。完整 hash 重算后的报告与分配攻击、错误 subject／权限／pin、未知拒签、类型隔离、只读和无覆盖边界的实际结果见下文。实际 wheel、实际 sdist 脚本、两平台原生后的 core 签发链路及原始十四角色包留存30天。本轮全部项目执行在远端；外部人类、真实市场、访谈、工时、性能及采用数据不补造。

### S06-02d 远端验收记录

最终功能 head `871d4cec3aff6a3f655658148b3f037761cee022` 的 [Engineering 40313624621](https://github.com/Darrenus/tickwitness/actions/runs/40313624621) 与 [Documentation 40313624711](https://github.com/Darrenus/tickwitness/actions/runs/40313624711) 共13 checks 全部通过；实际 merge checkout 为 `666cd6b92b6916cd8cf35424c31a5b0773c6ef87`。本节是该已验证代码的文档补充，后续文档 head 的独立 CI 不与功能 head 混记。

核心 Ubuntu 24.04／macOS 15 × Python 3.12／3.13／3.14 六组合各 **2091 passed / 111 optional-native skips**；原生 Ubuntu 24.04 与 macOS 26／Python 3.12 各 **2200 passed / 2 core-only skips / 313 warnings**。lint、184 文件格式、85 source files 严格类型、文档与实际 wheel／sdist 的 core／native 安装验收全部通过。warnings 保留，不作为通过断言；首轮 pytest 保留参数名导致收集失败及格式／长字面量失败有远端记录，修复后没有放宽规则或 oracle。

| 独立预设原生配对 | 实际签发结果与见证 |
| --- | --- |
| bid100／gt0：F/F | COUNTEREXAMPLE_FOUND，引用 front、back 两份 false 见证 |
| bid102／gt0：T/F | NOT_IDENTIFIABLE_WITHIN_MODEL 引用两份相反见证；COUNTEREXAMPLE_FOUND 只引用 back |
| bid102／ge0：T/T | NO_COUNTEREXAMPLE_FOUND，仅覆盖已列两政策，admissible_world_space_exhausted=false |
| bid100／ge0：F/T | NOT_IDENTIFIABLE_WITHIN_MODEL 引用两份相反见证；COUNTEREXAMPLE_FOUND 只引用 front |

上述四案均在两平台及实际 source archive／wheel 工作流中先独立冻结并产生真实 native 配对，再由 core 冻结权限、签发十四角色包并迁移复核。COUNTER／NO_COUNTER 的 conclusion_target 为已列集合的稳健满足，NOTID 为单个隐藏分配下谓词的识别；T/F 或 F/T 时稳健满足已确定为 false，不将其称为未知。历史 #85 的 F/F、T/F 与 #86 的实际 T/T 记录作为只读 golden 回归，没有伪造 callback。

| 边界核验 | 实际结果 |
| --- | --- |
| 权限、来源与固定规则 | 旧 subject／run／assessment 权限与字节保持原样；独立 authority 不接受 comparator、threshold、finding type 或 scope 的有利改写；每个结论都有目标、scope、限制与完整见证引用 |
| 已验证但不可签发 | 对实际封存配对的环境标签构造受控不一致并重审，退出9且不产生报告目录；原评价／false 见证和文件字节保留，不改成 false、INSUFFICIENT_EVIDENCE 或其他 finding |
| 发布与 FINAL | 错误 source pin、subject、publisher 换包均拒绝；完整十四角色写入并读回复核后返回 FINAL，领域正文仍为 CONTENT_CLOSED／UNASSERTED；认证、原发布和人类审批标志保持 false |
| 独立 core 复核 | 删除 issuer 的源包副本与 finding registry，移动报告包后在禁止 native、数据库、网络、worker 和原 registry 构造的安装 core 中重验成功，文件字节树不变 |
| 全量 hash 重算攻击 | 改写结论类型或 trade 分配，并重算关联 report／evaluation／receipt／assessment／manifest hash，仍被固定 rubric 或原始 source 审计拒绝；无效／未完成记录不能进入 finding |
| IO 与兼容性 | 旧8／12／新14格式互拒；身份 pin、固定角色／大小／数量／哈希、symlink／FIFO／隐藏条目、无覆盖／并发、ENOSPC 与发布后 fsync 不确定性均覆盖 |

真实报告与十四角色目录保存为 `tagged-findings-core-666cd6b92b6916cd8cf35424c31a5b0773c6ef87`、`tagged-findings-<os>-666cd6b92b6916cd8cf35424c31a5b0773c6ef87`、`tagged-findings-source-wheel-666cd6b92b6916cd8cf35424c31a5b0773c6ef87`，留存30天。core-only 历史记录与四个 fresh native 来源案例明确区分；source archive 使用实际 tar.gz 的脚本／样例及实际安装的 wheel。本机仅文本编辑、静态审查、Git／gh 和下载报告读取。

AI 静态交叉复核单独记为 AI 审阅，重点纠正过“单解释谓词识别”与“全称稳健满足”混为同一结论目标的歧义。该 profile 的数学见证不认证真实历史所有权、插单、市场影响、私有执行、作者或完整试验历史；独立人类领域复核与真实市场／用户采用证据仍未取得。owner 接受之前不关闭故事；撤回／更正、确认集 lifecycle 与跨协议完整账本仍为后续能力，不补造实际工时或访谈。
