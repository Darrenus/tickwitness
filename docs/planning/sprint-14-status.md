# Sprint 14 核心诊断补强状态

更新：2026-11-27 Asia/Singapore。当前路线：**核心fallback已选择；MCP／HTTP DEFER**。
已接受上游为源码`9901edd16450d65c8a483f91912cd6108475932e`；[PR116](https://github.com/Darrenus/tickwitness/pull/116)
由Darrenus于2026-11-27T15:06:02Z（23:06:02 Asia/Singapore）正常合并为
`4189fbe126d9447b39ba8f5981a5f5eeebb2e2eb`。S13-03接受的是有界审阅／降级准备、真实采用缺口记录及CI维护，
#39已按该准备范围实际结项，不把独立真人安全、外部参与者研究或复用观察记为完成。

本页跟踪新切片，不继承990或4189的绿色检查。候选实现按冻结合同推进，新head远端验收及owner接受均为**PENDING**；
合同／ADR须先实际commit、push及读回远端冻结revision，再开始实现。实际冻结和新检查发生后另记，
不将文档存在或静态审阅记为运行通过。

实际先冻结记录：仅合同及ADR0052的提交`55d4ec6557e70771411d59e05118b921dff6de50`已实际推送，
远端branch ref读回完全一致后才开始实现。冻结不等于实现／测试通过；当前候选仍需自身远端终态与owner接受。

## 为什么选择核心fallback

[入口需求记录](../support.md#httpmcp-入口需求与当前决定)仍没有可核验的真实CLI／SDK阻塞任务、
替代成本或参与者确认，状态为UNKNOWN／证据不足，而非“已证明没有需求”。
按[原S14规则](sprint-backlog.md)，本轮用同一32h容量选择核心补强，
不叠加MCP／HTTP、listener、托管或UI；原transport意图保留为条件性历史，不复制故事ID。

首个具体缺口来自[现有baseline reader](../../src/tickwitness/infrastructure/evidence_bundles.py)的
`_tree_entries`：缺manifest与缺已声明CAS对象都得到泛化缺项错误，CLI缺少对象角色及SHA上下文。
[既有文件系统负例](../../tests/infrastructure/test_evidence_bundles.py)覆盖这两类删除，
这是维护者可观察的诊断摩擦，不是虚构的外部用户请求。现有search evidence的独立诊断profile不改。

## 首切片：S14-01a／#40

范围按[Baseline evidence diagnostics v1](../contracts/baseline-evidence-diagnostics-v1.md)及
[ADR0052](../adr/0052-baseline-evidence-missing-object-diagnostics.md)先冻结。
[S14-01a／#40](https://github.com/Darrenus/tickwitness/issues/40)仅改进既有baseline `verify-evidence`的失败诊断：
保留`research_store_integrity_or_io_failure`／exit3，仅在有效manifest声明的CAS leaf真实ENOENT时，
增加`reason=bundle_object_missing`、`role`、排序的全部`roles`及`sha256`。

多项扫描缺失选择字典序最小SHA；同对象别名完整保留，`role`取排序首项。
完整扫描先检查已遇到的非法额外项／类型，不能用缺件遮蔽结构故障；扫描后open时真实消失可报告该leaf，
不宣称事务快照或穷尽健康检查。缺root保留exit4；缺manifest／容器、权限、symlink、FIFO、额外项、
大小变化、hash损坏及其他IO问题不变成带角色的缺件，不能猜测SHA或研究结果。

有效验证回执、八角色v1 bundle格式、公开SDK、研究判定、发布／修复及运行权限不改。
不下载、补件、改写原树、搜索别的store、导入native、打开SQLite、预留研究槽、replay、确认访问或reconcile。
一般tree检查及其他调用者的拒绝保持原范围；精确细则以冻结合同为准。

## 容量及未承诺工作

| 容量部分 | 预测 | 当前承诺状态 |
| --- | ---: | --- |
| 父项01／#40内的首切片 | 8h | 已选择：合同2h＋实现3h＋远端验收2h＋文档1h；尚无当前head远端验收／owner接受 |
| 父项01原12h中剩余 | 4h | UNCOMMITTED；未Ready功能 |
| 父项02原预测 | 12h | UNCOMMITTED；需从实际缺口重新细化 |
| 父项03原预测 | 8h | UNCOMMITTED；需冻结具体核心消费者／文档验收 |
| 原S14总容量 | 32h | 首8h＋余24h；不叠加transport容量 |

上述都是预测，不是实际工时。稳定backlog仍为原72项父故事，S14原12／12／8h上限不变。
typed inspect-experiment／attempt缺失上下文（F02）只有候选证据，未排程、未Ready、未实现；
是否选取及工时，包括原父项03的8h预测池，均须在剩余24h内另行细化，不承诺功能填满容量。
日常质量容量单独保持原口径；不把同一回归／维护重复计入专项和日常预算。

## 正例、负例及未知／拒绝验收

| 场景 | 需要实际验证的结果 | 当前证据状态 |
| --- | --- | --- |
| 正例：合法迁移后的完整baseline bundle | 独立安装core CLI返回原样有效回执；不需要native或SQLite；输入树不写入 | PENDING，新head远端运行后填写 |
| 负例：仅删除有效manifest声明的对象leaf | 确切code／exit3、空成功stdout、确定性SHA及完整排序角色别名；多缺项和扫描／open间真实消失按合同报告，原件和副本均不被失败读取改写 | PENDING，使用一次性合成副本；不改旧封存 |
| 未知／其他拒绝：缺root、manifest或容器，权限／不安全／额外项／损坏／变化 | 缺root仍exit4且不创建；其他结构／IO／完整性错误保持原拒绝，无伪造角色／SHA／成功或修复建议 | PENDING，不把非ENOENT当作缺件 |

源码、真实文件系统故障、已安装wheel／sdist消费者与既有baseline／search／发布／语义负例须在远端执行，
保存真实source、CI checkout／tree、各job终态、日志与覆盖范围。测试摘要通过但job未成功、跳过或启动拒绝都不计本切片通过。
桌面只做静态编辑及惰性字节／JSON／hash检查；不在本机import、测试、lint、build或执行项目代码。

## 保留的人类门、预算及运行边界

M0只支持既有可信owner及已资格内置profile；M1产品未集成／DISABLED，M2不支持。
独立安全reviewer UNASSIGNED／NOT_PERFORMED；[#24](https://github.com/Darrenus/tickwitness/issues/24)仍外部真人
0 attempts／0 successes／PENDING，实际自有案例表为空，联系／回复／意向／协助量／研究决定UNKNOWN，
没有激活日期、30天窗口或可计算复用率。已接受的[S13准备](sprint-13-status.md)不能代填这些依赖，也不宣称beta。

离线诊断不创建或重置研究协议／ledger。所有真实新执行仍需要同一原协议的新可用槽；已提交结果不重新执行，
失败／中断／未知不退款。原5／8／11槽、golden、PR94、参考本轮24＋历史21=45、600s／10s／2s窗口及所有CLOSED封存不改。
本切片不提供AWS Start、新资格、原host export／旧ACK、额外主机、外发联系或release授权。
