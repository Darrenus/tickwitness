# Sprint 7 固定预算搜索状态

更新：2026-10-27（Asia/Singapore）。Owner 已合并 [PR #87](https://github.com/Darrenus/tickwitness/pull/87)，S06-02 的最小 conditional tagged finding 能力已接受。Sprint 7 基线 merge 为 `2c2e0e39ccb4332afd87f4134d7fa6bf1e5801c6`；`0.2.0.dev0` 保持未发行。真实访谈、采用和独立人类领域复核没有新增证据。

## 本轮切片与后续门

| 故事 | 切片与实际边界 | 状态 |
| --- | --- | --- |
| S07-01 / #19 | S07-01a 冻结网格／随机候选、来源、种子与完整 proposal journal；重建去重／拒绝及 source 派生预检 | [PR #88](https://github.com/Darrenus/tickwitness/pull/88) 远端验收通过，待 owner 接受 |
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

S07-01a 远端结果、代码 head、实际 merge checkout 与 artifact 身份见下节。当前不得宣称自动搜索、完整试验账本、执行预算或 alpha 门已完成。

## S07-01a 远端验收记录

功能代码 head `ad57f6d2c7946a34c618f4436d0d2abd9e5e485f` 的 [Engineering 40483167929](https://github.com/Darrenus/tickwitness/actions/runs/40483167929) 与 [Documentation 40483168061](https://github.com/Darrenus/tickwitness/actions/runs/40483168061) 共13 checks 全部通过；实际 merge checkout 为 `eb8e41b21dfc71051a11c8ddd49fa4eb49fbeba7`，与 PR head 分开。后续文档提交的 CI 不冒充同一代码 head。

核心 Ubuntu 24.04／macOS 15 × Python 3.12／3.13／3.14 六组合各 **2225 passed / 111 optional-native skips**；原生 Ubuntu 24.04 与 macOS 26／Python 3.12 各 **2334 passed / 2 core-only skips / 313 warnings**。Lint、194 文件格式、90 source files 严格类型检查、71 文档／381 本地链接通过；warnings 保留，不作为通过断言。所有测试、构建、格式化、安装和原生回放均在远端，本机只进行编辑、静态审阅、Git／gh 控制与下载报告读取。

| 实际核验 | 结果 |
| --- | --- |
| Grid 完整提议 | 4 次原始提议保持顺序，2 eligible／1 duplicate／1 rejected；duplicate 指向首见，越界保持 null scenario_id，不补抽 |
| Random 与种子 | 固定 SHA256 无偏整数映射与独立编码 oracle 对齐；0、1、2^63−1 三组 seed 的安装后序列保存为固定回归向量；原生 replay seed 不改变 |
| 原始预算与停止 | 较小预算严格为同一 journal 前缀；singleton 越界区间得到 R/D/D/D，eligible=0 仍不被包装成搜索结论；grid_exhausted 仅指列表生成完毕 |
| Source 与派生 | 每次 freeze／inspect 均重验实际 development source 与所有 eligible 派生视图；raw／quality／identity／anchor 不合格或组合规模超限即整体拒绝 |
| 持久化与攻击 | 并发幂等、原子 no-replace、损坏不覆盖；symlink／FIFO／目录／超限拒绝；提交后 fsync 异常保留已提交证据；完整重算 hash 的伪造 journal 仍拒绝 |
| 无执行副作用 | 安装后的 core-only guard 禁止 native import、worker、network 和 attempt ledger 构造；source／原 protocol registry 字节树不变，无 runs 或 attempt |
| 权限与读取 | confirmation 在 ID／请求／factory 前拒绝；缺失根不创建；重复冻结同身份，inspect 只读且完整重新生成 |

安装后验收报告为 `installed_search_plan_acceptance_v1`。功能 run 的 `search-plans-core-eb8e41b21dfc71051a11c8ddd49fa4eb49fbeba7` 与 `search-plans-source-wheel-eb8e41b21dfc71051a11c8ddd49fa4eb49fbeba7` artifacts 保留30天；后者使用实际 tar.gz 内脚本／样例和全新环境中的实际 wheel，不以 checkout 替代。两份报告 accepted=true，全部不变量为 true，candidate plans 与三组随机向量一致。

初轮远端发现新 CLI 在 Python 3.12 运行时求值 argparse 泛型注解而阻断导入；增加延迟注解并应用远端格式补丁后重验，未修改候选或拒绝 oracle 掩盖问题。AI 并行静态复核单独计为 AI 审阅，独立人类领域接受仍未取得。

S07-01a 的提议计划可供 owner 审阅；#19 保持打开，自动评估及 durable attempt／outcome 关联、campaign 硬限额、搜索 finding、确认集 lifecycle 和完整统计试验历史仍由后续切片交付。未新增实际工时、真实访谈、性能或采用数据。
