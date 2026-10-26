# Sprint 6 队列约束与资格状态

更新：2026-10-26（Asia/Singapore）。Owner 已合并 PR #79–83；Sprint 5 与 S06-01 的资格、共同预算及持久双模型执行进入 `main`。本轮基线为 #83 merge `c78714bb9fca3a3a0ce21d29ae189d9ee0e5cd1d`。已有技术预览 `0.1.0a1` 保持原发行物，`0.2.0.dev0` 仍未发行。

已接受的 [PR #83](https://github.com/Darrenus/tickwitness/pull/83) 实现 S06-01b；历史远端记录见下文。本轮继续 S06-02a：先验证观测投影、单次 trade 分配与真假比较的语义，提供已提交双模型 run 的只读资格检查。资格通过不等于实际观测相容性或原命题判定已获授权。

| 故事 | 当前切片与接受边界 | 状态 |
| --- | --- | --- |
| S06-01 / #16 | S06-01a/b 已接受；冻结共同预算、持久前后模型执行与独立审计 | Owner 已合并 #83 |
| S06-02 / #17 | S06-02a 先验证明确投影、守恒反例、候选谓词真值表和只读配对 | In progress；生产 `NOT_IDENTIFIABLE_WITHIN_MODEL` 保持关闭 |
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

本切片远端验证完成后再补实际 case/check 数、head／merge SHA、完整矩阵与 wheel/sdist artifact。S06-02 整条故事尚未接受；需要后续独立冻结 queue claim、观测／干预合同及 sealed evidence 流程，才能考虑实际 finding。
