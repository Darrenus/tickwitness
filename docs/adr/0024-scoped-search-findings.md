# ADR 0024：为预算内搜索冻结独立条件结论权限

- 状态：Accepted；S07-03 [远端验收已通过](../planning/sprint-07-status.md#s07-03-远端验收记录)，owner 已合并 [PR #91](https://github.com/Darrenus/tickwitness/pull/91)。
- 日期：2026-10-27。
- 基线：owner 已合并 [PR #90](https://github.com/Darrenus/tickwitness/pull/90)，merge `935282c415d167bdcc8485569e47e5221e95b4c3`。
- 合同：[Search Findings v1](../contracts/search-findings-v1.md)。

## 问题

Scenario evaluation 已给出重新审计的指标，但原权限刻意不评价 baseline claim。自动遍历和资源预算本身也不能决定什么算反例、未发现或无法评价。直接把正常退出叫“未发现”，会把零覆盖、未知费用估值、执行失败或未决槽位变成假结论；只检查 stop reason 同样会遗漏候选内部中断。

## 决策

为完整 SearchPlan 冻结独立 `SearchFindingProtocol`，复制原 claim 的数字 criterion，构成新的未校准条件 stress 谓词和独立 predicate identity。报告权限不改变旧执行对象或 finding scope，不增设选取更有利阈值的入口。它不宣称 baseline 翻转、原命题真伪、真实历史可识别性或预注册。

应用只从实际 bounded inspector 获取重新审计的 source、ledger 与停止事实，不接收自报 JSON 作为证据。外层终态后，已完成且 metric eligible 的 false 见证允许存在性反例；后续失败不会删除该见证。NO 必须有非空全 true 已审计集合，且搜索完整或在候选边界干净耗尽资源／原 attempt 预算；所有入场都必须有完成事实，原预算拒绝的新槽位另作显式例外。无 false 的空、失败、未知、INCOMPLETE、未决或活动 campaign 返回 NOT_EVALUABLE。坏证据仍报错。

报告列出精确集合、已审计与未评估范围、原冻结预算、campaign 冻结限额、实际入场与停止原因。时间耗尽本身不支持 NO；只有全部 admission 已完成、非空全 true 且后缀未派发才允许有范围 NO。前缀 NO 不改变 stopped 状态，不推广至未执行后缀或连续空间，不能推算全局 trial 历史或原协议停止时剩余额度。当前运行环境未统一，不作纯延迟因果归因；环境可比门仍由后续独立比较合同处理。

## 交付边界

Evaluate 为只读派生输出，不再执行或占用原 attempt，也不写 runs 绕开 campaign 配额。Authority 以独立 namespace 原子发布；重复只读报告不补写历史。应用标记 LOCAL_REAUDITED，纯内容 loader 不认证来源、作者或物理资源历史。S08 的封包／确认 lifecycle、S10 恢复与完整试验账本继续独立实现。

## 验收

固定反例、预算内 true 前缀、全 true 有限计划、未知／失败／未决、零覆盖与损坏证据需要独立 oracle。真实安装验证保持旧 claim flags、原 slots 和 source 字节不变；执行前冻结独立 −3 USD 合成 criterion，报告阶段在 core-only guard 下禁止执行、网络和写入。六核心组合、两原生平台与真实 source archive／wheel 的结果均由远端 CI 回填，不以拟定测试冒充验收。
