# Sprint 6 队列约束与资格状态

更新：2026-10-26（Asia/Singapore）。Owner 已合并 PR #79、#80、#81，Sprint 5 的声明、耦合时钟压力与只读配对能力进入 `main`。当前基线为 `ccdf7d20cdcb3787d2880eb9c352a274fee8eed1`；其 [Engineering 40252756496](https://github.com/Darrenus/tickwitness/actions/runs/40252756496) 与 [Documentation 40252756404](https://github.com/Darrenus/tickwitness/actions/runs/40252756404) 均通过。已有技术预览 `0.1.0a1` 保持原发行物，`0.2.0.dev0` 仍未发行。

本轮 [PR #82](https://github.com/Darrenus/tickwitness/pull/82) 完成 S06-01 的资格与只读约束切片（S06-01a），远端验证已通过，待 owner 接受；不把它记为整条故事已交付。

| 故事 | 当前切片与接受边界 | 状态 |
| --- | --- | --- |
| S06-01 / #16 | 固定原生模型资格、external FIFO shadow queue 声明与来源/约束检查已实现；下一切片做版本化队列族协议和持久双模型执行 | In progress；PR #82 待 owner 接受，不关闭整条故事 |
| S06-02 / #17 | 两个受支持且独立验证的观测相容解释，才可进入最小真假分歧判定 | 尚未实现；`NOT_IDENTIFIABLE_WITHIN_MODEL` 保持关闭 |
| S06-03 / #18 | 真实近期问题访谈累计 8–12 次，反馈关联工作流阻力 | 未取得新增访谈证据；不虚填次数、采用或独立领域验收 |

原故事验收与容量仍见 [Sprint backlog](sprint-backlog.md#s6--l2-队列解释与证据不足判定)。实际投入工时尚未登记。S06-01 原估算不因生成代码自动视为已完成；复杂执行能力需要单独可验收切片，不通过修改旧协议或跳过预算提前打开。

## 为什么先资格化

当前 `ReplaySpec v1` 和 `ExecutableProtocol v2` 没有可变队列解释，冻结的是现有 pinned native semantic；独立账务审计同样只支持该 profile。S05 的 scenario intent 仅表示额外接收时间压力，S05 的比较器要求相同 engine/spec/environment。它们不能静默接纳新的 queue profile，也不能把 `queue_position=True/False` 直接改名为相容的 Q-front/Q-back。

已资格验证的公开组合为 `queue_position=False`、公开 `FillModel` 和 `SimulationModule.pre_process`，在同一份固定 L2 观测上驱动显式影子队列约束。影子模型的观测簿不包含策略自己的模拟订单；聚合观测与策略成交的反馈、市场影响和真实交易所队列位置仍未证明。有限 fixture 复放成功仍只能报告 `MODEL_SENSITIVITY`，不能签发真实历史相容性。

新模型需要逐事件的输入引用、价位总量、gross additions/cancellations、trade 分配及队前/队后状态，以便独立检查守恒与非负。仅凭净深度下降不能知道撤单数量或位置；不能把同一成交同时扣作 trade 和 cancellation。未记录的 gross 分解属于明示模型条件，不因一份自洽的 JSON 变成观测事实。精确请求与输出见 [Queue Constraints v1](../contracts/queue-constraints-v1.md)。

## 本切片的读写边界

`validate-queue-constraints` 读取已有 v2 protocol 和实际 development 输入，注入并核对来源绑定，再检查声明的受限 frame。确认集在请求文件或任何仓库访问前拒绝。它不运行 native、不给策略 fill/PnL、不占 attempt、不改变输入或协议，也不发布新的 catalog dataset、intent 或 outcome。

一份约束检查成功仅说明来源绑定及所列算术/顺序约束成立；旧 v2 protocol 不因此授权新的 queue profile。报告必须保留模型类别、未知撤单位置及执行未批准状态。无效 frame、引用、单位、整数、来源或不可支持状态都明确拒绝，不作为亏损或反例。

## 本轮验收门

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

## 后续执行门

持久队列执行须先冻结同一观察源、队列约束／解释集合、engine/adapter semantic、策略和共同预算。每次引擎调用在同一父协议下占一次 attempt；不得克隆两个协议分别获得新预算，或借“qualify”名称在用户数据上反复观察策略结果。执行前持久不可替换 intent，失败、超时与中断不退款。

新 queue trace、receipt 与审计应显式版本化；旧 v2、baseline receipt/bundle 和 S05 比较器继续拒绝新模型，不放宽其原保证。两解释是否真正代表同观测下的可行世界，要在全部列明约束与 native 结果均可独立核验后另行接受；在此之前保持模型敏感性表述，S06-02 的不可识别 finding 不能提前打开。
