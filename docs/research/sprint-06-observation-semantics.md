# S06-02a：观测投影与真假语义资格

日期：2026-10-26。基线：owner 已合并 [PR #83](https://github.com/Darrenus/tickwitness/pull/83)，merge `c78714bb9fca3a3a0ce21d29ae189d9ee0e5cd1d`。本轮使用远端 CPU，未在本机运行测试、构建、格式化、安装或原生回放。

## 结论与依据

目前的 external FIFO shadow queue 适合作模型敏感性研究；它不自动证明把模拟订单放入真实交易世界后仍能投影成同一历史行情。官方文档指出，记录的 book 并不揭示模拟订单会如何改变市场。该文档是当前说明，不据此推定固定 wheel 的行为；实现与资格继续以 `1.231.0` 源码及实际远端原生输出为准。[Nautilus 数据与 venue 语义](https://nautilustrader.io/docs/latest/concepts/backtesting/data-and-venues/)、[固定 FillModel 源码](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/nautilus_trader/backtest/models/fill.pyx)

本轮的两个独立数学检查是项目方从已冻结模型推导的结果：external 全额扣 trade 再另加 own fill，不能同时解释为同一笔 trade 的单次守恒分配；并且标记值不同只有跨过同一冻结比较符／阈值时才有真假分歧。具体公式、反例、空仓与错误语义在 [资格合同](../contracts/queue-semantics-qualification-v1.md) 中列明。它们不是上游提供的市场相容性保证。

还要区分“有限观测路径及明示模型内存在两个重建见证”与统计学上完整可观测分布下的识别问题。Molinari 的原作者综述讨论了数据分布与 maintained assumptions 对观测等价集合的共同约束；本项目当前固定有限路径的资格报告不能扩大为总体统计非识别结论。[Microeconometrics with Partial Identification](https://arxiv.org/abs/2004.11751)

## 远端资格设计

固定原创 synthetic cases 先封存 source、family、共同预算和候选 predicate，随后每政策占一个 attempt，调用真实 pinned native 引擎，持久保存 intent、result、receipt 与独立 audit，再只读复核。候选谓词只用于语义资格，不评估旧 family 的 source claim。没有任意用户数据的免费 qualifier 执行入口。

案例覆盖原始 −1/0 的 false/false、独立 final bid 102 的 true/false、ge 等号导致 true/true、数值不同但同真值、四比较符空仓边界、无撤单对照、gross churn 和同接收时刻的 capture 顺序。核心负例覆盖来源、环境、scope／proof 标签、预算／持久闭包、错误及未完成结果；候选计算使用 Fraction，不受调用方 Decimal 精度影响。

每份报告分别保存：硬编码 oracle 与实际值、原始观测、完整冻结声明、两个政策的原生与账务 trace、外部投影、单次 trade 分配及 checkpoint 残差、候选 predicate 真值、实际 consumed/remaining attempts、只读复验状态。禁止把自报 `passed=true` 当作 oracle，也不删掉不利检查来满足预期。

`scripts/qualify_queue_semantics.py` 只运行这些固定案例。CI 在 Ubuntu 24.04、macOS 26、实际安装 wheel、以及实际 source archive 内的脚本／样例与新安装 wheel 上重复验收；报告按实际 merge SHA 保存 30 天。测试和代码质量门仍为必需检查。

## 状态

远端结果待实际完成后登记；未完成时不宣称通过。S06-02 整条故事仍进行中。生产队列族的观测相容性未建立、source claim 不可评价、findings 为空；后续需单独冻结并验证 queue claim、投影、干预和证据封存合同。实际访谈与独立人类领域复核尚未新增，AI 并行复核单独计为 AI 检查。
