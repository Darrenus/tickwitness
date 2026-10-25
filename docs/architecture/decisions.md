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
