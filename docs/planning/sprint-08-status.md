# Sprint 8 独立复核与确认窗口状态

更新：2026-10-28（Asia/Singapore）。Owner 已合并 [PR #91](https://github.com/Darrenus/tickwitness/pull/91)，基线 merge 为 `2a83d39022ce5d53edbb42dafef897c6b5d1bd0c`；Sprint 7 在其声明范围接受。`0.2.0.dev0` 仍未发行，真实用户采用与独立人类领域复验没有新增证据。

## 切片与验收门

| 故事 | 实际范围 | 状态 |
| --- | --- | --- |
| S08-01 / #22 | 搜索数据／约束／候选／原预算槽位／结果／停止／版本完整闭包，离线重建 finding 和候选 trace diagnostics | 远端验收通过，[PR #92](https://github.com/Darrenus/tickwitness/pull/92) 待 owner 审阅；#22 保持打开 |
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

包括严格JSON／角色／别格式互拒、nofollow／FIFO／额外对象、dedup alias、聚合精确边界、原子不覆盖、并发唯一赢家、pre/postcommit故障保留，以及实际wheel和实际source archive安装闭环。全部测试、格式化、构建、安装和原生执行仍在远端；实际运行、head与artifact证据见下节。未满足外部复验与确认窗口门时不发行早期alpha。

## S08-01 远端验收记录

功能代码 head `1623aaccaa8f4e8f6432989e6a877e4b1790e4c8` 的 [Engineering 40662769753](https://github.com/Darrenus/tickwitness/actions/runs/40662769753) 与 [Documentation 40662769748](https://github.com/Darrenus/tickwitness/actions/runs/40662769748) 共13 checks 全部通过。实际 merge checkout 为 `42af1e23987835a9975cff1225175cbf3eec0bfb`，与 PR head 分开。后续验收文档提交须以 PR #92 最新 head 的独立 checks 为准，不冒充相同功能代码 head。

核心 Ubuntu 24.04／macOS 15 × Python 3.12／3.13／3.14 六组合各 **2752 passed / 112 optional-native skips**；原生 Ubuntu 24.04 与 macOS 26／Python 3.12 各 **2861 passed / 3 core-only skips / 313 warnings**。Lint、244 文件格式、112 source files 严格类型检查、80 文档／414 本地链接，以及实际 wheel／sdist 安装闭环全部通过；这些数字属于上述功能 run，warnings 保留。所有项目执行都在远端，本机只进行文本编辑、静态审阅、Git／gh 控制与下载产物读取。

安装验收报告均为 `installed_search_evidence_acceptance_v1`、accepted=true。下列 artifacts 内含报告和完整新格式包，保留30天；源码包链路使用实际 tar.gz 内脚本／样例和新安装的实际 wheel。

| 实际 artifact（共同后缀 `42af1e23987835a9975cff1225175cbf3eec0bfb`） | ID 与内容 |
| --- | --- |
| `search-evidence-core-…` | [12804168857](https://github.com/Darrenus/tickwitness/actions/runs/40662769753/artifacts/12804168857)：3个 core 案例 |
| `search-evidence-ubuntu-24.04-…` | [12804098468](https://github.com/Darrenus/tickwitness/actions/runs/40662769753/artifacts/12804098468)：10个 native 来源案例，由 core-only 复验 |
| `search-evidence-macos-26-…` | [12804534294](https://github.com/Darrenus/tickwitness/actions/runs/40662769753/artifacts/12804534294)：10个 native 来源案例，由 core-only 复验 |
| `search-evidence-source-wheel-…` | [12804454276](https://github.com/Darrenus/tickwitness/actions/runs/40662769753/artifacts/12804454276)：实际源码包／wheel 的 core3与native10案例 |

| 实际核验 | 结果与权限 |
| --- | --- |
| 脱离原目录 | 每个包导出后删除复制的完整发行者 workspace，移动包，再用禁止原stores、SQLite、临时恢复、native、Popen、network和研究写入口的core-only guard重审；全部保持相同原报告、snapshot与诊断，重复回执一致，只读字节树不变 |
| 三类结论 | core3均为 NOT_EVALUABLE；两个native平台及源码包native各为3个 COUNTEREXAMPLE_FOUND／4个 NO_COUNTEREXAMPLE_FOUND／3个 NOT_EVALUABLE；完整all-true集合的planned_predicate_truth=true，预算内true前缀仍为null，不扩大未访问候选覆盖 |
| 原预算及未知历史 | 有inner时重建完整已观察原protocol reservation prefix，保留baseline／其它plan已消费槽位，原预算耗尽案例不新增attempt；无inner的时间停止案例prefix／ledger重建旗标为false、reservations／attempts／CAS为空，仅表示历史未观察 |
| 具体分歧 | 各native报告有2对相邻已完成候选诊断，其他案例为0；source-normal首个记录差异为 `/input_trace/3/fields/native_ts_event_ns`，两侧仍指向capture_seq4的原始delta。该诊断不变成baseline翻转、纯延迟因果或全局最早业务原因 |
| 缺件与伪造 | 删除raw得到exit3及 `search_evidence_object_missing`，role=raw、hash=`89ace783f83ea99ba7e10a83ad667a95e2154e184b713136ec909d4654267789`；重算全部外层hash的finding／diagnostics篡改仍在语义重建时拒绝 |
| 发布与资源边界 | report／bundle错误pin、已存在目标覆盖均拒绝，同证据同包身份，原记录字节与slots不变；严格角色、精确聚合边界、nofollow／FIFO、dedup、并发唯一赢家与提交前后故障由远端回归覆盖；超profile整体拒绝并保留原记录 |
| 执行与认证范围 | 所有安装验收报告new_native_calls=false、new_attempts_reserved=false；FINAL仅为所供内容闭包，authorship／原发布／完整trial历史／原资源执行／confirmation认证保持false |

初轮远端发现格式／导入、nullable bytes循环变量与snapshot类型问题，应用远端格式补丁及类型修正后完整重验。安装smoke最初把无inner案例的ledger重建旗标写死为true，已改为精确匹配 `ledger_prefix_observed`，保持未观察语义，而非放宽报告oracle。AI 并行静态审阅另补强了输出必须位于原source roots之外；该审阅属于AI辅助，不宣称独立人类领域接受。

[S08-01 / #22](https://github.com/Darrenus/tickwitness/issues/22) 的实现与远端验收在上述受限profile范围交付，仍待owner合并#92后接受；不自动关闭故事、不发行新版本。S08-02确认窗口、S08-03真实外部复验与alpha scorecard、S10恢复和真实访谈继续独立验收，未新增实际工时、市场采用、研究收益或独立人类复验记录。
