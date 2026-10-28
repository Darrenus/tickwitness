# Sprint 8 独立复核与确认窗口状态

更新：2026-10-28（Asia/Singapore）。Owner 已合并 [PR #91](https://github.com/Darrenus/tickwitness/pull/91)，基线 merge 为 `2a83d39022ce5d53edbb42dafef897c6b5d1bd0c`；Sprint 7 在其声明范围接受。`0.2.0.dev0` 仍未发行，真实用户采用与独立人类领域复验没有新增证据。

## 切片与验收门

| 故事 | 实际范围 | 状态 |
| --- | --- | --- |
| S08-01 / #22 | 搜索数据／约束／候选／原预算槽位／结果／停止／版本完整闭包，离线重建 finding 和候选 trace diagnostics | 本轮实现，远端验收待完成 |
| S08-02 / #23 | 确认协议与一次性开启／暴露记账 | 后续实现，本轮拒绝 confirmation |
| S08-03 / #24 | Alpha scorecard 与真实外部复验记录 | 后续验收，未新增外部尝试或采用证据 |

原 [Sprint backlog](sprint-backlog.md#s8--独立复现与-alpha-门槛) 的12h／12h／8h专项估算与每Sprint持续质量容量保持；实际工时未登记，测试数量不替代外部验收。

## S08-01 实现边界

合同见 [Search Evidence v1](../contracts/search-evidence-v1.md)，决策见 [ADR 0025](../adr/0025-portable-search-evidence.md)。新包独立于旧8／12／14角色格式；变量角色通过严格inventory绑定显式缺省与真实存在的对象。包含development raw／normalized／quality／manifest、完整finding authority及内嵌plan／protocol／assumptions／候选journal、budget／admissions／stops、dispatch／link／captured result、原协议已观察reservation prefix、所选attempt的intent／outcome与全部必要CAS、原finding report和相邻已完成候选的trace诊断。

Export要求expected report ID，先重审当前实际来源，收集真实存储字节，再经内存ports重建并要求相同报告；缺对象不现场重造，不增加原attempt，不覆盖目的地。输出必须位于原source roots之外，避免向原控制namespace添加未知目录。256MiB／4096文件／2MiB manifest为独立受限profile，包含manifest的最终聚合上限在发布前核对；收集阶段也逐项限制，超限整体拒绝保留原件，不裁候选后缀。

Verify仅需包和core安装，不需要原SQLite／registry／ledger／workspace或native。它重新规范化raw并核对quality及manifest，复用原只读审计从闭包重建预算、派发、原槽位、账务、覆盖与三类finding；报告和诊断逐字节相等才返回FINAL。这里的重建是独立轨迹／语义审计，不重新启动native，`native_replayed=false`。FINAL只表示所供内容闭包，不认证作者、原始发布、完整历史、物理时间／存储或确认集；无inner header时明确未观察原ledger，而不是证明零尝试。

诊断复用既有ReplayComparison对相邻已完成且已审计候选比较声明条件和trace引用；raw轨迹完整保留。它不构造baseline对照、不新增baseline翻转或纯延迟因果判定。原报告的CE／预算内NO／NOT及旧claim权限不改变。

## 远端验收要求

从S07-03实际3个core／10个native案例导出，复制发行者workspace后删除全部原目录，移动包，再在禁止原stores、SQLite、native、Popen、network和写入口的core-only环境重审。检查report原字节、snapshot／diagnostic身份、预算前缀、失败／未知／在途和零执行；missing声明对象需精确role／hash错误，不能降成NOT。重算全部外层hash的报告／诊断／账务／停止篡改仍须被语义重建拒绝。

包括严格JSON／角色／别格式互拒、nofollow／FIFO／额外对象、dedup alias、聚合精确边界、原子不覆盖、并发唯一赢家、pre/postcommit故障保留，以及实际wheel和实际source archive安装闭环。全部测试、格式化、构建、安装和原生执行仍在远端；实际运行、head与artifact证据待回填。未满足外部复验与确认窗口门时不发行早期alpha。
