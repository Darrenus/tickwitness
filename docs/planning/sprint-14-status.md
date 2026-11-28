# Sprint 14 核心诊断补强状态

更新：2026-11-28 Asia/Singapore。核心 fallback；MCP／HTTP DEFER，核实需求 UNKNOWN。

## 已接受的两个切片

| 切片 | Owner 接受与合并 | 接受源码自己的远端验证 |
| --- | --- | --- |
| S14-01a／#40，8h预测 | PR117/source09dc19e→merge484fab84f78c55ed7ac1bdfd3cb14af93cf8d1b6；Darrenus于11:52:43接受合并 | Engineering16/16、focused128、Transport91、Docs162/984；legacy REFUSED另记 |
| S14-02a／#41，8h预测 | PR118/source3e665465b7b764cfc48c94964433939c4477e13a→mergefcbb0fb1bcbe97e312e4955ad71f1b58c7d027df；Darrenus于16:16:54接受合并 | Engineering17/17、journal34／inspection155／baseline128、Transport91、Docs167/1005；legacy REFUSED另记 |

[PR118](https://github.com/Darrenus/tickwitness/pull/118)在2026-11-28T08:16:54Z正常matching-head合并。
Merge与source同tree64e1806b53c7c342f32f368080628eefb0cd11b2；实际CI checkout5d6e292a531573506551959265a68c44059792bc。
当时20checks为19SUCCESS＋1已披露legacyFAILURE／0pending，required documentation／engineering满足，
分支保护未修改或绕过。接受例外只适用于该PR，不构成下一候选的全局豁免，也不把失败改为通过。

01a按[baseline合同](../contracts/baseline-evidence-diagnostics-v1.md)／ADR0052先冻结55d4ec6，
仅对有效manifest声明的CAS leaf真实ENOENT提供role(s)/SHA，保留原code/exit3与成功回执。
02a按[检查合同](../contracts/inspection-absence-context-v1.md)／ADR0053先冻结64cca6f，
在六个真实lookup提供request/dependency上下文，保留原读取顺序、各code/exit4、回执及预算消耗语义。
有效未完成reservation仍成功reserved_unfinalized、budget_consumed=true；缺件不证明预算可用。
这些是CLI适配层能力，没有扩展SDK五方法／七导出或研究执行权限。

PR118另有持续质量companion[#119](https://github.com/Darrenus/tickwitness/issues/119)，现已接受并CLOSED。
先冻结6239889的[Journal合同](../contracts/job-journal-unlinked-read-conflict-v1.md)／ADR0054，
在未改adapter时取得真实31PASS/3FAIL，再取得相同34项全通过及完整原取消矩阵。
仅固定optional journal只读REG/nlink0＋实际named no-follow ENOENT进入已有conflict9；
writer、mandatory、替换/relink、alias/type和其他IO仍strict3，不重试或扩大期限。

[失败历史](s14-02a-job-journal-2026-11-28.md)保留原4ce取消测试失败、2fd确定性RED、
5a安装checker失败与25f格式失败及后续取消。4ce原inner文件、5a原差异字段和child回执仍UNKNOWN。
当前3e的macOS目录nlink观察不追认旧起因。原16-call/90s/15s检查已在六安装消费路径产生96条通过观察；
副本持久names/type/bytes及原源树strict保持，实际日志、全部110制品metadata及四份选定payload已收齐，
其余payload是metadata-only。没有声称所有110份正文均下载。

## 当前唯一活动功能：S14-02b／F03／#41

维护者摩擦：现有[CLI分支](../../src/tickwitness/cli_jobs.py)、[CLI负例](../../tests/test_jobs_cli.py)
与[安装消费者](../../scripts/smoke_jobs.py)对已验证QUEUED/FAILED结果读取仅检查job_conflict/9；
同码还涵盖BUSY、journal和ownership/version拒绝。现有有限read-conflict重读许可不能由exit9整体推断。
这是已有自动化诊断缺口，不是虚构外部用户需求。

[新合同](../contracts/job-result-refusal-context-v1.md)及
[ADR0055](../adr/0055-job-result-refusal-context.md)已以3b0eccf39978c19dffb82994b22558456883235d
仅两文档commit/push并真实读回后才开始实施。当前候选自身远端验收与owner接受PENDING，
不继承PR118或mergefcbb绿色记录。

范围只在read-job-result的identity→create=False→完整store.get成功后的原non-SUCCEEDED分支：
新增CLI-local JobConflictError subtype，保留job_conflict/exit9及原message，增加固定
reason=job_result_not_succeeded、command、requested_job_id和实际stored_state。
状态仅QUEUED/RUNNING/FAILED/LOST的那次已验证快照；不新增clock/lock/job_view读取，
不计算effective状态，不捏造CANCELLED，不调用result或启动执行。

| 类别 | 当前候选必须实际验证 | 当前状态 |
| --- | --- | --- |
| 正例 | SUCCEEDED规范结果原字节/无新换行；domain NOT_EVALUABLE的成功Job保持未知真值 | 新head远端PENDING |
| 反例 | 四种合法拒绝状态exactcode/message/fields/exit9、空stdout；RUNNING不改为effective状态；Catalog不变 | 新head远端PENDING |
| 未知／其他拒绝 | get缺件/损坏/权限/BUSY/journal仍原route；第二result异常或None不加伪造state | 新head远端PENDING |

真实SUCCEEDED缺／坏BLOB和nonSUCCEEDED夹带BLOB仍在get先integrity3。
get/result是两个read transactions，不承诺跨调用原子性；第二result错误及原raw=None fallback原样。
没有new reason也不证明可重试；FAILED/LOST不授予research retry、退款或checkpoint恢复。
应用服务、infra、领域状态机、SDK和持久格式不改。

真实Catalog夹具用既有transition准备，不执行worker/native/research；准备后守卫写入/协调/重整与执行入口。
Catalog读取只允许已有mode=ro。库存包含全部名字/类型/普通文件字节；没有WAL/SHM/journal排除，
该Store本来拒绝WAL/SHM，不能套用02a DatasetStore sidecar例外。目录时钟/atime不作不变性承诺。
安装验收加强既有QUEUED/coreFAILED读取，并保留SUCCEEDED原字节、transcripts、guards和原预算；
不增Job执行、freeze/reserve/replay或smoke调用/期限。新源码仍须自身17-job完整真实终态。

## 原容量与未承诺工作

| 容量部分 | 预测 | 接受／承诺状态 |
| --- | ---: | --- |
| 父项01／#40首切片01a | 8h | 已接受 |
| 父项01剩余 | 4h | UNCOMMITTED，无并行功能 |
| 父项02／#41首切片02a | 8h | 已接受 |
| 父项02剩余02b／F03 | 4h | 当前唯一活动功能：合同1＋实现1＋远端验收1＋文档1；新head／owner PENDING |
| 父项03原预测 | 8h | UNCOMMITTED，未并行选择tagged诊断或transport消费者 |
| 原S14总容量 | 32h | 已接受16＋已选择4＋未承诺12 |

全部为预测，不冒充实际工时。稳定72父故事、原12/12/8h上限不变，#40父项OPEN不代表余4h在开发，
#41仍OPEN/in-progress待剩余切片接受；#119已关闭，不另计一项功能或借用未承诺容量。
十二角色tagged-pair缺件诊断是另一个有源码负例的候选，但涉及独立IO/race验收，当前不选。

## 保留的人类门、原研究预算与运行边界

M0只支持可信owner及既有资格profile；M1未集成／DISABLED，M2不支持。
ReviewerUNASSIGNED／独立安全NOT_PERFORMED；[#24](https://github.com/Darrenus/tickwitness/issues/24)
外部真人0attempts／0successes／PENDING。实际案例表空，联系／回复／意向／协助／决定UNKNOWN，
没有激活日期、30天窗口或可计算复用率。CI、AI审阅和owner合并不代填人类证据或宣称beta。

所有项目import/test/lint/format/type/build/native回放远端执行；桌面仅静态编辑、nativeGit/gh与惰性字节检查。
原5/8/11槽、golden、PR94、实际参考24＋历史21=45和600/10/2窗口不变。
失败／中断／未知不退款，真实新执行须同一原协议新槽，已提交结果不重复执行。
不启动AWS／新资格／原host export或旧ACK，不开放listener、外发联系或release，所有CLOSED封存不改。
