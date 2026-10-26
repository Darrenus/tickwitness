# ADR 0016：队列执行使用独立族与共同预算

- 状态：Proposed；S06-01b 完整远端验证通过，待 owner 审阅接受。
- 日期：2026-10-26。
- 承接：[队列约束合同](../contracts/queue-constraints-v1.md)、[Queue Family v1](../contracts/queue-family-v1.md)。

## 问题

固定原生资格与只读约束不能授权用户数据上的任意重复执行。旧 v2 固定旧 replay semantic；为前后撤单模型各克隆一个 v2 会隐藏实际研究次数并获得两份预算。用旧金融审计器接受新 engine 名字也会扩大旧保证。

## 决策

使用独立 `queue_family_protocol_v1`，将完整源协议、实际输入指纹、完整约束、两政策、取消时点、engine/adapter semantic、scope 和共同预算一起 canonical 冻结。族身份拥有共享 attempt 槽，source v2 是配置和来源。每个原生调用先 reserve 并持久绑定独立 kind 的不可替换 intent；失败和中断不退款。两次调用逐次提交，显式报告部分成功，失败后停止。末槽竞争由原 ledger 的无覆盖原语处理。

生产 adapter 从资格组合迁移为产品模块，使用真实输入、真实接受深度和真实原生成交/账户。每 capture 的公开 hook 共用一个额度账本。独立 evaluator 从源约束和实际结果复核队列、授予、订单回执、原生费用和 margin 账户，不复用执行层状态。只读 inspect 重算所有来源和持久闭包，不重复调用 native。新类型与旧协议、结果、审计、bundle、比较器隔离。

## 代价与限制

初版限定单流 EUR-USD、零 insert/cancel latency、首 capture 接受及最终目标 checkpoint 撤单，最多 1000 输入。它支持参数与满足合同的用户输入，不只支持固定 fixture；仍然属于 `MODEL_SENSITIVITY`。gross 流量未校准、无冲击相容性未证明；不产生估值或真假 finding。此处的共同预算不是跨族统计试验追踪，也没有补齐尚未实现的多重检验校正。

真实延迟、更多策略、跨进程/远端存储、模型兼容性证明和 S06-02 判定需各自版本化接受，不能通过放宽本合同静默开启。
