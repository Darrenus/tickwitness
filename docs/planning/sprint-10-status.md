# Sprint 10 作业恢复与取消状态

更新：2026-11-06（Asia/Singapore）。Owner 已合并 [PR #100](https://github.com/Darrenus/tickwitness/pull/100)，接受 S09-03，merge `6e5d48db480e2e7f471c3f743c4d97eb18be88ee`；S09-01／02／03 软件均已接受。外部真人复验仍 **0 / PENDING**，[#24](https://github.com/Darrenus/tickwitness/issues/24) 保持打开。原 PR94 转交包与 golden 不变，无新 release。

| 故事 | 当前范围 | 验收状态 |
| --- | --- | --- |
| S10-01 / #28 | 持久 Job 状态机、独立 attempt、心跳、单 coordinator、真实只读 comparison worker、失败／失联诊断 | 实现审阅中，实际远端检查与制品记录在实现 PR；待 owner 接受 |
| S10-02 / #29 | 幂等重试、最终研究 manifest 发布、按能力从冻结输入重跑／完整 checkpoint、原生执行接入与 fencing 验收 | Planned，单独验收 |
| S10-03 / #30 | 强取消、总 deadline／资源上限、临时目录回收 | Planned，单独验收 |

原专项估算 **12h／14h／8h** 与每 Sprint 持续质量容量不变，不补造实际工时，也不扩大本故事到分布式队列。

## S10-01 纵向边界

[Job lifecycle v1](../contracts/job-lifecycle-v1.md) 与 [ADR 0032](../adr/0032-durable-local-comparison-jobs.md) 冻结单机单 worker 模式。首个 operation 为真实 `compare_reduction_run_v1`，不是模拟耗时任务。Job attempt 与原研究 attempt 分开：在原协议 11 槽耗尽后仍能读取证据，但不能 reserve／publish／native replay 或返还额度。

Worker 只接收有界 JSONL 请求与心跳／结果 IPC，不获得 Catalog 路径或可写连接。Coordinator 独占 POSIX lock 和 SQLite 写入；短事务检查版本与当前租约，把结果 BLOB、终态和事件一起提交。退出码 0 与正确自报 hash 都不足以成功，coordinator 必须重新读取原 source／live ledger 并独立复验。NE／null 是合法研究观察，可以对应成功执行的 Job。

真实 worker 死亡由存活 coordinator 诊断；coordinator 死亡后，readonly inspect 展示 COORDINATOR_LOST／LEASE_EXPIRED／CLOCK_UNCERTAIN 等有效状态，显式新 owner 才把旧 incarnation 的 RUNNING 写成 LOST。没有 retry、resume、退款或确认域访问。迟到、乱序、错 token／attempt 与终态改写均拒绝。心跳只证明消息存活，不证明研究进度；Catalog 仍是可信 owner 的本地存储，不认证完整历史或 hostile-code 隔离。

## 验证与交付记录

全部项目代码、测试、格式、类型、构建、安装与运行仅在远端 CPU。实际 CI 检查状态和 `jobs-core`、`jobs-ubuntu-24.04`、`jobs-macos-26`、`jobs-source-wheel` 产物链接在实现 PR 回填；未完成的检查不计通过。制品保存实际命令、独立结果复验、Catalog／events／hash 闭包，以及真实 worker／coordinator 死亡诊断。只读 core refusal 不能冒充正例原生见证。

S10-01 只验收首个受支持的 managed operation 与作业生命期。研究重试／manifest、完整引擎状态、强取消、总资源限额与 release 没有因此提前完成。CI、AI 和 owner 合并均不计外部真人复验，也不记录实际市场采用或研究收益。
