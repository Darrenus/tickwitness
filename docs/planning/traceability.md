# TickWitness 需求与验收追踪

状态：滚动维护，2026-11-19 Asia/Singapore。以下是产品目标、领域规则、故事与目标验收证据的映射，不表示整行能力已实现。实际工程状态见各Sprint记录、[已接受SDK与接入状态](sprint-12-status.md)、[执行信任与隔离状态](sprint-13-status.md)及GitHub Issues。规则定义以[领域模型](../architecture/domain-model.md)及[质量策略](../quality/quality-strategy.md)为准。

| 用户目标或质量规则 | 领域责任 | 首批故事 | 发布证据 |
| --- | --- | --- | --- |
| 对研究问题形成统一语言 | 研究契约 / 实验注册 | S01-03、S02-03 | 真实问题记录、命题/协议边界、正反及未知案例 |
| 不伪造接收时点和缺失历史 Q-01/Q-02 | 数据证据 | S02-01、S03-01 | snapshot/delta/缺口/未知时间夹具和拒绝路径 |
| 不覆盖原始证据 Q-08 | 数据证据 / 证据包 | S02-02、S04-02 | 幂等导入、崩溃边界、哈希和完整性验证 |
| L2解释与新增压力分开 Q-03/Q-04 | 研究契约 / 反例搜索 | S05-01、S05-02、S06-01 | 场景类别合法性、同观测解释配对与未知边界 |
| 不把失败当反例或未发现 Q-05/Q-12 | 判定 / 作业 | S06-02、S07-02、S07-03、S10-03 | execution_status / scoped findings / completeness 三字段与负例 |
| 反例可以定位和复验 Q-06 | 回放 / 证据 | S03-02、S05-03、S08-01 | 首次分歧、输入订单账本、独立 verifier receipt |
| 缩减不改变原研究条件 Q-07/Q-11 | 搜索 / 回放 | S09-01、S09-02、S09-03 | [S09状态](sprint-09-status.md)：01a准备与01b原预算回放／terminal投影审计已接受；02有限局部缩减与独立false数值保持判定实现中，cooperative取消不扩大原预算；当前不支持checkpoint |
| 探索和确认有透明账本 Q-09/Q-10 | 实验注册 | S02-03、S07-01、S08-02 | 所有attempt、暴露继承、固定确认窗口和声明范围 |
| 长任务可控和可恢复 | 作业 / coordinator | S10-01、S10-02、S10-03 | 崩溃、重试、fencing、取消与资源限制演练 |
| 数据与策略不越过信任边界 | 导入 / 执行 / 入口；infrastructure与运维边界 | S02-01、S04-02、S13-01–S13-03 | [执行信任合同](../contracts/execution-trust-v1.md)／[ADR0044](../adr/0044-explicit-execution-trust-boundaries.md)、[S13状态](sprint-13-status.md)：M0仅现有已资格内置profile；M1未实现／未资格，M2托管权限边界不支持；T01–T10区分当前控制证据与后续未执行负例，缺证保持关闭 |
| 接入现有工作流 | 应用服务 / CLI / SDK | S04-01、S12-01、S12-02 | [已接受SDK与接入状态](sprint-12-status.md)、[自有案例流程](../user-onboarding.md)及[实际招募缺口](s12-02-recruitment-gap.md)；材料与技术成功不冒充真人激活 |
| SDK兼容与自助接入 | SDK driving adapter / 共享应用服务 / 质量 | S12-03 | [兼容合同](../contracts/sdk-compatibility-v1.md)、具名文档实际安装执行、SDK/CLI未知字段拒绝与开放参数保留、[分层支持矩阵](../support.md)；四档SDK新资格不继承历史绿色 |
| 长期证据可读、更正可追踪 | 证据 / 运维 | S16-02、S18-01–S18-03、S19-02 | 原件保留、迁移、撤回、依赖影响和备份恢复 |
| 自动搜索有可测价值 | 搜索 / 产品验证 | S07-01、S20-01、S21-01 | 同预算基线、未见案例、失败结果和独立复验 |
| 用户愿意再次使用 | 产品验证 | S12-02、S16-01、S21-03、S24-03 | Beta激活门与GA满30天第二研究复用门；[空白记录](../templates/onboarding-case-v1.md)及[示例判定](../templates/onboarding-review-examples.md)不计采用 |
| 能持续维护与发行 | 交付 / 治理 | S19-01–S19-03、S22-01–S24-03 | 许可、SBOM、provenance、RC、支持矩阵和维护政策 |

S13-01三模式及威胁模型已随PR114实际接受。S13-02先实际推送[参考合同](../contracts/restricted-reference-v1.md)／[ADR0045](../adr/0045-restricted-reference-qualification.md)冻结环境／机制／数值，再实现内部控制后端与固定合成负例；宿主事实、实际负例与M1产品启用分别判定，不新增SDK模式开关或研究权限。原S13专项10+16+8=34h和持续质量容量不变；原协议预算及5／8／11槽、golden／PR94不重置或退款。既有安全解析／Job／SDK测试不构成本轮隔离攻击资格；本候选远端检查、owner接受、独立安全复核与外部真人研究复验分别记录。独立安全复核尚未完成，外部真人0／0／PENDING及实际自有案例空登记保持，不能以文档或CI成功计作采用。

## 领域建模如何持续演进

当前S2代码证据：Q-01/Q-02由`tests/domain/test_data_evidence.py`的结构/缺口/未知时间案例覆盖明示的预检范围；Q-08由`tests/infrastructure/test_local_dataset_store.py`的真实CAS/SQLite完整性及故障案例覆盖本地封存范围。[协议合同](../contracts/frozen-protocol-v1.md)对应`tests/domain/test_research_protocols.py`，应用层分区绑定与confirmation拒绝对应`tests/application/test_research.py`和`tests/test_protocol_cli.py`。这些检查不认证完整回放、统计独立或Q-09/Q-10的完整attempt ledger；后者仍未完成。依赖方向由`tests/architecture/test_domain_boundaries.py`约束，安装制品链路由`scripts/smoke_distribution.py`在独立环境验证。

S1–S2 通过问题访谈和轻量 EventStorming 建立命令、事件、参与者、外部系统和热点清单。没有领域专家参与的部分标为假设，不把 AI 同意视为领域共识。每个关键规则使用 Example Mapping 写出规则、具体例子和未决问题；未决问题阻塞对应 story ready，不阻塞独立可行性试验。

每两个 Sprint 核对术语、context map 和代码依赖；新需求先归属上下文，再讨论类与表。跨域耦合或一个聚合修改多个上下文状态时，先检查模型，再决定是否需要 process manager/outbox。业务规则改变通过 ADR/RFC 和语义版本传播到契约、测试及历史证据处理。

任何发布声明必须能从此表追踪到具体 story、PR、检查和运行制品。规划期只允许显示“已规划”；只有实际完成并验收后才能转为“已实现/已验证”。
