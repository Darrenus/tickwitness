# ADR 0019：独立的可迁移 tagged 双模型证据

- 状态：Accepted；owner 已合并 PR #86，S06-02c 远端验收记录见 [Sprint 6](../planning/sprint-06-status.md#s06-02c-远端验收记录)。
- 日期：2026-10-26。
- 基线：owner 已合并 PR #85，merge `dcf38714b5ee306e9328f1ad25624fc687f036e8`。
- 合同：[Tagged Pair Evidence v1](../contracts/tagged-pair-evidence-v1.md)。

## 问题

S06-02b 可以冻结并持久执行两种守恒 tagged reconstruction，重审仍依赖原 data／registry／ledger。单份 run 的 verified、配对真值或一组内容 hash 不能替代可移交的来源闭包。旧 baseline bundle 只有八个固定角色，语义不包含双模型共同条件、两份 reservation 或新队列／horizon 审计。

## 决策

新增严格独立的十二角色 `tagged_queue_pair_evidence_bundle_v1`。一个完整 tagged protocol、development manifest／raw／normalized／report、两侧实际 result／evaluation／receipt 以及确定性 assessment 共同封存。source v2、gross 声明、完整 intent 和 reservation 已嵌入这些受限合同，不引入任意路径列表、执行脚本、动态插件或 archive 解析。

IO 复用已验证的固定树、CAS、no-follow、安全预算、fsync 与原子 no-replace 原则，旧八角色 marker／loader 继续严格。application 导出前重新核对原 committed ledger 和实际 accepted development 来源，再独立审计两侧；没有 worker、额外 attempt 或预算退款。反序传入 run 仍按 policy 规范排序，固定字节跨目录保持同一 bundle ID。

离线 verifier 在 core 中从 raw 重建质量报告、输入和两侧可行性，再重算真实回调的分配、费用、账户、生命周期、horizon／cleanup 与命题评价；完整绑定、两次独立 reservation 和封存 assessment 必须复现。不可只信任 supplied evaluation 或其 verified 布尔值，完整重算 hash 也不能隐藏业务矛盾。

实际环境不同则配对 ineligible，费用歧义保留 null；无成交完整终止沿用冻结 flat-zero。未知、模型错误和执行缺证不能变成 false。冻结 finding 权限仍为 false；可移交真假关系不自动成为最终研究 finding。

## DDD 与信任边界

领域逻辑消费不可变 role 字节并复算语义；application 负责实际 store／registry／ledger 到 portable artifact 的闭包；infrastructure 只保证安全有界目录发布／读取；CLI 先拒 confirmation，再选择既有用例。离线不依赖 native、数据库、原本路径、worker 或网络。

导出者能读取两份真实 committed outcome，但离线验证者看不到原 ledger。portable 回执因此固定 `ledger_commitment_checked=false`、`full_attempt_ledger_checked=false`；hash 或自算 bundle ID 不认证作者。提供可信外部 ID 的调用者可使用 expected bundle pin，仍不扩大物理市场或统计推断承诺。

## 后果与验收

一次目录移交即可让 core 安装者在删除原 store 后复核两份 witness；代价是独立版本和固定预算，不通过放宽旧合同兼容。发布后 parent fsync 未确认持久性时保留完整目录并报告未知，不覆盖重试。

验收要求包括：严格十二角色／全部边界攻击；实际 native export 后迁移并删除原状态；只有已安装 core、拦截 native／SQLite／network／worker／store 初始化的环境仍能验证；T/F、F/F、T/T 的预设 oracle；外层完全重算 hash 的语义攻击仍失败；两种 bundle 类型互拒；实际 wheel／sdist 脚本闭环。所有测试、构建、格式化和 native 执行在远端；未运行的门不记为通过。

下一步仍需独立确定 finding 授权与报告合同、确认集 lifecycle、完整试验历史和外部复验。没有独立人类领域接受时继续如实披露。
