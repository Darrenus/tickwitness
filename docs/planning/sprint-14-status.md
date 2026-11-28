# Sprint 14 核心诊断补强状态

更新：2026-11-28 Asia/Singapore。核心 fallback；MCP／HTTP DEFER，核实需求 UNKNOWN。

## 已接受的三个切片

| 切片 | Owner 接受与合并 | 接受源码自己的远端验证 |
| --- | --- | --- |
| S14-01a／#40，8h预测 | PR117/source09dc19e→merge484fab84f78c55ed7ac1bdfd3cb14af93cf8d1b6；Darrenus于11:52:43接受合并 | Engineering16/16、focused128、Transport91、Docs162/984；legacy REFUSED另记 |
| S14-02a／#41，8h预测 | PR118/source3e665465b7b764cfc48c94964433939c4477e13a→mergefcbb0fb1bcbe97e312e4955ad71f1b58c7d027df；Darrenus于16:16:54接受合并 | Engineering17/17、journal34／inspection155／baseline128、Transport91、Docs167/1005；legacy REFUSED另记 |
| S14-02b／F03／#41，4h预测 | PR120/sourcec218754959aedb5759eb6ba96b6b1dc89477a943→merge06fe2ef1267728c849f71bbdee54c90409015bd3；Darrenus于17:33:49接受合并 | Engineering17/17、Job focused253（含34新项）、journal34／inspection155／baseline128；legacy REFUSED另记 |

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

## 已接受的S14-02b／F03

[PR120](https://github.com/Darrenus/tickwitness/pull/120)于2026-11-28T09:33:49Z正常matching-head合并；
sourcec218与merge06fe同tree20c19817f28247a4e638dea10dca8ba953df56dc。
当时20checks为19SUCCESS＋1披露legacy REFUSED／0pending，required Docs／Engineering满足。
原非必需失败没有改成成功，接受只限该PR；父项#41按已接受12h实际CLOSED。

[Job结果合同](../contracts/job-result-refusal-context-v1.md)／ADR0055先以3b0eccf仅文档实际推送并读回。
实现只在原完整get成功后的non-SUCCEEDED分支补充四种已知持久状态；原job_conflict/9、
原message与SUCCEEDED结果字节保留。第二result读及缺件、损坏、BUSY等未知路线不重分类，
不承诺两个read transactions原子性，也不授予研究retry、退款或有效状态推断。

接受源码自身Engineering46126967098完整17/17：focused253含34新项，journal34、
inspection155、baseline128均无fail/error/skip；six core、two whole native、four controls、
distribution与preview均实际终态成功。安装Job观察为14条（distribution2、native Ubuntu4、
native macOS4、一个preview core-only4），不是16条：5次已知状态拒绝与9次原字节成功，
source/copy保持。既有inspection96条仍通过。Docs169/1011、Transport91通过。
Legacy46126967107仍因未知attachment拒绝，commands=[]、load=false；
反例未执行，研究计数NOT_RECORDED，不能填0。原格式失败与取消历史及metadata-only边界保留。

## 当前唯一活动功能：S14-03／F04／#42

维护者摩擦来自现有twelve-role reader、真实manifest/object删除负例及安装verify消费者：
声明的raw、receipt或assessment CAS leaf缺失与manifest/container缺失同为generic错误，
不能定位manifest中的role(s)/SHA。这是现有工作流证据，不是外部用户需求或新入口。

[合同](../contracts/tagged-pair-missing-object-diagnostics-v1.md)／
[ADR0056](../adr/0056-tagged-pair-missing-object-diagnostics.md)已以
3b668204115fc96d20f39de6751c94e72661e7c5仅两文档commit/push并真实读回后才实施。
当前源码自己的完整17job／owner接受仍PENDING，不继承c218或merge06fe结果。

范围：独立TaggedPairMissingObjectError，只来自完整有效12-role manifest和安全打开的containers。
完成结构扫描后取最小缺失SHA；真实declared stat ENOENT记下并继续查结构；实际open ENOENT
只报告该对象。aliases完整排序，保留no-follow/nonblock/配额/cleanup。
只有verify-tagged-queue-pair在原integrity3中投影固定reason、role、roles、sha256；
实际issue-tagged-findings source路径仍generic {code,message}，不调用publisher。
共享reader的human message可更具体，不承诺该caller旧文字逐字相同。
Baseline8、finding14与search独立；SDK/domain/schema/成功回执/authority不改。

| 类别 | 当前源码必须真实验证 | 当前状态 |
| --- | --- | --- |
| 正例 | recorded real golden移位包的原canonical语义回执逐字节保持 | 自身远端PENDING |
| 反例 | 所有unique leaf、完整alias、多缺件、真实stat/open unlink及结构优先；原件／副本保持 | 自身远端PENDING |
| 未知／其他拒绝 | root4；manifest/containers/unsafe/IO/hash/read及post-open ENOENT generic3；双向profile隔离；实际issuer优先序 | 自身远端PENDING |

缺件不证明其他对象有效、pin一致、来源认证或研究命题。malformed pin仍先拒绝；
well-formed pin在原完整read后才比较。alias opaque负例只验证IO，不算语义正例。
安装helper仅在原2/4-profile loop后一次复用standard-gt/relocated；新诊断只copy，
最多24 verify/shared90s/child15s，不增golden/export/native/Job/freeze/reserve/replay。
CLI import前class-compatible guards拒绝SQLite双alias、native、socket、worker，
研究repo构造／发布／reservation不得触发且记录吞掉尝试。明确无排除的nofollow库存，
先收child/streams/timeout及source/copy前后再统一判；不承诺atime/目录clock不变或hostile隔离。

## 原容量与未承诺工作

| 容量部分 | 预测 | 接受／承诺状态 |
| --- | ---: | --- |
| 父项01／#40首切片01a | 8h | 已接受 |
| 父项01剩余 | 4h | UNCOMMITTED，无并行功能 |
| 父项02／#41首切片02a | 8h | 已接受 |
| 父项02剩余02b／F03 | 4h | 随PR120已接受，父项#41 CLOSED |
| 父项03／F04／#42 | 8h | 当前唯一活动：合同2＋实现3＋远端验收2＋文档1；新head／owner PENDING |
| 原S14总容量 | 32h | 已接受20＋已选择8＋未承诺4 |

全部为预测，不冒充实际工时。稳定72父故事、原12/12/8h上限不变，#40父项OPEN不代表余4h在开发，
#41已CLOSED；#42是唯一活动父项，#119已关闭，不另计功能或借用父项01未承诺容量。
原条件transport forecast保留为历史，需求UNKNOWN／DEFER，不与当前tagged诊断叠加。

## 保留的人类门、原研究预算与运行边界

M0只支持可信owner及既有资格profile；M1未集成／DISABLED，M2不支持。
ReviewerUNASSIGNED／独立安全NOT_PERFORMED；[#24](https://github.com/Darrenus/tickwitness/issues/24)
外部真人0attempts／0successes／PENDING。实际案例表空，联系／回复／意向／协助／决定UNKNOWN，
没有激活日期、30天窗口或可计算复用率。CI、AI审阅和owner合并不代填人类证据或宣称beta。

所有项目import/test/lint/format/type/build/native回放远端执行；桌面仅静态编辑、nativeGit/gh与惰性字节检查。
原5/8/11槽、golden、PR94、实际参考24＋历史21=45和600/10/2窗口不变。
失败／中断／未知不退款，真实新执行须同一原协议新槽，已提交结果不重复执行。
不启动AWS／新资格／原host export或旧ACK，不开放listener、外发联系或release，所有CLOSED封存不改。
