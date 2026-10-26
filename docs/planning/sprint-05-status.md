# Sprint 5 场景约束工程状态

更新：2026-10-26（Asia/Singapore）。S04-03 的 PR #78 已获 owner 合并；`0.1.0a1` 发行由[独立发布记录](../releases/0.1.0a1.md)跟踪。`0.2.0.dev0` 的 S05-01 在 PR #79 待 owner 合并；后续 PR #80 先通过固定时钟资格，再接入 S05-02 耦合时钟压力执行。本页区分实现、远端验证及人类接受。

| 故事 | 本切片范围 | 状态与后续门 |
| --- | --- | --- |
| S05-01 / Issue #13 | 不可变 AssumptionSpec / ScenarioSpec、研究者设定的未校准纳秒范围、suffix anchor、真实来源绑定与只读 `validate-scenario` | PR #79 远端检查通过，待 owner 合并 |
| S05-02 / Issue #14 | 耦合 receive-clock 后缀压力执行、独立派生身份、持久intent、共享预算及复核 | PR #80 两阶段远端验收通过，待 owner 合并；未发行 |
| S05-03 / Issue #15 | 已提交基线/干预关联重验、精确数值差、raw/业务投影各通道首次分歧 | 后续独立 PR 实施中，远端验收待记录；不能将元数据差异或不可评价状态当作失效 |

故事范围与容量仍见 [Sprint backlog](sprint-backlog.md#s5--假设约束与首个压力情景)。实际投入时间尚未登记，不把代码生成、自审或 AI 交叉审查计为独立人类领域验收。真实访谈、外部采用和其他开放研究门继续保留原记录，不由本切片补数。

## S05-01 声明校验边界

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

上表定义所需门；实际发生的证据追加于下节，不把旧版通过结果替代当前版本，也不虚构投入工时或独立人类验收。

## S05-02 两阶段执行记录

[PR #80](https://github.com/Darrenus/tickwitness/pull/80) 以仍待合并的 PR #79 为 base。Phase A head 为 `c1edcf5d772cae78702e33cd2c1d62d2b8622d14`；[Engineering 40220550602](https://github.com/Darrenus/tickwitness/actions/runs/40220550602) 实际测试 merge checkout `2b78eb75d843f9128bf91ce72868f4bc4a784a10`，两者不混记。13 项检查通过，原生两平台各 959 passed / 1 skipped；固定时钟脚本每平台 9 cases / 154 checks 全部通过。报告 artifact 名称为 `scenario-clocks-<os>-<merge checkout>`，包含原始 native traces、精确 spec、环境与 audit。

零延迟/全流平移维持业务投影；1.5 秒撤单延迟、capture 4 起 suffix 加 2 秒的原创合成案例使成交 2 手变 1 手、手续费 2 USD 变 1 USD，两边均完整可评价（net marked PnL -2 / -1 USD）。同刻撤单反证确认：到期命令在真实输入步骤后结算，不能假定在行情间独立生效。这些是模型资格，未校准真实市场，也不判原 baseline claim 的反例。

Phase B 仅在读取上述实际报告后接入执行：原协议 reserve、engine 前持久intent/CAS、派生 view 身份、独立 scenario receipt/evaluation、`inspect-scenario-run` 重派生和账务审计。旧 baseline receipt/bundle 拒绝压力结果。场景 portable bundle 与通用配对/首次分歧仍不计完成。本机未运行测试、构建、回放或基准。

S05-02 上述范围为当时验收边界；S05-03 随后单独实现 `compare-scenario-runs`，使用同一原协议下两个已提交 outcome，只读重验来源与账务，不再运行策略或占 attempt。[报告合同](../contracts/scenario-comparison-v1.md) 将 raw metadata 差异与业务投影区分，给确定性每通道位置；不声称全局因果最早，不输出 baseline claim truth。实现中的测试文件不算已通过，S05-03 实际 CI 证据在对应 PR 验证后补入；前置 PR #79/#80 尚待 owner 合并。

Phase B head `101a3dc06932d1ef0f4736b0ad7fbedad64dd7f6` 的 [Engineering 40221168032](https://github.com/Darrenus/tickwitness/actions/runs/40221168032) 与 [Documentation 40221168033](https://github.com/Darrenus/tickwitness/actions/runs/40221168033) 全部通过；实际 merge checkout 为 `c751bc9a64fce85934d6fddebf88787d1474b36e`。核心六组合各 1038 passed / 27 optional-native skips；原生 Ubuntu 24.04、macOS 26 / Python 3.12 各 1063 passed / 2 core-only skips。106 个 warning 来自既有原生撮合路径，未将 warning 当通过断言。

两平台实际 wheel 安装后均跑完整 CLI：独立基线、零干预、2 秒 suffix 压力分别输出 -2 / -2 / -1 USD；场景 inspect 重派生/账务核验成功且 `native_replayed=false`；三次共用预算，第四次被拒；原数据 unchanged、旧 baseline bundle 拒绝场景回执。各平台报告 artifact 为 `scenario-execution-<os>-c751bc9a64fce85934d6fddebf88787d1474b36e`。预览制品 job 另从实际 sdist 取脚本和样例，在新环境安装实际 wheel，核心及原生场景 smoke 通过；制品为未发布开发构建。

## 延迟执行与配对风险

当前 receive-order profile 同步推进市场和策略时钟，全流常数平移可能没有经济效果。后缀平移会改变相对时间，但没有独立观察/交易所时钟就不能等同真实 feed delay；不能仅凭 trace 差异宣传压力模型已成立。

后续执行门包含零变换、全流平移经济不变对照、有效非零案例、同刻/命令延迟/EOF/future-cache 与费用审计。干预改变 data/spec/model 后应明确共同条件与允许变化，不伪装成旧比较器的严格同条件运行。无成交、费用歧义或未决命令只说明执行/可评价范围，不能升级为 S6 不可识别或 S7 反例 finding。
