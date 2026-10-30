# Sprint 9 合法反例缩减状态

更新：2026-10-30（Asia/Singapore）。Owner 已合并 [PR #97](https://github.com/Darrenus/tickwitness/pull/97)，接受merge为 `4e3691cccbe28f76b777814d1bac297082ed13c1`，#96兼容性修复接受后进入S09-01b。S09-01a已由[PR #95](https://github.com/Darrenus/tickwitness/pull/95) merge `a2c711861d1d776c78b4b5f5471f8afa388d390f`接受；其功能基线及历史run保持原值。[S08-03 / #24](https://github.com/Darrenus/tickwitness/issues/24) 真实外部复验仍0／PENDING，owner请求的AI自动化回传另记技术证据。原PR94转交归档与pin不变，无新release。

## 切片与验收门

| 故事／切片 | 范围 | 状态 |
| --- | --- | --- |
| S09-01a / #25 | 合法缩减recipe、完整必要前缀输入准备与独立重建 | Owner已合并 [PR #95](https://github.com/Darrenus/tickwitness/pull/95) 接受软件 |
| S09-01b / #25 | 在原协议共同预算下真实从头执行前缀，持久关联intent／attempt／outcome，审计账户／订单／显式在途状态 | 实现中，远端验收待完成，#25待owner接受后才关闭 |
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

## S09-01a 远端验收记录

功能代码 head 为 `471a5978dea6d9b135f56f250156210d80feab86`，[Engineering 40688297721](https://github.com/Darrenus/tickwitness/actions/runs/40688297721) 与 [Documentation 40688297566](https://github.com/Darrenus/tickwitness/actions/runs/40688297566) 共13 checks全部通过。actual merge checkout 为 `6ad72789de5b79a2c8471efc509fc7b5272c9875`，与PR head分开记录。后续验收文档提交有独立的最新head检查，不冒充相同功能head。

Ubuntu 24.04／macOS 15 × Python 3.12／3.13／3.14 六组合各 **3092 passed / 112 optional-native skips**；原生 Ubuntu 24.04 与 macOS 26／Python 3.12 各 **3201 passed / 3 core-only skips / 313 warnings**。Lint、275文件格式、126 source files严格类型检查与89文档／456本地链接均通过；这些数字属于上述功能run，warnings保留。全部项目执行在远端，本机仅编辑文本、静态审阅、Git／gh控制与下载产物读取。

| 实际 artifact（共同后缀 `6ad72789de5b79a2c8471efc509fc7b5272c9875`） | 内容与来源 |
| --- | --- |
| `reduction-input-core-…` | [12816445729](https://github.com/Darrenus/tickwitness/actions/runs/40688297721/artifacts/12816445729)：实际core wheel独立安装 |
| `reduction-input-ubuntu-24.04-…` | [12816218225](https://github.com/Darrenus/tickwitness/actions/runs/40688297721/artifacts/12816218225)：Linux原生作业内的独立core-only verifier |
| `reduction-input-macos-26-…` | [12816645843](https://github.com/Darrenus/tickwitness/actions/runs/40688297721/artifacts/12816645843)：macOS原生作业内的独立core-only verifier |
| `reduction-input-source-wheel-…` | [12816976157](https://github.com/Darrenus/tickwitness/actions/runs/40688297721/artifacts/12816976157)：实际sdist内脚本／语料与重建后安装的core wheel |

四份实际报告均为 `installed_reduction_input_acceptance_v1`、accepted=true，各含5个正例、17个拒绝场景和28份真实执行transcripts。每份保留目录的141个文件哈希已逐一核验，外部report与目录内report字节相同；包与诊断保留30天。五个preparation IDs跨四条安装链路相同，运行解释器身份按实际venv记录，不能把路径别名当环境分离。聚焦前缀preparation ID固定为 `f19cf603140cd1ff4c46b08a842619ee07f57dbba028062908c418a31f95c2ab`。

| 实际核验 | 结果与权限 |
| --- | --- |
| 完整与缩短输入 | 五例event_count／warmup_count分别为7／0、6／3、6／3、6／4、4／3；no-op保留原完整情景，focused-prefix逐字节等于其前6行，必要warmup前3行SHA为 `d757fbefd6807a1241cf3278414c187dff87beb6a6166fb4f57d894a5b9c3d39` |
| 变化与绑定 | 2e9→1e9ns重派完整候选情景，再截取；capture1..6及其它字段保留，受影响warmup、scenario／view／context身份实际变化；不声称收益单调或局部最小 |
| 移动与重复复算 | 删除复制的issuer／旧prepared目录，源包与准备包移位后guarded installed core复验；每个verify只将原回执status改为RECOMPUTED_PREPARATION_ONLY，其余完全一致 |
| 实际拒绝 | pre-IO tripwire得到8次unsafe request与2次confirmation拒绝；17个CLI拒绝含真实clean control／错误pin／端点／锚点／checkpoint、3个外层重hash语义攻击、2个缺件／字节篡改及2个confirmation拒绝，实际退出分别与预期2／3／5一致 |
| IO边界 | 远端回归覆盖精确role上限、canonical／unknown／nofollow／FIFO、源root与alias排除、原子不覆盖、发布竞争、提交前write／sync清理和提交后sync不确定完整保留；只证明观察到的边界 |
| 源与权限 | relocation后的两份完整source逐字节等于committed golden，CE仍只有原reservation1..3；guard禁止native import、SQLite／原stores、网络／worker及原预算写入口。9项flags精确，只有requires_full_prefix_replay=true，其余均false；无新attempt、运行态、checkpoint、缩减finding或confirmation权限 |

初轮远端发现格式／导入排序问题，应用远端生成补丁；CLI测试夹具抄写bundle pin漏了两位，按实际manifest SHA修正后原严格断言通过，没有放宽身份校验。并行交叉审阅与下载产物审计均为AI辅助，不冒充外部用户、人类领域接受或完整历史认证。

[PR #95](https://github.com/Darrenus/tickwitness/pull/95) 仅交付S09-01a软件，现已由owner合并接受。#25因01b实际执行与状态验收未实现而继续打开；S09-02／03独立推进。#24继续打开，真实外部复验0／PENDING，现有PR94转交归档和pin不变；无新release、采用、访谈、实际工时或研究收益记录。

## S09-01b 实现与验收门

合同见[Reduction Execution v1](../contracts/reduction-execution-v1.md)，决策见[ADR 0029](../adr/0029-origin-prefix-execution.md)。真实执行仍从原始首snapshot开始，保留完整warmup与候选prefix，不向引擎注入静态盘口或旧账户状态。实际native结果经原有`evaluate_replay`独立核对全部输入、初始账户、fills／fees、订单生命周期、final账户和显式pending ledger。

执行前核对完整source/preparation及现有live ledger的全部已观察reservation prefix、候选intent／outcome和CAS。只允许同一源ExecutableProtocol拥有槽位，不从portable恢复空ledger、改protocol或返还预算；允许live追加合法suffix。记录中未观察的baseline outcome不伪造为“应当不存在”。原max_attempts、max_events、max_wall_seconds保持；本轮不延长既有搜索candidate journal或其campaign限额，也不实现S09-02的自动缩减循环。

每次运行先reserve，再持久绑定新reduction intent及4件准备CAS，确认可读后才构造worker。完整处理N个retained事件才允许成功state audit；EOF仍有挂单或命令可为INCOMPLETE，其估值保持原core规则的not_eligible，不变成反例保持。native失败、非法轨迹、超时、bind失败均消费原槽位；terminal发布异常／错ID只报不确定，不用failure覆盖已提交receipt、不重跑不退款。只读inspect重建准备与全部状态audit，缺件失败不修复、不占slot；reserved_unfinalized不是S10恢复授权。

状态边界固定为`after_native_run_before_dispose_v1`：这是engine.run返回后的账户／订单／显式在途投影，不能声称focus边界完整初态、engine.end前状态或可恢复checkpoint。native初始账户被核对且全部warmup真实回放；隐藏队列／RNG／策略内部状态不导出，cash lock只核非负及free+locked=total，不认证完整保证金分配算法。01a准备flags、真实run audit flags与当前只读inspect flags分别表达各自阶段，不改旧格式、engine语义或原source命题权限。

远端验收将新qualification协议从一开始冻结5槽：baseline1、两个实际search候选2／3，导出不可变source快照后再准备并执行两段前缀4／5，之后预算拒绝必须不构造引擎。旧3槽已耗尽golden保持原样。实际短prefix需观察部分成交和取消在途的INCOMPLETE，较长prefix需观察取消完成／pending为空；不预填原生结果。core-only安装只验证拒绝／审计边界，actual-native由Ubuntu、macOS与实际sdist安装链路单独执行，不能把fake port标成native。

当前实现与远端验收尚未完成；#25保持打开，S09-02／03另验，外部真人0／PENDING，无新release或研究收益声明。
