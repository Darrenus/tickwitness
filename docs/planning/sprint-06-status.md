# Sprint 6 队列约束与资格状态

更新：2026-10-26（Asia/Singapore）。Owner 已合并 PR #79–84；Sprint 5、S06-01 的资格／共同预算／持久双模型执行，以及 S06-02a 的观测与真假语义资格进入 `main`。本轮基线为 #84 merge `e018100df57e66376c810edce4fdf9ffec698e28`。已有技术预览 `0.1.0a1` 保持原发行物，`0.2.0.dev0` 仍未发行。

已接受的 [PR #84](https://github.com/Darrenus/tickwitness/pull/84) 实现 S06-02a；历史远端记录见下文。本轮继续 S06-02b：独立冻结 tagged queue claim、inclusive 观测投影及 relabel 干预，解决单笔 trade 重复分配。新合同描述有限 public 观测下的条件重建；最终 finding 和独立 sealed tagged evidence 流程仍未开放。

| 故事 | 当前切片与接受边界 | 状态 |
| --- | --- | --- |
| S06-01 / #16 | S06-01a/b 已接受；冻结共同预算、持久前后模型执行与独立审计 | Owner 已合并 #83 |
| S06-02 / #17 | S06-02a 已接受；S06-02b 新命题、观测／干预合同、守恒分配与持久执行通过远端验收 | In progress；[PR #85](https://github.com/Darrenus/tickwitness/pull/85) 待 owner 接受，生产 `NOT_IDENTIFIABLE_WITHIN_MODEL` 保持关闭 |
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
