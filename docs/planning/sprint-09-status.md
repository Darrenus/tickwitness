# Sprint 9 合法反例缩减状态

更新：2026-10-28（Asia/Singapore）。Owner 已合并 [PR #94](https://github.com/Darrenus/tickwitness/pull/94)，本轮基线为 `3ab62bf97dd21609638e9f887f68f450bc345aaf`。软件工程继续推进；[S08-03 / #24](https://github.com/Darrenus/tickwitness/issues/24) 的真实外部复验由owner联系，仍为0／PENDING、整体保持打开。现有PR94转交归档与pin不变，没有新增外部记录或release。

## 切片与验收门

| 故事／切片 | 范围 | 状态 |
| --- | --- | --- |
| S09-01a / #25 | 合法缩减recipe、完整必要前缀输入准备与独立重建 | 实现中，远端验收待运行；软件待owner接受 |
| S09-01b / #25 | 在原协议共同预算下真实从头执行前缀，持久关联intent／attempt／outcome，审计真实账户／订单／在途状态 | 尚未实现，#25整体保持打开 |
| S09-02 / #26 | 预算内自动局部缩减、取消、反例保持判定 | Planned，不能以准备好输入代替实际反例保持 |
| S09-03 / #27 | 原／缩减证据对比、实际首次分歧定位 | Planned，不能将输入字节差异提升为业务因果 |

原 [Sprint backlog](sprint-backlog.md#s9--合法反例缩减) 的14h／12h／8h专项估算和持续质量容量保持；01a／01b是同一14h故事的验收拆分，没有新增实际工时或重估容量。没有完整运行态checkpoint的现引擎不能用盘口快照代替策略、账户、队列和在途命令。

本轮依赖S08已接受的完整软件证据与稳定事件引用，可以在外部参与者准备期间独立实现；这不宣布S08整体完成、不豁免外部发行门，也不启动S10恢复资格。

## S09-01a 实现边界

合同见 [Reduction Input v1](../contracts/reduction-input-v1.md)。从完整已验证、已审计且真值false的development搜索见证中选择原candidate，绑定原bundle／report／protocol／claim／predicate／run／spec／assumptions。先验证整个source，再按原源数据重建完整候选情景，最后保留从原始首snapshot到真实through事件的连续前缀。只允许右端截短和冻结范围内减小该见证的额外延迟；focus左界仅控制审阅范围，完整warmup仍在执行输入内。

每个准备包只有manifest、recipe、materialization和normalized四个固定文件。独立verify需要原source evidence和显式preparation ID，重新计算所有语义和输入字节；重算外层hash无法把伪造descriptor变成有效准备。目标必须在原输入root之外，以原子不覆盖方式发布；提交前失败清理stage，提交后同步不确定保留完整目标并报错。

`prefix_context_id`表示计划输入上下文，`PreparedReplay`仅静态预检。所有回执明确 `native_replayed=false`、`initial_state_materialized=false`、`attempt_reserved=false`、`witness_preservation_verified=false`，必须从原点完整重放。原始预算已耗尽的portable见证不能恢复成空ledger、新增额度或授权实际缩减执行。截短EOF可能改变未成交、部分成交、在途取消和估值范围，实际完成度及真值只能在01b的真实运行中判定。

## 远端验收要求

全部项目测试、格式化、构建和安装在GitHub Actions远端CPU执行。本机仅编辑文本、静态审阅、Git／gh控制及下载产物读取。验收使用已提交的真实合成证据，而非自填成功报告：7事件identity正对照，focus4..6必须保留1..6且warmup1..3，延迟变化重算整个候选情景及prefix context；非法端点、删中间事件、快照／checkpoint注入和完整source损坏均拒绝。包移动后由安装的core-only wheel重算，禁native、网络与研究写入口，原始证据字节树和预算槽位不变。

Ubuntu与macOS的核心／原生回归、实际wheel及实际sdist重新构建安装、严格类型／格式／文档检查独立验收。受控发布故障只证明所观察边界，不认证历史durability或S10断电恢复。本切片不宣称真实运行态、缩减反例、最小性、研究收益、市场采用或外部复验。
