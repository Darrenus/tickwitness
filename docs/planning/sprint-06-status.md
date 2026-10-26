# Sprint 6 队列约束与资格状态

更新：2026-10-26（Asia/Singapore）。Owner 已合并 PR #79、#80、#81，Sprint 5 的声明、耦合时钟压力与只读配对能力进入 `main`。当前基线为 `ccdf7d20cdcb3787d2880eb9c352a274fee8eed1`；其 [Engineering 40252756496](https://github.com/Darrenus/tickwitness/actions/runs/40252756496) 与 [Documentation 40252756404](https://github.com/Darrenus/tickwitness/actions/runs/40252756404) 均通过。已有技术预览 `0.1.0a1` 保持原发行物，`0.2.0.dev0` 仍未发行。

本轮进入 S06-01 的资格与只读约束切片（S06-01a），不把两种配置名称或部分研究试验记为完整故事交付。

| 故事 | 当前切片与接受边界 | 状态 |
| --- | --- | --- |
| S06-01 / #16 | 先取得固定原生模型资格，提供受限 external FIFO shadow queue 的声明、来源绑定与约束检查；之后再做版本化队列族协议和持久双模型执行 | In progress；本切片不关闭整条故事 |
| S06-02 / #17 | 两个受支持且独立验证的观测相容解释，才可进入最小真假分歧判定 | 尚未实现；`NOT_IDENTIFIABLE_WITHIN_MODEL` 保持关闭 |
| S06-03 / #18 | 真实近期问题访谈累计 8–12 次，反馈关联工作流阻力 | 未取得新增访谈证据；不虚填次数、采用或独立领域验收 |

原故事验收与容量仍见 [Sprint backlog](sprint-backlog.md#s6--l2-队列解释与证据不足判定)。实际投入工时尚未登记。S06-01 原估算不因生成代码自动视为已完成；复杂执行能力需要单独可验收切片，不通过修改旧协议或跳过预算提前打开。

## 为什么先资格化

当前 `ReplaySpec v1` 和 `ExecutableProtocol v2` 没有可变队列解释，冻结的是现有 pinned native semantic；独立账务审计同样只支持该 profile。S05 的 scenario intent 仅表示额外接收时间压力，S05 的比较器要求相同 engine/spec/environment。它们不能静默接纳新的 queue profile，也不能把 `queue_position=True/False` 直接改名为相容的 Q-front/Q-back。

拟验证的公开组合为 `queue_position=False`、公开 `FillModel` 和 `SimulationModule.pre_process`，在同一份固定 L2 观测上驱动显式影子队列约束。影子模型的观测簿不包含策略自己的模拟订单；聚合观测与策略成交的反馈、市场影响和真实交易所队列位置仍未证明。即使有限 fixture 复放成功，也只能在此阶段报告 `MODEL_SENSITIVITY`，不能签发真实历史相容性。

新模型需要逐事件的输入引用、价位总量、gross additions/cancellations、trade 分配及队前/队后状态，以便独立检查守恒与非负。仅凭净深度下降不能知道撤单数量或位置；不能把同一成交同时扣作 trade 和 cancellation。未记录的 gross 分解属于明示模型条件，不因一份自洽的 JSON 变成观测事实。精确请求与输出见 [Queue Constraints v1](../contracts/queue-constraints-v1.md)。

## 本切片的读写边界

`validate-queue-constraints` 读取已有 v2 protocol 和实际 development 输入，注入并核对来源绑定，再检查声明的受限 frame。确认集在请求文件或任何仓库访问前拒绝。它不运行 native、不给策略 fill/PnL、不占 attempt、不改变输入或协议，也不发布新的 catalog dataset、intent 或 outcome。

一份约束检查成功仅说明来源绑定及所列算术/顺序约束成立；旧 v2 protocol 不因此授权新的 queue profile。报告必须保留模型类别、未知撤单位置及执行未批准状态。无效 frame、引用、单位、整数、来源或不可支持状态都明确拒绝，不作为亏损或反例。

## 待收集的本轮远端证据

| 门 | 所需实际记录 |
| --- | --- |
| 声明与不可变身份 | exact JSON、单位、整数、重复字段与未知字段负例；detached document；任一来源/约束变化产生新身份 |
| 约束可行性 | 同观测两种受限分配、逐步守恒/非负、未知位置、非法引用/重复计量/不支持 frame 拒绝；不生成策略 fill 或 PnL |
| 权限与只读 | confirmation 先拒、缺失根不创建、完整字节树无改动、无 ledger/engine 调用、不会读取 confirmation 数据 |
| 固定原生资格 | pinned engine/environment、相同观测、两种公开模型配置、逐步 queue trace 与原始 native 输出；失败和不匹配保留，不改 oracle 掩盖结果 |
| 分发与回归 | 远端 core/native 矩阵、安装后 CLI、实际 wheel/source archive 样例、已有 baseline 与 S05 对比路径继续严格 |
| 人类接受 | Owner 对该切片的审阅；独立人类领域复核仍有缺口，AI 交叉审查单独标识 |

本状态页初稿尚不填本轮通过数量、性能数字、PR/run ID 或资格结论；源文件和测试存在不等于已经执行。所有新增测试、构建、回放及资格实验继续在远端进行，本机仅编辑/审查文件和 Git/gh 控制。

## 后续执行门

持久队列执行须先冻结同一观察源、队列约束／解释集合、engine/adapter semantic、策略和共同预算。每次引擎调用在同一父协议下占一次 attempt；不得克隆两个协议分别获得新预算，或借“qualify”名称在用户数据上反复观察策略结果。执行前持久不可替换 intent，失败、超时与中断不退款。

新 queue trace、receipt 与审计应显式版本化；旧 v2、baseline receipt/bundle 和 S05 比较器继续拒绝新模型，不放宽其原保证。两解释是否真正代表同观测下的可行世界，要在全部列明约束与 native 结果均可独立核验后另行接受；在此之前保持模型敏感性表述，S06-02 的不可识别 finding 不能提前打开。
