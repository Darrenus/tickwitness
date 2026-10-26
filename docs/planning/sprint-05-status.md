# Sprint 5 场景约束工程状态

更新：2026-10-26（Asia/Singapore）。S04-03 的 PR #78 已获 owner 合并；`0.1.0a1` 发行由[独立发布记录](../releases/0.1.0a1.md)跟踪，本文不把合并、候选 CI 与实际发行视为同一事实。本切片进入 `0.2.0.dev0`，先交付 S05-01 的最小声明/输入约束闭环，后两项执行工作不提前计为完成。

| 故事 | 本切片范围 | 状态与后续门 |
| --- | --- | --- |
| S05-01 / Issue #13 | 不可变 AssumptionSpec / ScenarioSpec、研究者设定的未校准纳秒范围、suffix anchor、真实来源绑定与只读 `validate-scenario` | 实施中，待对应 PR、远端 CI 和 owner 接受；本机未执行本轮测试/基准 |
| S05-02 / Issue #14 | 额外接收延迟压力的实际执行 | 尚未批准执行；需先确定市场/观察/决策时钟、derived-view lineage、新 semantic 与原生/审计资格门 |
| S05-03 / Issue #15 | 基线/干预配对与首次分歧、数值变化说明 | 依赖 S05-02；不能将输入时间戳/hash 不同、incomplete 或不可评价状态当作命题翻转 |

故事范围与容量仍见 [Sprint backlog](sprint-backlog.md#s5--假设约束与首个压力情景)。实际投入时间尚未登记，不把代码生成、自审或 AI 交叉审查计为独立人类领域验收。真实访谈、外部采用和其他开放研究门继续保留原记录，不由本切片补数。

## 本次最小交付边界

- [Assumption / Scenario v1](../contracts/assumption-scenario-v1.md) 将请求与 canonical spec 分开；hash/frozen DTO 保存声明身份，不提供执行权限。
- transform 仅 `replay_receive_suffix_shift_v1`，从实际存在的 capture 起对全部后缀声明增加非负 receive delay；类别仅额外压力。
- 范围依据仅 `researcher_defined` / `uncalibrated`，校准引用为空；60 秒限额属于工程支持，不是物理证据。
- builder/application 从实际 v2 protocol、development dataset、normalized bytes 与 ReplaySpec 注入并核对绑定，执行 source/preflight/anchor/int64 horizon 约束校验。
- CLI 是只读检查；confirmation 在 repository factory 前拒绝；不运行 native、不占 attempt、不写变换行情，也不改变 v2、旧 bundle 或原始证据。
- 成功只返回来源/输入约束已核、未校准与 `execution_approved=false`；引擎兼容性尚未验，不签发收益、claim observation、可行历史世界或搜索 finding。

合同决策先记录于 [ADR-012](../architecture/decisions.md#adr-012-场景声明与延迟压力执行分开验收)，用户命令见[场景校验](../scenarios.md)。

## 待保留的验收证据

| 门 | 需要的实际记录 |
| --- | --- |
| exact schema 与不可变身份 | 严格 JSON/单位/整数/范围/类别/refs 负例；修改范围或来源生成新身份；detached document 不影响原值 |
| 上下文校验 | 实际协议/data/spec hash 匹配；缺失 anchor、隔离输入、时间/horizon 溢出明确拒绝 |
| 只读与权限 | 合法重复请求无仓库写入；missing store/registry 不创建；确认集拒绝先于输入/仓库读取，无 attempt 消费 |
| 干净安装与回归 | 候选 commit 的远端 CI job、安装后 CLI smoke、既有 core/native/evidence 回归结果；配置或脚本存在不算已通过 |
| 人类接受 | owner 对本切片差异的接受记录；AI 审查如实标记，独立领域复核缺口保留 |

截至本状态页初稿，上表是待收集门，不填虚构测试数量、CI 结果或耗时。具体 run/PR 链接在实际发生后补入对应工程记录；不会把 `0.1.0a1` 的旧结果当作 `0.2.0.dev0` 本切片通过。

## 延迟执行与配对风险

当前 receive-order profile 同步推进市场和策略时钟，全流常数平移可能没有经济效果。后缀平移会改变相对时间，但没有独立观察/交易所时钟就不能等同真实 feed delay；不能仅凭 trace 差异宣传压力模型已成立。

后续执行门包含零变换、全流平移经济不变对照、有效非零案例、同刻/命令延迟/EOF/future-cache 与费用审计。干预改变 data/spec/model 后应明确共同条件与允许变化，不伪装成旧比较器的严格同条件运行。无成交、费用歧义或未决命令只说明执行/可评价范围，不能升级为 S6 不可识别或 S7 反例 finding。
