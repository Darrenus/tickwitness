# ADR 0021：先冻结搜索候选序列与提议记录

- 状态：Accepted；S07-01a 通过[远端验收](../planning/sprint-07-status.md#s07-01a-远端验收记录)，owner 已合并 [PR #88](https://github.com/Darrenus/tickwitness/pull/88)。
- 日期：2026-10-27。
- 基线：owner 已合并 [PR #87](https://github.com/Darrenus/tickwitness/pull/87)，merge `2c2e0e39ccb4332afd87f4134d7fa6bf1e5801c6`。
- 合同：[Search Plan v1](../contracts/search-plan-v1.md)。

## 问题

已有受控延迟场景和两政策 tagged finding 能力，并不等于搜索器已获执行与判断权限。自动生成候选需要固定算法、来源、顺序、去重和提议预算，才能把后续运行关联到事前可复核的计划。若将生成候选的 seed、容量和执行 seed／attempt 混用，可能悄悄改变模型或重置预算。

## 决策

先交付独立 `SearchPlan` 与 `search-plans` 存储，只支持已资格化的固定 anchor、一维 additional-delay COUNTERFACTUAL_STRESS。Grid 保留显式原顺序；random 使用版本化 SHA-256 counter 与无偏整数拒绝采样，独立 `search_seed` 不修改 `ReplaySpec.seed`。原始提议预算包含重复和范围拒绝，不为凑足有效样本重抽；每个条目保留最早重复引用和拒绝原因。

领域计划嵌入原协议与 assumption、严格重建 journal 和 immutable identity，但不自行声称源数据已复验。应用 freeze 和 inspect 均从真实 development 闭包重新构造合同并派生所有 eligible 唯一候选，再发布或报告成功。派生预检按源事件数乘候选数设组合规模限额，超额整体拒绝而非隐藏裁剪；内部多轮 preflight 不计作实际总处理次数或 CPU 硬预算。

采用单独不可变 namespace 与 no-follow／有界读取／原子 no-replace／fsync。重复发布重验已有内容；损坏对象保留并拒绝，缺失根只读访问不创建。全量 hash 重写不能替代确定性重建与实际来源检查。

## 代价与边界

这个增量可准备并复核后续搜索输入，尚不运行 native、不占 attempt、不评判研究命题。它不是完整统计 trial-family 账本或可迁移 source evidence。S07-01b 接入自动评估及 attempt/outcome 关联，仍消费原 ExecutableProtocol 的共同预算；S07-02 控制执行时间和存储，S07-03 定义搜索结论。旧 scenario receipt 的 `search_performed=false` 和 S06 tagged 权限不改写。

接受范围仅为固定受限变换。随机样本不解释为市场概率，重复未去尽或提议预算结束不表示全空间穷举，也不保证单调延迟阈值、历史网络还原或统计防过拟合。用户访谈、实际采用和独立人类领域复核缺口继续保留。

## 验收

远端六个 core 平台／Python 组合核对固定随机黄金序列、前缀稳定、重复与范围拒绝、strict schema 和完整重算攻击。应用验证先拒确认集、真实 source closure、derived 工作量限制、无执行和写入口排序。安装后的 core wheel 与实际 source archive 内脚本完成同身份重复冻结、只读 inspect、坏证据不覆盖、原 source／registry 不变和 worker／network／attempt 禁用检查。未取得的结果不记为通过。
