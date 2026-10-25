# Sprint 2 数据证据工程状态

更新：2026-10-25（Asia/Singapore）。PR#73已获owner接受并合并；S1两项工程故事已完成，真实访谈仍为0次。按继续开发授权，先推进不依赖真实用户证据的数据证据技术前置；产品需求、市场采用和访谈门槛均保持未完成。

| 故事 | 本批范围与状态 | 仍未完成 |
| --- | --- | --- |
| S02-01 / Issue#4 | 实现规范化JSONL v1、有界安全输入、结构/序列预检与隔离报告，待本PR验收 | 真实交易所原始协议adapter、完整盘口/时钟认证和大文件列式扫描不在此范围 |
| S02-02 / Issue#5 | 不可变raw/normalized/report CAS、manifest、SQLite sealed catalog、幂等与完整性核验已实现，待PR验收 | 默认回放引擎选择仍未通过，故事整体不标Done |
| S02-03 / Issue#6 | 当前保持计划状态 | ClaimSpec/冻结协议/应用层holdout拒绝及真实访谈未实现或未完成，不能以本次导入替代 |

操作流程见[数据导入](../data-import.md)，格式见[规范化合同](../contracts/normalized-events-v1.md)。当前CLI能完成import与inspect；没有freeze、replay、搜索或最终研究判定命令。

## 工程验收边界

输入读取、结构或预算校验失败时不会构造目标store；发布期间I/O失败可留下未引用对象。合法但有缺口的输入完整封存并标quarantined。`sealed`描述证据提交完整性，`accepted`只描述明示的结构/序列预检；所有报告都显式声明`replay_certified=false`和未绑定时钟。重同步不补出缺失历史。

文件系统与SQLite不存在跨系统ACID事务；先校验并持久化不可变对象，再事务登记catalog，可留下未引用对象但不产生半份可用dataset。故障、篡改、symlink/FIFO、限额、幂等和并发使用真实临时FS/SQLite测试。断电恢复、安全隔离、备份和自动GC没有由这些单测获得认证。

## 研究门与范围调整

[HFT补测](../research/hftbacktest-selection-gates.md)保留20个合成案例，包含部分成交账务不一致和fill日志缺口；旧EOF推断已通过receipt证据更正。可继续受限单次成交研究，但尚不具备批准产品完整执行模型的证据。默认引擎按[ADR-003](../architecture/decisions.md)暂缓。

后续只安排有界候选试验：比较Nautilus L2/partial公开扩展，或估计HFT修复/trace hook维护成本；重新分配S02-02选型预算后再推进，不同时扩展市场、UI或两套正式adapter。当前未向任何上游仓库发送报告、Issue、PR或消息。

本批开发接受前的本地与CI证据随PR记录；未经owner验收不关闭Issue#4，Issue#5的选型项未完成时继续开放。实际人工工时尚未登记，不将AI运行时间冒充人力投入。
