# Sprint 7 固定预算搜索状态

更新：2026-10-27（Asia/Singapore）。Owner 已合并 [PR #87](https://github.com/Darrenus/tickwitness/pull/87)，S06-02 的最小 conditional tagged finding 能力已接受。Sprint 7 基线 merge 为 `2c2e0e39ccb4332afd87f4134d7fa6bf1e5801c6`；`0.2.0.dev0` 保持未发行。真实访谈、采用和独立人类领域复核没有新增证据。

## 本轮切片与后续门

| 故事 | 切片与实际边界 | 状态 |
| --- | --- | --- |
| S07-01 / #19 | S07-01a 冻结网格／随机候选、来源、种子与完整 proposal journal；重建去重／拒绝及 source 派生预检 | 实现中；远端验收待完成 |
| S07-01 / #19 | S07-01b 自动评估、候选与真实 attempt/outcome 关联；原协议预算不重置 | 尚未实现；不以 proposal journal 代替执行账本 |
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

远端结果、代码 head、实际 merge checkout 与 artifact 身份待执行后回填。当前不得宣称自动搜索、完整试验账本、执行预算或 alpha 门已完成。
