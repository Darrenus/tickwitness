# Sprint 14 核心诊断补强状态

更新：2026-11-28 Asia/Singapore。路线：**核心fallback；MCP／HTTP DEFER、已核验需求UNKNOWN**。

## 已接受的首切片

Owner明确接受[S14-01a／#40](https://github.com/Darrenus/tickwitness/issues/40)的baseline离线缺件诊断，
接受源码为09dc19e0696359a18cbb1c7e930871f9b35a133e。[PR117](https://github.com/Darrenus/tickwitness/pull/117)
由Darrenus于2026-11-28T03:52:43Z（11:52:43 Asia/Singapore）正常matching-head合并为
484fab84f78c55ed7ac1bdfd3cb14af93cf8d1b6；merge与source同tree4ab7b7d587bc2e2a4d43a28675e69d81e6fabf3d。
父故事#40仍OPEN/in-progress，仅首8h预测范围已接受，余4h未承诺，不并行开展剩余功能。

| 接受源码的实际远端证据 | 结果 |
| --- | --- |
| [Engineering46025748380](https://github.com/Darrenus/tickwitness/actions/runs/46025748380) | 16/16SUCCESS，focused baseline128PASS／0failure/error/skip |
| 六core／两native | 各Ubuntu5651/112skip、各mac5613/150skip；native5760/3skip和5722/41skip，各313warnings |
| [Docs46025748510](https://github.com/Darrenus/tickwitness/actions/runs/46025748510) | 162documents／984links；quality运行后的163/984另记 |
| [Transport46025748500](https://github.com/Darrenus/tickwitness/actions/runs/46025748500) | 实际JUnit91PASS／0failure/error/skip |
| [Legacy46025748236](https://github.com/Darrenus/tickwitness/actions/runs/46025748236) | FAILURE/REFUSED未知attachment；commands[]、loadfalse、qualSKIP、diagUNKNOWN |

接受时19checks为18SUCCESS＋1上述FAILURE／0pending，不能写全部CI绿色。
Owner接受这一有界源码与已披露例外，不构成后续PR全局豁免，分支保护未改或绕过。
完整16job日志、107项制品元数据和范围所需JUnit/辅助制品已取回；不声称107份payload全下载。
五处真实安装完成标记覆盖distribution、两native与preview core/native。
初次c7头的guard注解、格式真实失败及后来自动取消分别保留，不把取消改成通过。

首切片按[baseline合同](../contracts/baseline-evidence-diagnostics-v1.md)及
[ADR0052](../adr/0052-baseline-evidence-missing-object-diagnostics.md)先实际推送／读回55d4ec6后实现。
仅有效manifest已声明的CAS leaf真实ENOENT增加reason/role(s)/sha256；原code/exit3、缺root4、
有效回执与其他拒绝保留。不修复、下载、搜索别的store或授予研究执行权。
其离线baseline验证没有SQLite，不把该profile套到需要既有只读catalog的检查命令。

已接受的上游[PR116](https://github.com/Darrenus/tickwitness/pull/116)／#39仅是有界审阅／降级及采用准备，
不代表独立真人安全、外部研究复验或实际复用完成；[S13记录](sprint-13-status.md)与原CI失败不回写。

## 当前唯一活动功能切片：S14-02a／F02／#41

[检查缺失上下文合同](../contracts/inspection-absence-context-v1.md)及
[ADR0053](../adr/0053-inspection-absence-context.md)已先以64cca6f3bb9ddda5ae17d22fef4eebf98fad9533
仅两文件commit/push，再实际读回远端一致后开始实现。
本切片的**新head远端验收和owner接受均PENDING**，不继承09、484或旧CI结果。

维护者目标是把既有inspect-experiment／inspect-attempt错误与实际查询目标／依赖关联。
源码证据是[CLI适配器](../../src/tickwitness/cli_experiments.py)、
[原应用服务](../../src/tickwitness/application/experiments.py)及
[原attempt负例](../../tests/infrastructure/test_attempt_ledger.py)：当前NotFound只有code/message，
而CAS orphan、有效未完成reservation及outcome CAS缺失有不同语义。
这是已有维护者诊断摩擦，不是虚构外部用户任务。依赖仅已接受的可信M0读取与原合成夹具，
无新增外部接口／数据权利或专家依赖；角色与账户验证不在本切片范围。

新CLI适配层仅包装已知NotFound：固定reason=inspection_evidence_not_found、command、requested_id、
六种lookup及实际已知时的resource_id。保持research_evidence_not_found或dataset_not_found各自原code／exit4，
构造registry→store→应用inspect的顺序不变；引用dataset ID只取验证后实际get入参，不解析message。
应用服务、infra分类、领域聚合、持久格式及SDK五方法／七导出不改，不复制领域验证。

| 验收类别 | 需要实际验证的结果 | 当前状态 |
| --- | --- | --- |
| 正例 | 合法experiment与finalized回执不变；有效未完成reservation仍成功reserved_unfinalized、budget_consumed=true | 新head远端PENDING |
| 反例 | 六lookup exactcode/fields；分别缺两dataset时报告真实依赖ID；CAS orphan不猜退款／组件；双故障保留原读取优先级 | 新head远端PENDING |
| 未知／其他拒绝 | 权限、普通IO、损坏、symlink/FIFO、当前泛型结构拒绝及引用不匹配无伪造context；缺outcome CAS不能变未完成成功 | 新head远端PENDING |

完整负例用远端unit/integration；安装代表矩阵最多16次inspect，共享90s、子进程各最多15s。
只复制已有smoke的frozen数据／已消耗attempt，不另freeze/reserve/replay；禁止native、worker、网络及研究写入。
允许既有SQLite mode=ro，只对目标catalog.sqlite3-wal/shm正常运行活动作明确例外；
持续证据catalog/CAS/protocol/slot/outcome名字及字节保持，不宣称目录元数据完全不变，不删live sidecar。
这不是恶意代码sandbox，也不是OS级不存在、预算可用、语义成功、repair/retry或确认访问许可。

## 原容量与未承诺工作

| 容量部分 | 预测 | 承诺／接受状态 |
| --- | ---: | --- |
| 父项01／#40首切片01a | 8h | 已接受：合同2＋实现3＋远端验收2＋文档1；不是实际工时 |
| 父项01剩余 | 4h | UNCOMMITTED；无Ready功能 |
| 父项02／#41首切片02a | 8h | 当前选择：合同2＋实现3＋远端验收2＋文档1；新head验收／owner接受PENDING |
| 父项02剩余 | 4h | UNCOMMITTED |
| 父项03原预测 | 8h | UNCOMMITTED；未选择transport客户端或其他消费者 |
| S14原总容量 | 32h | 已接受8＋已选择8＋未承诺16；不叠加transport |

稳定backlog仍为72项父故事、原12/12/8h上限。WIP只统计实际选定的02a功能切片，
#40保留父项聚合状态不表示并行开发余4h。不为填满容量虚构功能，持续质量容量不重复记账。

## 保留的人类门、原研究预算与运行边界

M0只支持可信owner与既有已资格profile；M1未集成／DISABLED，M2不支持。
reviewerUNASSIGNED／独立安全NOT_PERFORMED；[#24](https://github.com/Darrenus/tickwitness/issues/24)仍
外部真人0attempts／0successes／PENDING。实际案例表空，联系／回复／意向／协助／决定UNKNOWN，
没有激活日期、30天窗口或可计算复用率。软件接受、CI与AI审阅不能代填人类证据，不宣称beta。

所有项目import/test/lint/format/type/build/native回放继续远端执行；桌面只做静态编辑、nativeGit/gh及惰性字节检查。
原5/8/11槽、golden、PR94、实际参考本轮24＋历史21=45和600/10/2窗口不变。
失败／中断／未知不退款，真实新执行须同一原协议新槽，已提交结果不重复执行。
不启动AWS／新资格／原host export或旧ACK，不开放listener、外发联系或release，所有CLOSED封存不改。
