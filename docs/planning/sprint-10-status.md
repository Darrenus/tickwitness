# Sprint 10 作业恢复与取消状态

更新：2026-11-07（Asia/Singapore）。Owner 已合并 [PR #102](https://github.com/Darrenus/tickwitness/pull/102)，接受 S10-02a，merge `4822d60855be17e09590b5a77ab5c09a96868233`；S09-01／02／03、S10-01 与 S10-02a 软件均已接受。#29 仍未整项完成。外部真人复验仍 **0 / PENDING**，[#24](https://github.com/Darrenus/tickwitness/issues/24) 保持打开。原 PR94 转交包与 golden 不变，无新 release。

| 故事 | 当前范围 | 验收状态 |
| --- | --- | --- |
| S10-01 / #28 | 持久 Job 状态机、独立 attempt、心跳、单 coordinator、真实只读 comparison worker、失败／失联诊断 | Owner 合并 #101 接受；#28 关闭 |
| S10-02a / #29 | 按原研究 attempt 只读复验恢复事实与既有最终 manifest，区分未绑定／未完成／失败／已提交结果 | Owner 合并 #102 接受；#29 保持打开 |
| S10-02b / #29 | 确定性持久 dispatch／原槽绑定、受管原生执行、coordinator 研究发布 fencing、原 receipt 作为 Job 结果 | 实现审阅中；远端实际证据在实现 PR，待 owner 接受 |
| S10-02c / #29 | 显式幂等 retry、研究提交后 Job acknowledgment 恢复；无完整 checkpoint 时从冻结原点占新槽重跑 | Planned；#29 未整项 Done，原总估算不变 |
| S10-03 / #30 | 强取消、总 deadline／资源上限、临时目录回收 | Planned，单独验收 |

原专项估算 **12h／14h／8h** 与每 Sprint 持续质量容量不变，不补造实际工时，也不扩大本故事到分布式队列。

## S10-01 纵向边界

[Job lifecycle v1](../contracts/job-lifecycle-v1.md) 与 [ADR 0032](../adr/0032-durable-local-comparison-jobs.md) 冻结单机单 worker 模式。首个 operation 为真实 `compare_reduction_run_v1`，不是模拟耗时任务。Job attempt 与原研究 attempt 分开：在原协议 11 槽耗尽后仍能读取证据，但不能 reserve／publish／native replay 或返还额度。

Worker 只接收有界 JSONL 请求与心跳／结果 IPC，不获得 Catalog 路径或可写连接。Coordinator 独占 POSIX lock 和 SQLite 写入；短事务检查版本与当前租约，把结果 BLOB、终态和事件一起提交。退出码 0 与正确自报 hash 都不足以成功，coordinator 必须重新读取原 source／live ledger 并独立复验。NE／null 是合法研究观察，可以对应成功执行的 Job。

真实 worker 死亡由存活 coordinator 诊断；coordinator 死亡后，readonly inspect 展示 COORDINATOR_LOST／LEASE_EXPIRED／CLOCK_UNCERTAIN 等有效状态，显式新 owner 才把旧 incarnation 的 RUNNING 写成 LOST。没有 retry、resume、退款或确认域访问。迟到、乱序、错 token／attempt 与终态改写均拒绝。心跳只证明消息存活，不证明研究进度；Catalog 仍是可信 owner 的本地存储，不认证完整历史或 hostile-code 隔离。

## S10-02a 恢复边界

[Recovery v1](../contracts/reduction-attempt-recovery-v1.md) 与 [ADR 0033](../adr/0033-read-only-reduction-recovery.md) 先冻结恢复判定。Producer 报错不代表 outcome 未提交；新接口按原 attempt 与冻结 source／preparation pins 复验原账本，返回已提交的最终 receipt，不新建 attempt、不运行原生引擎、不修复 Job。未绑定记录不能冒充 preparation 已获授权，未观察到 outcome 不能冒充封存的全局缺失。

当前引擎没有完整 checkpoint 能力，仅允许在原协议新槽下从冻结原点执行。研究 outcome 与 Catalog 是两个存储，没有跨库原子事务保证。拆分不增加原 14h 专项总估算，不把未实现部分记 Done。

## S10-02b 受管原生执行边界

[Native Jobs v1](../contracts/native-reduction-jobs-v1.md) 与 [ADR0034](../adr/0034-coordinator-owned-native-jobs.md) 扩展真实执行。Job descriptor 先持久化，版本化 nonce 从 Job ID 派生并进入原账本 reservation。Coordinator 校验原 source／preparation／prefix，先占原槽、写 intent 与四份 preparation CAS，再派发无路径 DTO；worker 直接运行 built-in adapter，只返回原始 ReplayResult，没有 Catalog／ledger 写能力。重复 nonce 不授权再执行，terminal Job 不重启。

原 native wall deadline 与可续 Job lease 分开；心跳不延长原预算。Coordinator 和 worker 自身默认 OS alarm 分别约束同一绝对执行期限，避免脱离父进程的原生孙进程。发布前重读输入与原账本、重算 audit／receipt，并检查当前 owner／版本／凭据／租约；SQLite 等待后再次检查所有权和时钟。实际研究 receipt 提交确认后才写 Catalog 结果；确认丢失不会覆盖 outcome 或退款。

只读 `inspect-reduction-job` 复原 nonce→实际原 attempt→恢复报告的关联。原研究结果已提交而 Job 未确认时保持可诊断，本切片不自动恢复 acknowledgment。显式 retry／Job acknowledgment 恢复仍是 S10-02c，强取消／总资源与完整 orphan 回收仍是 S10-03。

新 installed qualification 在执行前冻结独立合成八槽协议：原 source 三槽、两个结果、worker／coordinator 实际故障、过期发布。旧五槽、十一槽、golden 不改，无第九槽或 portable 额度恢复；四档 `native-jobs-*` 保存真实命令、PID／IPC／Catalog／原账本闭包，实际通过状态以实现 PR 为准。

## 验证与交付记录

全部项目代码、测试、格式、类型、构建、安装与运行仅在远端 CPU。实际 CI 检查状态和 `jobs-core`、`jobs-ubuntu-24.04`、`jobs-macos-26`、`jobs-source-wheel` 产物链接在实现 PR 回填；未完成的检查不计通过。制品保存实际命令、独立结果复验、Catalog／events／hash 闭包，以及真实 worker／coordinator 死亡诊断。只读 core refusal 不能冒充正例原生见证。

S10-01 的 [Engineering 42077246248](https://github.com/Darrenus/tickwitness/actions/runs/42077246248)／[Documentation 42077246306](https://github.com/Darrenus/tickwitness/actions/runs/42077246306) 13/13 通过，四份 Job 制品审计通过；该历史资格不替代 S10-02a 的新检查。S10-01 只验收首个受支持的 managed operation 与作业生命期。S10-02a 只验收只读恢复事实；研究重试／Job manifest acknowledgment、完整引擎状态、强取消、总资源限额与 release 没有提前完成。CI、AI 和 owner 合并均不计外部真人复验，也不记录实际市场采用或研究收益。

S10-02a 的 [Engineering 42233843538](https://github.com/Darrenus/tickwitness/actions/runs/42233843538)／[Documentation 42233843587](https://github.com/Darrenus/tickwitness/actions/runs/42233843587) 13/13 通过，六 core 各3744／112skip、两 native 各3853／3skip；四份本轮制品完整静态审计通过。原生正例仅资格化 committed_result 与真实提交后的受控 ACK 异常；其余恢复状态是单元 fixture，未冒充受管重试或 Job acknowledgment 恢复。S10-02b 的新资格独立执行，不复用历史绿勾充当当前实现通过。
