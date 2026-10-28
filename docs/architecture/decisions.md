# TickWitness 初始架构决策记录

状态：Proposed，2026-10-25。owner 可在 Sprint refinement 接受、替代或拒绝；本记录不代表相关能力已实现。每次改动保留原决定及替代原因，新增不可变 ADR 编号。

## ADR-001 采用领域模块化单体与独立执行 worker

问题：单维护者需要清楚的领域边界，也需要限制长任务与策略执行的影响。决定：领域和应用服务采用模块化单体，长任务由隔离 worker 执行；bounded context 是模型/所有权边界，不机械等同网络服务。代价：需要自动依赖检查与应用层契约，不能靠部署隔离掩盖耦合。

重评条件：存在独立团队所有权、不同故障/权限边界或独立扩缩容的实测需求。仅因为请求量增长不自动拆分所有 context。DDD 参考 [Bounded Context](https://martinfowler.com/bliki/BoundedContext.html)。

## ADR-002 优先交付可复验的研究判定

决定：判定绑定冻结协议、输入、假设空间、已执行场景、引擎版本与预算；观测相容解释和反事实压力场景分开。有限搜索结果仅声称找到反例/本预算未找到/证据不足/执行失败；最小性声明匹配算法保证。

代价：结果比单个收益数字复杂，UI 与 API 必须解释范围；不能用 PASS 字段掩盖未知。重评需要领域证据和版本迁移，不以营销简化判定。

## ADR-003 复用一个现有回放引擎并以反腐层接入

决定：Sprint 1 timebox 比较 HftBacktest 与 NautilusTrader 的 wheel/平台、语义、定制场景、输入要求、许可与测试成本，Sprint 2 选一个默认 adapter。核心域不引用其类，capability contract 说明支持级别；对齐单位、费用、队列、估值及时间语义后才比较结果。

暂不造两套完整回测器。可手算参考实现只用于微型语义检查。第二引擎须有外部需求、明确边界和 adapter 维护预算。参考 [HftBacktest](https://github.com/nkaz001/hftbacktest)、[NautilusTrader](https://github.com/nautechsystems/nautilus_trader)。

2026-10-25选型门更新：S1比较已获owner接受，但S2[补测](../research/hftbacktest-selection-gates.md)发现固定HFT版本的部分成交账务不一致、fill轮询不完整及终止时钟陈旧。单次完整成交的受限路径可继续研究，不能据此批准产品完整执行模型。**默认adapter决策暂缓**，待核对替代引擎的L2/partial能力或经验证的上游修复成本；不会静默换成无部分成交模型。S02-02不可变数据发布可独立交付，其引擎选型验收项保持未完成。

同日后续补测与有限选型提案见ADR-008；上段保留为当时的决策依据，不覆盖原始失败证据。

## ADR-004 原始证据不可变，catalog 与分析存储分开

决定：原始数据和制品采用 content-addressed immutable objects + manifest；规范化列数据使用 Parquet；DuckDB 负责只读分析，不作为并发任务状态库；SQLite 支持本地 catalog 与事务，jobs/state 遵守单写/事务边界。冻结后修订创建新版本。

不强制全面 event sourcing。状态表加审计事件足以满足初期追溯；跨模块可靠通知由事务 outbox/幂等消费逐步实现。PostgreSQL/S3-compatible storage 在多人/多 worker 的实测锁竞争、部署或权限需求出现时启用，不在首版同时维护两套后端。

## ADR-005 可信本地策略与不可信代码执行分开支持

决定：最早发布明确仅支持用户信任的代码；不可信策略进入受限 Linux worker，评价器独立持有冻结输入/判定权，网络、挂载、CPU/RAM/pids/时限/磁盘有边界。远程/多租户为独立安全 gate。

代价：不同平台能力不完全相同。不能把 Python 进程或普通容器配置写成已证明强隔离。重评需外部安全复核与有预算的托管部署计划。

## ADR-006 采用 Apache-2.0 软件许可

状态：Accepted，2026-10-25，owner 已明确选择。决定：仓库 public，项目自有软件与文档采用根目录 Apache-2.0 许可证；贡献按同一许可接收。依赖与数据权利单独登记，启动软件发行前检查所有传递依赖和数据分发方式。

重评：新增依赖不兼容或商业模式需求改变；既有已授予权利不能通过修改文件简单撤回。不得自动将第三方数据、引擎或插件纳入本项目软件许可。

## ADR-007 CLI/SDK 先行，所有入口共享应用语义

决定：CLI/SDK 构成早期完整产品；HTTP、MCP 和 UI 是相同应用用例的 adapter，不直接操作数据库。UI 只显示真实 job、场景、证据和 unknown/error；不使用假后端状态证明产品完成。

代价：首版视觉能力有限；优先保证用户能从自己的流程调用并独立复验。UI 投入由用户定位任务耗时和采用反馈触发。

## ADR-008 首个有限L2 adapter选择NautilusTrader稳定v1

状态：Accepted，2026-10-26，owner已合并PR#75。选择固定NautilusTrader **1.231.0**作为S3首个单资产L2 adapter的集成目标，依据[综合记录](../research/engine-selection.md)和[六案例L2补测](../research/nautilus-l2-selection-gates.md)。两个独立进程结果一致，分时/同刻partial的fill回调与持仓、现金、费用对齐；HftBacktest2.4.4的已知失败门保持记录，不启用其产品默认路径。

范围约束：adapter尚未实现；数据步进时间不代表任意时间精确命令到达；EOF不自动drain，待处理命令必须报告incomplete；S6精确观测相容队列见证仍closed。正式性能、平台wheel、费用/单位、确定性及输入反腐映射由S3契约检查后逐项开放。重评条件包括稳定版本语义变化、复验失败、许可/维护成本或所需公开扩展无法实现。

第三方LGPL-3.0-or-later保留独立许可，后续只通过optional extra/独立worker边界引入，不能重标Apache或隐式进入核心依赖。本批不打包引擎、不改第三方源码；发布组合制品前仍须检查实际链接、再分发与NOTICE义务。依赖隔离本身不构成许可豁免。

## ADR-009 冻结声明与执行许可分开

状态：Accepted，2026-10-26，owner已合并PR#75。协议以canonical bytes的SHA-256为身份，claim以规范化命题的独立hash为revision。应用验证真实dataset、数据质量、向前不交叠分区和策略源码后，通过独立不可变registry发布；模型、数据、参数或策略变化生成新protocol，不覆盖旧版本。domain只处理值，存储与CLI通过application ports连接。

当前冻结结果始终`execution_ready=false`，只有development读取，任何confirmation读取在repository初始化前被拒绝。该政策不对宿主owner保密，也不证明时间绑定、模型有效或统计独立。完整ClaimSpec/trial生命周期、累计预算、确认解封/一次性使用和执行sandbox由后续切片实现，不能用当前声明hash代替实际执行证据。完整schema见[协议合同](../contracts/frozen-protocol-v1.md)。

## ADR-010 先交付显式受限的引擎验收profile

状态：Accepted，2026-10-26，owner已合并PR#76。以独立ReplaySpec和ReplayPort实现可信本地dataset qualification，只支持EUR/USD内置单限价买单。原有FrozenProtocol v1不升级为可执行，也不被此入口解封。先验证排序、单位、源引用、逐笔账务和终止完整性，再另行版本化研究执行合同。

`receive_order_v1`明确映射native双时间到receive，并保留来源原始时点；不是UTC校准。公开pre_process在撮合前绑定source_ref；submit/cancel都有独立receipt，FILLED不抹掉仍在途取消。未决命令或开放订单均incomplete，不造未来行情推进结算。native实际费用与精确理论值分别记录，不隐藏其f64/Money舍入。

worker采用schema化JSON、独立CWD、`-I`、进程组终止和输出/墙钟预算；这是可信代码故障边界，不是任意Python沙箱或RAM硬配额。可选引擎依赖固定版本与uv.lock，核心仍无必需第三方runtime。扩大资产、策略、时钟、完成规则或执行权限必须先补合同/测试与维护证据，不能只放开枚举。见[回放指南](../replay.md)及[合同](../contracts/replay-v1.md)。

## ADR-011 可执行协议与可迁移一致性证据分开建模

状态：Proposed，2026-10-26。本批新增ExecutableProtocol v2，以显式builtin/engine/spec/evaluation政策与开发集数据、claim和预算绑定；保持v1不可执行且确认集永不解封。每次native运行前占不可退款attempt，终态不覆盖，中断状态保留未知；预算只约束per-protocol，完整统计family/exposure账本仍另建。

采用最后观测bid的受限做多mark，独立重建源fields、订单生命周期、成交、费用和缓存账户。native费用算法用精确有理数模拟binary64与两级Money量化，不能只信任自报actual/difference；原生精度模式导致费用不唯一则不给估值或claimtruth。model、mark与独立审计必须和实际数据/结果一起封存，不用单个布尔PASS代表全部研究结论。

bundle仅固定目录/8role，原子no-replace发布，安全有界读取；offline verifier无native/SQLite依赖并重新计算规范化、绑定、账务、估值和claim观察。回执显式不认证作者、native重放、确认外部引用或完整attempt历史；hash自洽不能替代出处真实性。提交后fsync失败不删除已发布目录，单列durability未知。扩大可执行策略、档位填价、账户/资产、验证级别或签名承诺须版本化合同和新测试。见[完整工作流](../evidence-workflow.md)。

## ADR-012 场景声明与延迟压力执行分开验收

状态：Proposed，2026-10-26。S05-01 先交付只读的 AssumptionSpec / ScenarioSpec 声明与上下文输入校验，新增 `validate-scenario`；不运行引擎、不预留 attempt、不改变 ExecutableProtocol v2、既有回放语义或旧 bundle。精确合同见 [Assumption / Scenario v1](../contracts/assumption-scenario-v1.md)，用户流程见[场景校验](../scenarios.md)。

首个 typed transformation 为 `replay_receive_suffix_shift_v1`：从指定 capture anchor 起，对全部后缀声明增加同一非负纳秒量。类别固定为额外压力，不是历史观测相容解释；范围由研究者设置，未校准、校准引用为空。60 秒上限是本切片的工程支持限额，不是交易所、网络或时钟的物理证据。

领域 builder 从实际 ExecutableProtocol 与 ReplayInput 派生 protocol、development dataset、normalized data SHA 和 ReplaySpec 身份；不能由请求自行填写 bindings。应用在已有仓库只读模式下重验闭包与 accepted 报告，执行 replay preflight，检查 capture anchor 存在及时间/执行 horizon 的 int64 溢出。确认集请求必须先于任何 repository factory 被拒绝。输出只描述已经完成的来源绑定与输入约束校验，`execution_approved=false`；不签发收益、可行世界、搜索或不可识别 finding，也不宣称引擎兼容性已验收。

原因：现有 `receive_order_v1` 将 native 市场和策略使用的时间均映射到 receive，内置策略按 capture_seq 触发。全流增加常数可能只平移时间戳，改变 hash 或首处分歧不等于改变成交或命题。后缀平移即使改变相对时间，也仍未证明它等价于“市场照常、研究者晚收到信息”的独立 feed-delay 模型。

后续执行门：S05-02 必须先确定市场/观察/决策与命令到达的明确时间语义，版本化新的 adapter/clock semantic 与 derived-view lineage，防止策略提前读取未来 cache；验证零变换、全流平移负对照、可手查有效案例、同刻顺序、延迟、EOF 与审计一致性。不能改写 raw 或静默复用原 semantic_id。若只实现订单发送延迟，应明确修订范围，不能冒充接收延迟。

S05-03 的 controlled intervention 配对应披露共同条件与允许变化；不能把干预导致的数据/模型变化包装成旧比较器的 strictly paired。只有双方可评价且满足声明的完成规则时才比较冻结 metric/comparator；无成交、费用歧义、未决 EOF 或执行错误不能变成命题翻转。零变换与全流平移在本批只是后续执行资格门，不是已运行的实验。

## ADR-013 耦合回放时钟压力与持久场景身份

状态：Proposed，2026-10-26，PR #80。细化 ADR-012 后续执行范围：复用不变的 Nautilus receive-order adapter，并新增组合层 `coupled_receive_suffix_clock_v1`，明确 suffix receive 同时改变 native 市场与策略时钟。它不实现独立 venue/observer feed-delay；native 输入步骤先匹配后结算命令的资格结果不能替换为独立 timer 假设。固定案例先在远端两平台验证，再启用场景执行。精确合同见[场景执行 v1](../contracts/scenario-execution-v1.md)。

派生是纯函数：原数据、事件顺序、event_time 和 source_ref 保留，只移动声明后缀 receive；zero 保留原字节。派生 ReplayInput 使用独立 view ID，显式标记非 catalog manifest，不改写原 sealed dataset。复核重新派生，不能信任提供的派生 hash。

每次引擎调用占原 v2 protocol 的一个不可退 slot；不因 candidate/assumption 变更重置预算。预留后必须先持久完整 intent 及其制品才能构造引擎，中断保留候选归属；intent 绑定与终态发布串行且不可替换。新 scenario receipt/failure 与 baseline 类型严格分开；场景审计复用精确费用/账务逻辑，只输出 metric observation，不套用原 baseline claim 的 comparator 形成反例结论。

S05-02 的持久化和复核依赖 data/registry/runs 三根；旧八角色 bundle v1 保持只接受 baseline。独立场景 bundle 和 S05-03 通用配对留作后续独立能力，不用放宽旧 verifier 或伪造 baseline protocol 来接纳派生数据。

## ADR-014 只读受控干预关联与分层分歧报告

状态：Proposed，S05-03。使用已提交 baseline/scenario 回执关联，不增加 native 调用或预算槽；重新核验双方来源、派生、终态及账务，要求原协议、数据来源、ReplaySpec、engine 和完整 environment 一致。旧 baseline receipt、bundle 与 ReplayComparison 的严格相同条件判定保持不变；新报告为 controlled intervention，不能冒充 strictly paired。

raw 与显式字段业务投影分别给每通道首差异，保留原始值、指针和事件引用。订单角色映射仅定址处理，不能递归替换源 trade ID 的文本；只精确识别 pinned cancel reason 模板。固定报告顺序不建立跨通道全局时间/因果顺序。双方完整可评价且 mark/fee 定义一致才给有理数计算的十进制差值；不可比较保留 null/原因，无分歧也不叫策略失效。精确合同见[Scenario Comparison v1](../contracts/scenario-comparison-v1.md)。

## ADR-015 队列约束先核守恒与公开扩展资格

状态：Proposed，S06-01a。固定 Nautilus 1.231.0 的内置 queue gate 不能表达两种显式前/后撤单分配；不能把 queue_position 的开关或概率模型名称当观测相容性证明。先交付来源绑定的纯队列约束检查与固定案例公开扩展资格，精确合同见 [Queue constraints v1](../contracts/queue-constraints-v1.md)。

外部量与 shadow order 分开。gross additions/cancellations、FIFO、无隐藏流动性与 checkpoint 流时序必须明示；逐笔成交和绝对深度更新对账，不能重复扣量。两条分配 trace 的非负/量守恒仅是条件性可行性；shadow 无冲击仍未经证明，因此分类为模型敏感性候选，不签发 OBSERVATION_COMPATIBLE 或不可识别 finding。

固定原生试验使用公开模块、FillModel 与订单回调，关闭旧 queue gate、以每 capture 的 grant/consume 账本限制 shadow 容量。空 book 与 None 回退的语义、重复 hook、接受前 trade、部分成交/费用/账户及 EOF 均须远端核实；原始观测不改写。旧生产 adapter 不声明 explicit_queue_allocation 能力，旧协议及审计器严格拒绝新 semantic。

生产执行另行版本化 queue family 协议、解释集合、共同预算、intent 与审计；不得克隆两个协议重置尝试预算。固定原创资格 fixture 不属于用户研究尝试；一旦使用用户数据运行模型并暴露结果，必须先占研究预算。S06-01 未完成部分和 S06-02 finding 门保留开放，不以 qualification 文件或通过个例冒充全部生产能力。

## 后续队列决策记录

- [ADR 0016：冻结队列族和持久执行](../adr/0016-frozen-queue-family-execution.md)：共同预算、完整 intent 和独立审计。
- [ADR 0017：先资格化观测与真假语义](../adr/0017-qualify-observation-and-predicate-semantics.md)：owner 已合并 #84；旧 ghost 投影残差与候选谓词资格边界。
- [ADR 0018：独立冻结标记参与者的守恒重建](../adr/0018-conserved-tagged-queue-reconstruction.md)：owner 已合并 #85；独立命题、inclusive total projection 和单次 trade 分配。
- [ADR 0019：独立的可迁移 tagged 双模型证据](../adr/0019-portable-tagged-pair-evidence.md)：owner 已合并 #86；固定十二角色、只读 core 离线重建和有界配对关系。
- [ADR 0020：冻结独立 finding 权限并封存确定性报告](../adr/0020-frozen-tagged-finding-authority.md)：owner 已合并 #87；受限 finding 映射、独立权限、十四角色内容闭包与 FINAL 边界。

## 搜索计划决策记录

- [ADR 0021：先冻结搜索候选序列与提议记录](../adr/0021-frozen-search-candidate-plans.md)：owner 已合并 #88；独立种子、固定生成算法、原始提议预算及完整 journal。

- [ADR 0022：以原协议预算执行候选并持久关联尝试](../adr/0022-persistent-search-execution.md)：owner 已合并 #89；事前 dispatch nonce、原槽位预算、结果保留、停止与只读重审；搜索 finding 与完整作业恢复仍保留后续门。

- [ADR 0023：以独立合同监督 campaign 总资源预算](../adr/0023-supervised-campaign-resource-budgets.md)：owner 已合并 #90；整份执行阶段 deadline、候选入场容量预留、原预算共用及停止证据保留；计量为受管理 payload，不冒充宿主磁盘或 RAM quota。

- [ADR 0024：独立的有范围搜索结论](../adr/0024-scoped-search-findings.md)：owner 已合并 #91；复制数字 criterion 为新条件命题，从真实来源与原 ledger 只读重审后输出见证、覆盖、预算和不可评价原因，不扩大旧 baseline 权限。

- [ADR 0025：可迁移搜索证据闭包](../adr/0025-portable-search-evidence.md)：S08-01；封存明确缺省、原协议槽位前缀和完整候选CAS，移除原workspace后core-only重建同一报告与trace诊断，FINAL仅为内容闭包。

- [ADR 0026：一次性确认窗口与不可逆暴露记账](../adr/0026-one-shot-confirmation-exposure.md)：S08-02；独立冻结整窗读取政策，按同一数据根的稳定来源交叠持久消费，改名称或协议不恢复未接触状态；不认证宿主保密或全局历史。
