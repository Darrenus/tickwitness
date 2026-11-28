# 分版本支持范围与恢复政策

当前接受，2026-11-28：owner已接受S14-01a基线离线诊断源码`09dc19e0696359a18cbb1c7e930871f9b35a133e`，
[PR117](https://github.com/Darrenus/tickwitness/pull/117)由Darrenus于2026-11-28T03:52:43Z
（11:52:43 Asia/Singapore）正常合并为`484fab84f78c55ed7ac1bdfd3cb14af93cf8d1b6`。
#40仅首8h预测范围接受，父项仍OPEN，余4h未承诺且不并行开发。上游PR116／#39已按准备范围接受，
独立安全reviewerUNASSIGNED／NOT_PERFORMED、#24外部真人0/0/PENDING、空案例和无激活／复用窗口保留。
软件接受不提供beta、M1产品启用或新执行权限。

[S14](planning/sprint-14-status.md)原32h=首8h已接受＋S14-02a／#41的8h已选择＋16h未承诺
（父项01余4＋02余4＋03原8）；MCP／HTTP仍DEFER、已核验需求UNKNOWN。
仅[PR118](https://github.com/Darrenus/tickwitness/pull/118)新切片的当前head远端验收／owner接受PENDING，
不借用09／484或其他旧头结果；已接受baseline与候选inspect上下文分开，不宣称新发行。

以下PR115接受及S13-03准备进行中表述为PR116接受前的历史快照；其产品关闭／人类未完成限制仍然成立。

当前状态，2026-11-27接受后：Owner已在本次项目对话中明确回复“接受”，接受精确提交`89e12eb3e2e371ea7a4939f277bab57cd3c7843e`及已披露限制。[PR115](https://github.com/Darrenus/tickwitness/pull/115)按正常matching-head流程实际合并为`40aede39b4d7b051b00b0dd604738e736d3f4c25`，由Darrenus于2026-11-27 17:58:53 Asia/Singapore完成；合并树与接受源码相同。必需documentation／engineering通过；实际18 SUCCESS／1非必需legacy REFUSED–FAILURE／0pending保留。Owner接受这一有界交付及已披露例外，不把失败改称通过，不构成对后续PR的全局豁免。

当前软件支持边界仍是既有M0可信owner及已资格内置profile。参考24PASS和已接受交付不启用SDK／CLI／Job的M1，也不支持任意Python策略、M2或HTTP／MCP listener。[S13-03审阅／降级准备](security/s13-03-review-and-degradation.md)仅整理已证实控制、未知和关闭决定；独立真人安全NOT_PERFORMED、外部真人0/0/PENDING。[采用快照](planning/s13-03-adoption-observation-2026-11-27.md)不提供新的激活日期或观察窗口。

以下2026-11-27资格／收证记录保留其发生时的owner PENDING／Draft状态；它们不是当前owner接受状态。没有新的发行或新增运行模式。

更新：2026-11-27，Asia/Singapore。先根据安装包的版本、来源和接口合同选择入口；相同包版本号不代表相同构建字节。SDK v1 已随 [PR110](https://github.com/Darrenus/tickwitness/pull/110) 接受；S12-03 的文档执行与兼容回归按 [独立合同](contracts/sdk-compatibility-v1.md) 完成，并由 owner 合并 [PR113](https://github.com/Darrenus/tickwitness/pull/113) 接受，真实 merge 为 `df10923663a3d3c09b5b917995fbb554da60ea40`。S13-01 的[执行信任与威胁模型](contracts/execution-trust-v1.md)已随[PR114](https://github.com/Darrenus/tickwitness/pull/114)由owner实际接受，真实merge `6c350b9fe32dfed96392edd2b856e937f767e342`。S13-02先冻结[受限参考资格合同](contracts/restricted-reference-v1.md)，仅内部参考后端与固定合成探针；产品M1未开放、任意策略不支持、M2托管不支持，不能把普通CI或参考控制结果当作产品隔离／新平台认证。当前候选自己的远端结果另行记录，历史绿色不代替本轮验收。这里没有新的发行。

2026-11-27的[固定EC2 v3参考及后续只读收证](security/ec2-reference-recovery-v3-evidence-2026-11-27.md)
记录资格源码`908d56db32439f38686346687a5b43239b1b7264`完整24项PASS，
本轮24／历史21／累计45，仅QUALIFIED_REFERENCE_ONLY。独立readback63文件已CLOSED，
原handoff过期74／ACK不存在分别保留；558项固定pins及10文件资格源码闭包未变，
最后独立AWS观察为2026-11-27 15:08:26 Asia/Singapore Stopped／无公网IPv4或DNS。
文档修订前基线`b5ee94808861ed6eff085f71073bb703bfd7d6f9`的远端专用91项、
Engineering16项及Documentation已SUCCESS，旧GHA参考拒绝仍保留为历史。
[owner接受](security/s13-02-owner-review.md)PENDING，PR115 Draft／#38 OPEN／in-progress；
M1产品未集成且DISABLED，独立真人安全NOT_PERFORMED、外部真人研究复验0/0/PENDING，
均不由本次参考成功替代。S13-03／#39仍Planned，本轮没有推进条件性S14入口。

| 版本/接口 | 取得方式与状态 | 正确入口 |
| --- | --- | --- |
| `0.1.0a1` 已发行技术预览 | 固定 tag `v0.1.0a1` 和提交 `a84edddef00db8af69c7e6e67be31f0763310dca`；GitHub prerelease，无 PyPI 发布 | [0.1 快速开始](quickstart.md)、[原发行制品与验收](releases/0.1.0a1.md) |
| `0.2.0.dev0` / SDK contract v1 | 开发技术预览的固定候选 wheel 与匹配 sdist，按实际 hash/commit/CI 取得；不表示已发布 0.2 Release | [SDK 指南](python-sdk.md)、[真实消费者](../examples/sdk/README.md)、[自有案例与已验收制品](user-onboarding.md) |
| `0.2.0.dev0` / 既有 CLI profile | 每项格式、模型和操作遵循自己的版本合同；SDK v1 不自动开放这些命令 | 下文能力索引及各 Sprint 的实际接受记录 |

0.1 的固定发行物没有稳定公共 SDK、搜索 finding、一次确认窗口或后续 Job/维护能力。0.2 的新增能力不追记到 0.1 认证；也不把 SDK contract v1 等同整个包 GA 或广泛稳定的内部 Python 接口。

## 按任务划分的环境矩阵

下表区分当前 0.2 包声明、源码回归与独立安装资格，入口对应现有 [Engineering CI](../.github/workflows/engineering.yml)。SDK 声明的 Python 范围是 3.12–3.14；源码测试通过不等于同一解释器已完成独立安装消费者资格。只有候选 commit 的实际 job 成功后，才能记录本轮通过；历史 PR 成功或配置存在不能替代它。0.1 的历史矩阵固定在其发行记录中。

| 任务 | CI 环境 | Python | 依赖与验收范围 |
| --- | --- | --- | --- |
| 核心源码回归 | `ubuntu-24.04`、`macos-15`，六组合 | 3.12 / 3.13 / 3.14 | 包含 SDK 入口回归；不安装可选引擎，native case 的 skip 不算原生通过 |
| 核心 CLI 分发安装 | `ubuntu-24.04` | 3.12 | 独立环境/不同工作目录安装 wheel，执行已有安装 smoke 与离线核验；不冒充 3.13/3.14 安装消费者 |
| SDK 独立安装、文档消费者与 strict typing | controls 的 `core`、`ubuntu-24.04`、`macos-26`、`source-wheel` 四 profile | **全部 3.12** | 每档 SDK 均使用独立安装的 **core wheel**，不加载 native；三个 profile 在 Ubuntu 24.04，一个在 macOS 26；SOURCE 使用实际 sdist 中的 driver、文档和消费者 |
| 原生回归及安装链路 | `ubuntu-24.04`、`macos-26` | 3.12 | 单独的原生资格，精确 `nautilus-trader==1.231.0`；不因 SDK 在 core wheel 下成功就成立 |

四个 controls profile 不是四种不同平台；原生 host profile 中运行 SDK 也不让 SDK 获得引擎或研究执行权限。文档具名示例的实际执行、README 模板绑定、类型和拒绝回归均须保存本候选自己的记录。矩阵未承诺每段历史 Markdown shell 都由当前 CI 逐字运行，具体覆盖见 [SDK 验收范围](python-sdk.md#验收范围)。

runner 标签不是所有 CPU 架构、发行版或文件系统的认证。实际架构、解释器、依赖与 job 链接须保留在验收证据中；未在候选记录中验证的组合属于未验证。`py3-none-any` wheel 标签同样不表示所有操作系统均支持安全文件 IO。

文件存储依赖 POSIX directory fd、no-follow、regular-file 检查、hard link 与 fsync。原子目录发布只实现 Linux/macOS 的 no-replace 接口，缺少能力就明确失败。Windows、未验证的发行版/运行时、网络文件系统、云盘挂载、不同原生 Python 组合及上游源码编译不在上述资格范围。macOS 原生 wheel 还须满足其平台标签，不能把 macOS 15 的核心回归当作原生支持。

原子发布还依赖进程 libc/运行时导出对应入口：Linux 使用 `renameat2`，macOS 使用 `renameatx_np`；内核与文件系统也须支持无覆盖发布和目录同步。缺少入口会明确失败，不使用覆盖式 fallback。既有自动化补充复验中的一份 Alpine 配置在此检查失败；这不代表全部 musl 配置均已验证，也不提供所有 Linux 发行版或 glibc 版本下限保证。原记录及系统 checksum 说明见 [复验手册](alpha-reproduction.md)。

本轮维护者的项目执行、测试、构建、安装和类型检查全部在远端 GitHub Actions CPU 或另行授权的专用EC2参考环境进行；真实参与者案例可按既有合同留在其受支持远端环境。当前不要求 GPU，也没有 GPU 加速承诺。Colab 的运行时和磁盘可能回收，不构成额外受支持组合、长期托管或持久性保证。原始数据、CAS、attempt ledger 和导出包按 owner 的备份流程保存。

## 功能与模型边界

| 能力 | 既有范围及版本归属 |
| --- | --- |
| 数据导入 | 规范化 JSONL 的 snapshot/delta/trade；不是交易所原始 WebSocket 采集器。导入 accepted 不是回放许可或真实来源认证 |
| 声明 | v1 不可执行声明继续保持 `execution_ready=false`；v2 单独绑定受支持内置策略、数据、模型、估值与预算 |
| 回放 | 单流 EUR-USD、一次初始 snapshot、受支持完整序列与 receive-order 时钟；内置 post-only 限价买单、MARGIN/NETTING，无用户 Python 策略执行 |
| 估值与费用 | 最后观测 bid 的 USD marked PnL，不是平仓收益；没有退出深度、冲击或退出费用。列明费用模型独立复算，歧义时估值/claim 未知，不以一分钱容差放行 |
| 尝试预算 | 每个 protocol ID 的不可退款 attempt；失败与中断消费预算，不是跨协议的完整 trial family/exposure 账本 |
| 证据 | 按各自格式复算完整性/绑定/账务；离线 verifier 不重新执行 native 撮合，不自动认证作者、真实市场成交、确认集或全部历史尝试 |
| 公共 SDK | 仅 0.2 的 [SDK v1](contracts/python-sdk-v1.md)：五方法、七个公开名称，共用原应用服务；数据导入/检查、不可执行声明冻结/检查、受限 development 读取 |
| CLI 与内部接口 | 0.1 CLI 按原发行；0.2 CLI 按各自合同。内部 domain/application import 不进入 SDK 兼容保证；SDK 不提供 run、Job、maintenance 或确认暴露 |

0.2 的既有 CLI 能力索引如下，各项权限不互换：

- [场景执行](contracts/scenario-execution-v1.md)、[有限搜索计划](contracts/search-plan-v1.md)、[campaign 预算](contracts/campaign-budgets-v1.md)、[有范围 finding](contracts/search-findings-v1.md) 和 [可迁移搜索证据](contracts/search-evidence-v1.md)；条件压力 finding 不自动成为原 baseline 命题翻转。
- [一次确认访问](contracts/confirmation-access-v1.md) 使用独立 authority，不授权确认 evaluator，也不成为 SDK development-read 的 override。
- [缩减输入](contracts/reduction-input-v1.md)、[从首 snapshot 执行](contracts/reduction-execution-v1.md)、[局部缩减](contracts/reduction-search-v1.md)；保持/不保持/不可评价分开，不提供引擎 checkpoint、隐藏队列初态或全局最小性保证。
- [Job 重试与确认恢复](contracts/job-followups-v1.md)、[强取消与资源控制](contracts/job-controls-v1.md)、[资源报告](contracts/job-resources-v1.md)、[引用感知保留](contracts/dataset-retention-v1.md) 和 [有限故障恢复资格](contracts/dataset-fault-budget-v1.md)；依各自 CLI 执行，不是 SDK 方法。

这些 profile 均不承诺通用加密货币或任意 Python 策略执行、实时交易、任意恶意代码沙箱、完整引擎 checkpoint、HTTP/MCP/UI、生产性能或真实市场收益。EUR-USD 内置模型不会因通用 JSONL 导入或 wheel 标签而扩为任意资产执行。已接受的 SDK／接入工作见 [Sprint12 状态](planning/sprint-12-status.md)，执行信任和未启用能力见下文及 [冻结合同](contracts/execution-trust-v1.md)，不以未来规划提前背书。

回放硬上限仍为 8 MiB / 10,000 events；可执行协议最多 100 attempts，单次 native worker 最多 60 秒，具体原协议可更严格。worker wall budget 不覆盖导入、导出和全部验证总时长。campaign/Job 另有各自范围的控制，不放宽原协议预算；导入与 bundle 配额按各自合同。

## 信任与运行状态

下表是 [Execution trust v1](contracts/execution-trust-v1.md) 的支持状态摘要；M0/M1/M2 是文档标签，没有对应的 CLI/SDK mode selector，也不扩大上文 OS/Python/文件系统矩阵。

| 模式 | 当前状态 | 使用或启用边界 |
| --- | --- | --- |
| M0 TRUSTED_LOCAL／可信本地 | 当前支持边界，仅既有已资格内置 profile | owner、输入/存储根及祖先、解释器、依赖和宿主可信；只处理合法授权数据。同一可信 owner 在受支持远端主机通过 SSH 操作仍是 M0 |
| M1 RESTRICTED_SINGLE_HOST／受限单机隔离 | 内部参考已获**QUALIFIED_REFERENCE_ONLY**；**产品未集成／DISABLED** | S13-02先冻结[内部参考环境与限额](contracts/restricted-reference-v1.md)，[固定EC2 v3参考](security/ec2-reference-recovery-v3-evidence-2026-11-27.md)24PASS／累计45、独立只读readback CLOSED；[2026-11-19 GHA预检拒绝](security/restricted-reference-evidence-2026-11-19.md)是保留的历史结果，其“当前参考未获资格”表述于2026-11-27被取代（SUPERSEDED）。产品执行仍未接入，[owner接受](security/s13-02-owner-review.md)与独立安全复核另计；缺证据保持不可用，不自动退回 M0 执行不可信代码 |
| M2 HOSTED_UNSUPPORTED／不支持托管 | 不支持不可信托管任务、需要独立用户/租户权限边界的协作和多租户服务 | 尚无独立用户/租户身份、资源归属与权限、跨用户数据/秘密隔离、租户配额和服务运维资格；自托管、容器或单项 M1 负例通过不自动提供这些边界 |

当前 0.2 的可选 [Job controls](contracts/job-controls-v1.md) 在支持的平台上设置 worker CPU、单文件与 FD 限额，并以固定 monotonic deadline 控制入场和发布；未配置的历史 worker 不自动获得这些控制。owned scratch、进程组终止和 no-follow 回收处理的是其已声明生命周期，不是 hostile/escaped 进程 containment。同步校验、kernel IO、fsync 可能延迟物理停止或确认；未知停止、live lifetime 或路径替换时按原合同保留 scratch 和诊断。

这些控制未提供整树内存/PID、总磁盘/inode 或生产网络默认拒绝，也未清洗 worker 继承的宿主环境。RSS 与 cleanup 逻辑字节是有口径的 [观测](contracts/job-resources-v1.md)，不等于内存/存储配额；campaign 的 managed-payload 硬门也不是宿主磁盘配额。SDK 的原32次/180秒资格预算限制直接受监督的调用，不是 OS 进程树/网络隔离；Python 子进程、`-I`、测试 guard 或文件哈希都不能据此称为安全沙箱。

普通 development/SDK 入口拒绝 confirmation，独立确认访问遵循自己的合同；这些策略不能对宿主 owner 隐藏其文件。mode 标签、环境替换、取消或安全测试不更换原协议/Job/family 身份、不授予新预算；失败/中断/未知 reservation 不退款，真实重跑仍使用同一原协议新槽，已提交结果仅复核/ACK，不重复执行。缺少 OS/control/profile 或实际负例证据时保持 UNKNOWN／NOT_QUALIFIED，不把跳过、缺失观测或 AI 审阅记为安全通过。

`completed`、`claim_observation.eligible` 和 `satisfied` 分别描述执行结束、是否可评价及是否满足冻结阈值。incomplete、费用歧义、错误或预算终止不能变成研究通过。`reserved_unfinalized` 表示终态未知，不能解释为失败已确认或预算可退款。

## 兼容、升级与回退

SDK contract v1 的五方法、七名称、类型和错误按 [SDK 合同](contracts/python-sdk-v1.md) 与 [兼容合同](contracts/sdk-compatibility-v1.md) 维护；这不稳定所有内部 Python API。CLI、持久格式与领域语义分别版本化，兼容范围以对应发行/候选的实际回归为准；不以包版本号推断 loader 理解所有旧对象，也不承诺通用自动迁移。

输入中的封闭 schema 拒绝未知字段/版本，不静默删除字段以通过校验；声明的 bounded scalar `parameters` 是允许保留自定义键的开放位置。SDK 没有 receipt JSON ingest 或“忽略未来字段”选项。未知 receive 时间保留 `None`，不能补成事件时间或 0。存储 inspect 与研究绑定的区别见 [SDK 未知字段说明](python-sdk.md#未知字段参数与存储检查)。

1. 升级前停止对相关目录的写入，备份完整 catalog、CAS、registry、attempt ledger 与已导出 bundle，保留旧解释器环境和安装制品。
2. 将新版本装入独立环境；用原始导出包和新的独立工作目录验收。不要删除或重写旧 CAS 对象、旧协议、slot、outcome 或 bundle manifest。
3. 不支持旧格式时明确拒绝并保留原件。未来转换须有自己的合同，生成新对象和来源记录，不能原地重解释旧证据。
4. 回退使用保留的旧安装环境与匹配的完整备份；不混合新旧可变 catalog/ledger，也不假设旧版理解新格式。

本预览没有自动备份、通用迁移、任意跨版本恢复或真实断电认证。0.2 的显式 Job ACK/重试和特定 DatasetStore 恢复有各自范围，不构成通用续跑。导出目标已存在时不覆盖；发布后持久性未确认时先核验已有目标并保留诊断，再决定其合同允许的恢复路径。失败、中断和未知 reservation 不退款；真实重跑使用同一原协议的新槽，已提交结果不重复执行，原 5/8/11 槽、golden 和 PR94 不变。

## SDK 自助诊断与恢复

先保留包版本/来源、SDK contract、OS/Python、真实调用和完整原始错误，再按 [SDK 错误表](python-sdk.md#错误与明确恢复) 处理。不删除或重建根目录、不手工删 WAL/SHM、不修改协议预算来“修复”错误。损坏/缺件时先保存原件；已知合法来源到新 store 的特定恢复遵循 [故障合同](contracts/dataset-fault-budget-v1.md)，不复制或重置研究 ledger。

维护 BLOCKED、Job read conflict、研究 `reserved_unfinalized` 和普通 SDK 存储错误不是同一种状态。只读检查不会替你发起研究重试；维护 apply 的 PARTIAL/IO_UNCONFIRMED 不能报告 APPLIED。相关操作按各自 CLI 合同处理，不能从一个错误码推断另一个子系统的恢复权限。

### 已接受的baseline离线缺件诊断

S14-01a首切片已随[PR117](https://github.com/Darrenus/tickwitness/pull/117)接受：source09正常合并484，
其当前源码实际16/16 Engineering、focused128、transport91及Docs162/984通过，legacy REFUSED单独保留。
[baseline合同](contracts/baseline-evidence-diagnostics-v1.md)／[ADR0052](adr/0052-baseline-evidence-missing-object-diagnostics.md)
保留research_store_integrity_or_io_failure和exit3，仅对有效manifest声明CAS leaf真实ENOENT增加
reason=bundle_object_missing、role、排序roles及sha256。有效回执、格式、SDK及其他拒绝不变。
它不补件、下载、搜索其他store、engine、SQLite、reservation、replay或确认访问；不代表新release。

### 当前候选的inspect缺失上下文

S14-02a／#41按[检查合同](contracts/inspection-absence-context-v1.md)及
[ADR0053](adr/0053-inspection-absence-context.md)先实际冻结64cca6f，再实现已有两个inspect命令的诊断。
新head远端验收及owner接受仍PENDING。错误保留原research_evidence_not_found或dataset_not_found／exit4，
增加reason=inspection_evidence_not_found、command、requested_id和固定lookup；实际已知时才有resource_id。
缺依赖dataset的resource_id来自已验证protocol的真实get入参，构造失败不猜ID，不解析message。

F02这两个命令不是SDK v1的新方法，本身不改变infra或领域语义；下述Job质量companion单独记录。检查有效reservation但没有outcome仍成功
reserved_unfinalized、budget_consumed=true；CAS orphan不能证明未执行或预算可用，outcome CAS缺失仍完整性拒绝。
其他权限、IO、不安全或损坏按既有分类拒绝，没有新增repair、retry、退款、确认访问或重跑许可。
inspect-experiment允许已有SQLite mode=ro访问；其catalog WAL/SHM正常活动不等于绝无文件系统写入。
不要把baseline无SQLite profile套到这个命令，也不要删除live sidecar。原协议、用户ledger及已提交结果保持。

### Job journal只读竞态的质量companion

[实际失败／确定性RED](planning/s14-02a-job-journal-2026-11-28.md)与
[先冻结的修正合同](contracts/job-journal-unlinked-read-conflict-v1.md)单独追踪#119。
原macOS取消测试的inner异常信息缺失，不能宣称已确认其具体文件；真实COMMIT-after-open回归已证明可复现缺口。
候选只在fixed optional journal的readonly预检发现REG/nlink0且named实际ENOENT时返回原job_conflict／exit9，
不给SQLite观察或自动重试。原有限窗口内可以重新读取并完整校验；writer、mandatory、替换／alias／类型及其他IO仍拒绝。
不删journal、不重建catalog、不扩大期限或发起Job／研究重跑。修正head的完整GREEN／owner接受仍PENDING，
不能把原31PASS/3FAIL或其他source绿色当当前验收；M1及外部真人门保持关闭／PENDING。

## HTTP/MCP 入口需求与当前决定

项目路线图中已有 HTTP/MCP 的规划兴趣；它与可核验的“现有 CLI/SDK 阻塞了某个真实任务”是两类证据。截至本页更新，未提供这样的已核验案例记录，阻塞任务、替代成本和参与者确认仍为 **UNKNOWN / 证据不足**，不是已证明没有需求。当前决定是 **DEFER**，保留 S14 或以后条件性入口，本轮不实现。

本轮执行原S14的核心fallback：首8h已接受、S14-02a的8h已选择，原32h中余16h
（父项01余4h＋02余4h＋03原8h）未承诺，不叠加transport或虚构功能填满容量。
这些都是预测，不是实际工时；重新选择transport前仍需真实需求证据、独立范围和验收。

真实请求到来时，分别记录匿名请求者/角色、日期、具体任务及合法案例、当前工作流、CLI/SDK 替代及其实际阻碍、所需最小入口、原始来源/证据、参与和公开记录同意、投入/限制、评审决定及理由。无记录时不填虚构请求或成功数；规划偏好和维护者推测不改写成外部用户需求。普通文档更新也不授权自动向他人联系。

## 获取帮助

普通缺陷通过 [GitHub Issues](https://github.com/Darrenus/tickwitness/issues) 提交：版本/commit、OS/Python、相关 schema/engine ID、命令、退出码和可公开的最小合成复现。不要上传私有行情、策略、凭据或未经许可的完整证据包；安全问题按 [SECURITY](../SECURITY.md) 私密报告。

维护者按可用时间处理预览问题，不提供 24×7、付费 SLA、长期维护期限或修复日期保证。外部真人复验仍为 0 attempts / 0 successes / PENDING，#24 保持 OPEN，实际自有案例登记为空；[接入指南](user-onboarding.md) 将技术成功、真人参与、激活和 30 天复用分别评审。CI、AI 审阅和 owner 合并都不计作外部认证。
