# S06-02a：观测投影与真假语义资格

日期：2026-10-26。基线：owner 已合并 [PR #83](https://github.com/Darrenus/tickwitness/pull/83)，merge `c78714bb9fca3a3a0ce21d29ae189d9ee0e5cd1d`。本轮使用远端 CPU，未在本机运行测试、构建、格式化、安装或原生回放。

## 结论与依据

目前的 external FIFO shadow queue 适合作模型敏感性研究；它不自动证明把模拟订单放入真实交易世界后仍能投影成同一历史行情。官方文档指出，记录的 book 并不揭示模拟订单会如何改变市场。该文档是当前说明，不据此推定固定 wheel 的行为；实现与资格继续以 `1.231.0` 源码及实际远端原生输出为准。[Nautilus 数据与 venue 语义](https://nautilustrader.io/docs/latest/concepts/backtesting/data-and-venues/)、[固定 FillModel 源码](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/nautilus_trader/backtest/models/fill.pyx)

本轮的两个独立数学检查是项目方从已冻结模型推导的结果：external 全额扣 trade 再另加 own fill，不能同时解释为同一笔 trade 的单次守恒分配；并且标记值不同只有跨过同一冻结比较符／阈值时才有真假分歧。具体公式、反例、空仓与错误语义在 [资格合同](../contracts/queue-semantics-qualification-v1.md) 中列明。它们不是上游提供的市场相容性保证。

还要区分“有限观测路径及明示模型内存在两个重建见证”与统计学上完整可观测分布下的识别问题。Molinari 的原作者综述讨论了数据分布与 maintained assumptions 对观测等价集合的共同约束；本项目当前固定有限路径的资格报告不能扩大为总体统计非识别结论。[Microeconometrics with Partial Identification](https://arxiv.org/abs/2004.11751)

## 远端资格设计

固定原创 synthetic cases 先构造不可变候选 predicate 身份并记录于报告，再持久冻结 source、family 和共同预算，随后每政策占一个 attempt，调用真实 pinned native 引擎，持久保存 intent、result、receipt 与独立 audit，再只读复核。候选对象的构造顺序不是持久时间注册或跨协议统计试验族证明；它只用于语义资格，不评估旧 family 的 source claim。没有任意用户数据的免费 qualifier 执行入口。

案例覆盖原始 −1/0 的 false/false、独立 final bid 102 的 true/false、ge 等号导致 true/true、数值不同但同真值、四比较符空仓边界、无撤单对照、gross churn 和同接收时刻的 capture 顺序。核心负例覆盖来源、环境、scope／proof 标签、预算／持久闭包、错误及未完成结果；候选计算使用 Fraction，不受调用方 Decimal 精度影响。

每份报告分别保存：硬编码 oracle 与实际值、原始观测、完整冻结声明、两个政策的原生与账务 trace、外部投影、单次 trade 分配及 checkpoint 残差、候选 predicate 真值、实际 consumed/remaining attempts、只读复验状态。禁止把自报 `passed=true` 当作 oracle，也不删掉不利检查来满足预期。

`scripts/qualify_queue_semantics.py` 只运行这些固定案例。CI 在 Ubuntu 24.04、macOS 26、实际安装 wheel、以及实际 source archive 内的脚本／样例与新安装 wheel 上重复验收；报告按实际 merge SHA 保存 30 天。测试和代码质量门仍为必需检查。

## 实际远端验收

实现 head `6ffdc4d45e08593af82f25786a3830f1dd16ddbd` 的 [Engineering 40260800327](https://github.com/Darrenus/tickwitness/actions/runs/40260800327) 与 [Documentation 40260800224](https://github.com/Darrenus/tickwitness/actions/runs/40260800224) 共 13 checks 全部通过。实际 merge checkout 为 `6c676acac65dcff9b5df16a73777f82cedb0d567`；本记录随后的文档提交不冒充同一 head。

| 门 | 实际结果 |
| --- | --- |
| 核心矩阵 | Ubuntu 24.04 / macOS 15 × Python 3.12/3.13/3.14，六组合各 1534 passed / 57 optional-native skips |
| 原生矩阵 | Ubuntu 24.04 / macOS 26 × Python 3.12，各 1589 passed / 2 core-only skips / 190 warnings |
| 固定语义资格 | 两平台均 8 cases / 210 checks 全部通过；16 次受监督 worker 调用，每案例共同预算实际 consumed=2、remaining=0 |
| 实际安装 wheel | 两平台再次通过全部 8/210；安装后 CLI 验证配对逆序结果一致、只读文件字节树不变、不再执行 native 或消耗尝试 |
| 实际 sdist 与 wheel | 使用实际源码包内脚本／样例及新安装 wheel 再次通过 8/210，并校验预览发行物 checksum |
| 质量 | lint、138 文件格式、64 source files 类型检查、文档与全部旧回归通过；warnings 保留，不当作通过断言 |

直接复核的实际 oracle：原例值 `−1/0` 对 `gt0` 为 `false/false`；最终 bid102 例为 `+1/0`，对 `gt0` 为 `true/false`，对 `ge0` 为 `true/true`。标准 front 的 public trade3、external consumed3、own filled1 合计4，超分配1；对应 checkpoint recorded external2，指定插单投影需要3，残差1。back 无残差但仍不具有完整相容性证书。报告始终为 `production_finding_enabled=false`、`user_data_valuation_enabled=false`、`finding_issued=false`。

Artifacts 保存 30 天，名称为 `queue-semantics-<os>-6c676acac65dcff9b5df16a73777f82cedb0d567`、`queue-semantics-wheel-<os>-6c676acac65dcff9b5df16a73777f82cedb0d567` 与 `queue-semantics-source-wheel-6c676acac65dcff9b5df16a73777f82cedb0d567`，保留完整 raw/normalized source、family、候选 predicate、实际 budget/intent/receipt/result/audit、投影残差、预期与实际值及检查结果。

初轮的括号错误、测试收集重名、类型错误，以及新增夹具的固定 book 档数／删除 trade 后捕获缺口均保留在 CI 历史。夹具修正为从源计算档数、以合法非 trade 对照保持序列；生产审计没有放宽。独立 AI 静态复核另发现 loader 应累计限制 gross flow，已补同实际 feasibility 一致的上限和回归；loader 的 preimage 边界也已明确。

## 状态

[PR #84](https://github.com/Darrenus/tickwitness/pull/84) 的 S06-02a 实现已完成远端验收，待 owner 接受；S06-02 整条故事仍进行中。生产队列族的观测相容性未建立、source claim 不可评价、findings 为空；后续需单独冻结并验证 queue claim、投影、干预和证据封存合同。实际访谈与独立人类领域复核尚未新增，AI 并行复核单独计为 AI 检查。
