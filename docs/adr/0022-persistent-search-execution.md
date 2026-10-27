# ADR 0022：以原协议预算执行候选并持久关联尝试

- 状态：Proposed；S07-01b 实现，远端验收及 owner 审阅待完成。
- 日期：2026-10-27。
- 基线：owner 已合并 [PR #88](https://github.com/Darrenus/tickwitness/pull/88)，merge `373d08a5c2196662c5116e02ea7b7fe3a98dc167`。
- 合同：[Search Execution v1](../contracts/search-execution-v1.md)。

## 问题

冻结候选序列并不等于尝试已经发生。自动执行需要把每个 proposal 与真实 reservation、intent、原始结果和 committed outcome 联系起来；否则协调器在 reserve 后崩溃，可能失去候选身份，或者把已占槽但尚未返回的调用误报为零成本。新建 plan 也不能重新取得已经被 baseline 或其它候选消费的预算。

## 决策

先实现固定顺序的单机协调器，一次只执行一个 eligible 候选，所有调用继续由原 `ExecutableProtocol v2` 拥有预算。旧 reservation、ScenarioIntent、receipt、failure 与 scope 不改写。Campaign 只提供外层计划与执行关联；重复及范围拒绝仍由原 journal 完整披露。

同 plan／同 runs 根只允许一个 campaign，用非阻塞 POSIX 排他锁避免并发协调器。每个候选先提交 dispatch 和 reservation nonce，再用该 nonce 在原 slot namespace 中 reserve，持久 reservation link、既有 scenario intent 后才构造引擎。Named nonce 复用明确拒绝，不能返回旧 slot 使第二次执行免费。普通 baseline、其它 plan 和新 API 仍争用相同预算槽。

预先承诺 nonce 是恢复关联的依据。Reserve 在 slot link 后 fsync 失败时，即使没有返回 reservation，inspect 仍可按 nonce 在已提交前缀中找回实际 attempt。无法确认时停止并保留未知，不退款或自动续跑；多个匹配则拒绝完整性。引擎返回后先保存原始 result，再交给既有 independent audit，使审计失败不丢弃已经取得的诊断证据。

## 停止与检查

首个失败、不完整、预算耗尽或写入不确定即停止，后续 eligible 候选仍明确未执行。进程中断不保证能写终止记录，inspect 从实际 reservation、intent 和 outcome 重建未决事实，不补写成功。Outcome 可能已提交而返回路径报错；保持原诊断并重审真实内容，不能盲目第二次调用。

重复 run 仅检查已有 campaign，不自动恢复。Readonly inspect 重建实际 source、plan、候选与旧 ScenarioIntent，核对 reservation／slot／nonce／committed outcome，成功结果复用独立场景账务审计。它不需要 native extra，不构造 worker、不消耗预算或修改文件。

## 代价与后续门

这是透明的自动评估和执行关联，不是完整统计 trial-family 历史或预注册认证；已有 scenario scope 不因外层搜索而扩大。有限计划执行完毕不产生 finding，也不证明连续空间穷尽或真实市场稳健。Campaign 总时间／存储预算仍由 S07-02、搜索 finding 由 S07-03、确认集 lifecycle 由 S08、完整恢复／取消由 S10 分别交付。

受信任的 runs 根保留固定 POSIX namespace、bounded regular-file／no-follow 读写、原子 no-replace 与 fsync。这个模式不提供多租户隔离、host owner 对抗或作者认证；原数据／protocol／plan／ledger 闭包仍是检查前提。独立人类领域复核、真实访谈、采用和性能指标未增加时不填造。

## 验收

远端验收覆盖 baseline 先占槽、两候选执行占余下槽、其它 plan 预算耗尽、失败／中断不退款、reserve 提交后异常的 nonce 关联、原始结果保留、重复 run 不重放、同 plan 并发互斥、只读检查及 source／link／outcome 篡改。实际 wheel 和实际 source archive 安装流程分别验证 native 执行及 core-only 复核；未取得的结果不记为通过。
