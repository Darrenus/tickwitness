# 自有案例接入：从准备到真实激活

更新：2026-11-18，Asia/Singapore。本指南执行已冻结的 [接入证据规则](contracts/onboarding-evidence-v1.md) 与 [ADR0042](adr/0042-manual-own-case-onboarding-evidence.md)，面向参与者和陪同维护者。当前可核验的真实外部自有案例记录为空，外部真人复验仍为 **0 attempts / 0 successes / PENDING**，[#24](https://github.com/Darrenus/tickwitness/issues/24) 保持 OPEN。材料准备和自动化消费者通过，不增加真人激活数。

先阅读本页并选择支持的路线，再安排实际运行。案例记录使用 [空白模板](templates/onboarding-case-v1.md)，判断方式见 [评审示例](templates/onboarding-review-examples.md)；当前缺少的证据和下一项依赖见 [招募缺口记录](planning/s12-02-recruitment-gap.md)。模板与示例均不是已经发生的案例。

## 1. 先确定本次要完成什么

| 路线 | 可以完成的工作 | 不能据此宣称的结果 |
| --- | --- | --- |
| SDK 集成准备 | 将合法输入接入现有研究工程，封存数据和声明，读取受限 development 观察并得到 capture 摘要 | 完整研究执行、命题评价、自有研究激活或收益验证 |
| 支持范围内的 CLI 自有研究 | 独立冻结可执行协议，完成基线、声明约束、执行及有效完整结果，并保留可核验产物 | 任意资产/策略支持、完整历史认证或现实获利保证 |
| 原 PR94 技术复验 | 使用其原 kit、可信 pin 和 runner 核验指定合成证据及拒绝路径 | 自有研究激活、真实参与者身份认证或自动通过 #24 |

SDK 的 `freeze_protocol` 生成不可执行的 declaration-v1；CLI 的 `freeze-experiment` 使用独立的 [ExecutableProtocol v2](contracts/executable-protocol-v2.md)。两种 ID 和 loader 不可互换，目前没有公共 SDK 转换或 run 桥接接口。先完成 SDK 集成的人，若要进行完整研究，仍须另行满足 CLI 路线的输入和协议合同。

首次接入可只完成 SDK 准备，也可以在支持范围内直接选择 CLI。完整研究若暂不支持，记录具体能力缺口和未执行步骤；不要修改资产名称、补造时钟或用官方样例替代其自有案例来达到激活条件。

## 2. 运行前的案例约定

参与者与维护者共同完成模板中的 intake 部分。没有真实参与者时保持实际案例清单为空，不先创建一个看似已招募的人。

1. 确认参与者近期自己的研究问题、目前基线与工具、希望据此作出的决定，以及本次任务是否符合现有支持范围。记录原话、参与者估计与维护者解释的区别。
2. 分别记录参与、保存记录、后续联系和公开引用的同意。不同意公开材料不妨碍在其环境运行；输入来源、使用权和再分发许可也分别记录。软件 Apache-2.0 许可不授予第三方行情或策略的公开权利。
3. 记录实际操作者及每位人类、AI、自动化助手的工作。`external_user` 自报标签或目录名称不能证明真人独立参与；维护者代操作也不能记成参与者自行完成。
4. 约定可信输入根、独立持久输出根、远端 CPU 环境、固定包与模型版本及预算。数据可以一直留在参与者受支持的远端环境。输入和输出根使用清楚的绝对路径，避免覆盖源码、样例或已有证据。
5. 在评估前说明“有限帮助”的判定依据，并记录实际帮助次数、工作和时间；不在结果出来后另造数字门槛。需要长期定制或维护者持续代操作，应保留为集成成本证据。

默认不收集遥测，不录音、不公开身份或原始输入。联系方式、同意原件、专有代码、真实运行原件留在 owner 控制的私有存储；命名为 private 的公共目录并不私密。公共仓库只保存空白材料和经许可的匿名摘要。哈希、匿名 ID、脱敏或软件许可都不替代发布授权。提交采用记录不是产品运行的前提，参与者可以退出。

## 3. 取得同一份已验收包和匹配材料

SDK v1 已由 owner 合并 [PR110](https://github.com/Darrenus/tickwitness/pull/110) 接受，包版本仍为 **0.2.0.dev0 技术预览**。以下固定实际已验收的 source-wheel 制品，不表示发布到 PyPI 或产生新的 Release。

| 身份 | 固定值 |
| --- | --- |
| 已接受的 PR head | `7ea5bce8edefda4f46deaf4981fc31a3d88d4f48` |
| 实际 CI checkout / 包 manifest 的 source_commit | `b6da41bc3c1dd1728b23a06e4e397007ca3bee44` |
| Owner 接受的真实 merge | `94fc08a98d3237077cfa79065d18c0daf91bcd88`，2026-11-16T10:38:23Z |
| 远端资格运行 | [Engineering 43812145589](https://github.com/Darrenus/tickwitness/actions/runs/43812145589) |
| 下载制品 | [artifact 14201226410](https://github.com/Darrenus/tickwitness/actions/runs/43812145589/artifacts/14201226410)，`job-controls-packages-source-wheel-b6da41bc3c1dd1728b23a06e4e397007ca3bee44` |
| 下载 ZIP 的 SHA-256 | `67142c00c1e707806a12ba52bafdd921719c38c424f65ec3d588d292eb9645e2` |
| `tickwitness-0.2.0.dev0-py3-none-any.whl` 的 SHA-256 | `5af8fca8eb11d9a73b9cecb57077e148658d385f31c2efc579394468341267d5` |
| `tickwitness-0.2.0.dev0.tar.gz` 的 SHA-256 | `cbce34a02f9e009cd0eac3fcdb1a21c404d40ed7814563129c940a20959d0c7a` |
| `preview-manifest.json` 的 SHA-256 | `5ef09321cce853eee23840dd62a93d871064d927f0ab11b8f8908064af9054e4` |

这些是不同身份：不能把 PR head、临时 CI merge checkout、owner merge 和分发文件哈希写成同一个值。制品中的 `SHA256SUMS` 与 `preview-manifest.json` 固定 wheel/sdist 的名称、大小和哈希；manifest 的 `published`、`signed`、`source_rebuild_verified`、`test_results_included` 均为 false，原验收另见 [Sprint12 状态](planning/sprint-12-status.md)。包名相同不代表文件相同。

取得材料时按下列顺序核对并记入案例：

1. 从上面的实际 run/artifact 取得 ZIP，先核对 ZIP 哈希，再使用其分发文件；保存取得日期和来源。
2. 对照可信预期值、制品内 `SHA256SUMS` 和 manifest，分别核对 wheel、sdist、manifest。哈希仅标识内容，不认证作者或人类参与。
3. 从同一 sdist 取得 `examples/sdk/` 及匹配文档，不从移动的 main 或其他 0.2.0.dev0 构建拼接输入、脚本或说明。安装 wheel 不会自动提供示例目录。
4. 按 [已接受 SDK 安装说明](python-sdk.md#安装与真实消费者) 在独立远端环境安装这一个已核对的 wheel，再按 [消费者说明](../examples/sdk/README.md) 使用安装环境的 Python 和 `-I`。不使用 editable、源码 `PYTHONPATH` 或内部模块作为公共 SDK 集成入口。

2026-11-18 的实际 artifact 元数据为 `expired=false`，到期时间是 2026-12-16T05:47:37Z；这不是永久下载承诺。GitHub 下载可能要求登录。制品已过期或无权取得时，请维护者转交保留的相同字节和独立确认的 checksum；无法核对就停止安装并记录缺件，不用一个同名新包静默替换。

SDK 准备不需要 GPU 或 nautilus extra。优先采用已验收的远端 Ubuntu 24.04 / Python 3.12；其他 Python/OS/原生组合以该候选真实 CI 和各合同为准，`py3-none-any` 不认证任意文件系统。本轮维护者的全部项目执行与测试继续使用远端 GitHub Actions CPU，不在 owner 个人电脑运行；未来实际案例可按合同留在参与者受支持的远端环境，并如实记录。旧 [0.1 安装入口](quickstart.md) 与 [0.1 支持页](support.md) 记录原发行边界，不是本次 0.2 完整操作指南。

## 4. SDK 集成准备：保留真实输入的边界

先使用同包的 [独立消费者和输入](../examples/sdk/README.md) 确认安装与调用方式；官方样例完成只记为样例完成。随后若参与者同意接入自己的数据，在其私有工作区按 [规范化事件合同](contracts/normalized-events-v1.md) 和 [声明合同](contracts/frozen-protocol-v1.md) 准备输入，并保留原始来源、合法使用依据和转换方式。

消费者需要 `development.jsonl`、`confirmation.jsonl`、`request.json`、`strategy.py`。使用自有输入时记录其真实版本，不将替换后的文件仍称为官方原件。两个数据分区必须满足现有前向不交叠合同；策略源码仅解析和哈希，不执行。正式调用只使用 [SDK v1 的五个方法](contracts/python-sdk-v1.md#exact-public-signatures)，错误和返回类型沿用既有合同。

保存完整输出、真实退出码、脚本修订、数据/声明 ID、`created`、`total_records`、`truncated` 和未知时间。`receive_time_ns=None` 保持未知，不以 event time 代填；一次 `read_protocol_data` 必须同时遵守原声明 `max_events` 和接口 limit。confirmation 请求在 IO 前拒绝，不作为继续研究的解封办法。

这一阶段可以记录 `technical_attempt=SUCCESS`，但 capture 摘要的 `research_claim_evaluated=false` 仍成立。数据 accepted、声明封存、重复调用 `created=false` 或消费者成功，均不认证可回放时钟、研究结果或外部身份；激活评审仍需完整研究证据。

## 5. CLI 自有研究：只走已经支持的执行合同

先与参与者确认其问题确实能在现有受限模型中表达。当前可执行基线固定 **EUR-USD、内置 `single_limit_buy_v1`、receive-order 时钟和 pinned `nautilus-trader==1.231.0`**；不是通用加密货币回放器，也不执行任意用户 Python 策略。原生环境另须满足其真实远端资格，SDK core 环境安装成功不等于原生环境已就绪。

这里复用现有命令及其参数说明，不新增未经执行验收的拼接脚本。参与者先选择要回答的问题，再按对应合同运行；官方合成输入只用于熟悉入口，不能算作其自有研究。

| 顺序 | 既有入口和材料 | 运行前或产出时要记录的事实 |
| --- | --- | --- |
| 输入资格 | [Replay v1 预检](contracts/replay-v1.md#3-native-import-之前的预检) 与 [v2 协议](contracts/executable-protocol-v2.md) | 单流、初始 snapshot、完整序列与盘口、已知非递减 receive 时间、资产/模型与资源限额；不满足就停止，不排序、补包或改名绕过 |
| 冻结与基线 | [既有 freeze/replay/inspect 链路](evidence-workflow.md#在空工作目录跑完整链路)：`freeze-experiment`、`replay-protocol`、`inspect-run` | 自有数据、原主张/基线、真实 v2 ID、首次执行前冻结的 budget、原 ledger 和实际 run/attempt ID；使用本页固定的 0.2 包及匹配输入，不跟随该历史指南的旧发行安装链接 |
| 声明压力范围 | [Assumption/Scenario](contracts/assumption-scenario-v1.md)、[场景执行](contracts/scenario-execution-v1.md) 与 [SearchPlan](contracts/search-plan-v1.md#存储与-cli) | 真实 capture anchor、参数范围及依据、有限候选 journal；`COUNTERFACTUAL_STRESS` 与未校准状态不改称观测相容或测得延迟 |
| 有界搜索 | [Campaign Budgets](contracts/campaign-budgets-v1.md#cli)：`run-bounded-search-plan`、`inspect-bounded-search-campaign` | 原共同槽、campaign 时间/存储/评估上限、真实入场和停止原因；不要用旧 `run-search-plan` 冒充总资源硬限额入口 |
| 形成范围明确的结果 | [Search Findings](contracts/search-findings-v1.md#cli-与读取边界)：`freeze-search-finding-protocol`、`evaluate-search-findings` | 实际 authority/plan/report 身份、完整性、已评价集合和未评价后缀；条件压力谓词不是 baseline 原主张翻转 |
| 交接与核验 | [Search Evidence](contracts/search-evidence-v1.md#cli-与失败处理)：`export-search-evidence`、`verify-search-evidence` | 显式预期 report/bundle ID、全新导出目标、取得来源、独立核验记录和权限范围；核验不重新执行 native，也不认证作者或完整历史 |

只需要基线结果的案例可使用其既有 [baseline 导出与核验合同](contracts/evidence-bundle-v1.md)，不能把 scenario 或 search 结果塞入旧 baseline 格式。是否完成了参与者自己的研究，还要检查其事先声明的约束和预期问题；不是表中命令退出 0 就自动激活。

每个新合法案例在首次执行前冻结自己的 **原始** 可执行协议与预算；该案例后续 baseline、scenario、search、reduction 和真实重试继续共用同一原 authority/ledger。已提交结果不重复执行，失败、超时、中断及未决 reservation 不退款；预算用尽即停止。不得复制协议到空 ledger、重建 registry、换名字或修改预算来规避已经消费的额度。原 5/8/11 槽资格、golden 和 PR94 不变。

本次 SDK/onboarding 接入没有授权 confirmation 研究执行。不要把独立确认访问能力当作本流程的默认步骤，也不从 development 入口绕过其拒绝。

## 6. 实际失败、协助和结果都要留下

每次尝试开始、停止时在私有案例记录中保存日期/时区、实际环境与包身份、精确命令或 SDK 程序修订、原预算及持久 ID、stdout/stderr、退出码和未执行步骤。无法安装或启动时保留原始日志，不需要先生成一个“成功 submission”。收到别人返回的材料先保留原件，不在 owner 本机执行回传 harness。

遇到错误先停止后续派发，保留失败或未知状态并按已有只读 inspect/明确恢复合同检查。发布报错可能已有完整提交，reserve 报错可能已经占槽，不能据此认定“没执行，所以免费再来一次”。任何真实新执行都需要原协议新槽；SDK 不自动重试，显式重复导入也不是研究重试。

退出 0 仅说明当前命令完成。研究结果需独立检查 integrity、completeness、eligibility 和报告范围：完整的有范围未发现可如实交付，合法证据不足可按其合同记录；进程崩溃、损坏、未知终态和 incomplete 不能改称有效的“预算内未发现”。`FINAL`、hash 一致或 verifier 成功也不认证真人、市场来源或现实盈利。

用户主动操作时间、计算等待时间、维护者协助时间分别记录，并标明实测、参与者估计或 UNKNOWN。维护者/AI/自动化完成了输入转换、适配编写、排错、报告解释还是代操作，应逐项写清。未知时间不是 0，持续定制不是自助完成；失败材料不删除后只交成功截图。

## 7. 人工评审、研究决定和复用观察

实际返回后按 [模板](templates/onboarding-case-v1.md) 和 [评审示例](templates/onboarding-review-examples.md) 逐维评审，记录真人 reviewer、日期及依据。参与归属、技术尝试、自有案例适配、激活、研究决定、复用互相独立，不能只填一个 success。

- 真人参与、同意、操作归属或完整结果证据不足时，维持 `PENDING / NEEDS_EVIDENCE`。已核实外部真人的安装失败可以是真实尝试，但不是激活；仅 SDK 成功也不能升级。
- 激活按 [原指标定义](product/discovery-and-adoption.md#6-采用漏斗与指标字典)：外部用户自己的研究完成基线、声明约束并获得有效完整结果。结果不必找到反例；raw crash 或未完成状态也不会因为标签变更而满足条件。
- 研究决定由参与者确认，可以是修正、补采、继续、停止或有具体证据的“没有改变”。维护者解释和软件生成建议分开保存。价值实现另需独立复现和该确认决定。
- 只有真实评审合格的激活日期才启动其 30 天窗口。参与者自发完成第二个不同研究时记录真实日期、任务及发起依据；同例重跑、owner 代跑、演示重复或未来意向均不计复用。第 5 天复用可以记事件，但观察窗口仍未满。
- 汇总保留分母、窗口、来源和缺失值。没有激活日期就没有可计算复用率；不从 PR 合并日、首次 SDK 安装或第一次演示开始计时。

更正追加日期、理由与证据，保留先前失败和未知记录。未获公开许可的细节不随评审结论提交 public repo。

## 8. 暂无参与者时的交接

当前按原 S12-02 验收的招募缺口路径交付，实际案例清单保持为空；没有可核验记录不等于无人联系、无人回复或不存在需求。触达次数、回复、联系耗时和意向在没有证据时均为 UNKNOWN，具体来源见 [当前缺口快照](planning/s12-02-recruitment-gap.md)。

下一项外部依赖是 owner 联系参与者，并取得其同意后的真实案例安排或实际回传。本文可以交给对方，但它本身不授权向他人发送邮件/消息。收到材料后再保存原件、确认参与和操作归属、按本页分流并安排远端运行；不因标注 `external_user`、CI/Claude 回传或 owner 合并而增加计数。

PR94 技术复验继续使用 [原转交说明](alpha-reproduction.md) 及原 kit/archive/wheel pins，旧归档和自动化记录不替换、不改角色。`scripts/reproduce_alpha.py` 的自报提交不自动更新真人门；#24 的 0/0/PENDING、S12 自有案例激活和长期复用分别验收。

本页只覆盖 S12-02 的案例接入操作和证据交接。原 14h / S12 总 34h 与持续质量容量不变，不声明实际工时；S12-03 的 8h 支持矩阵、自助诊断和 SDK 契约回归独立推进。GPU 延后，HTTP 仍为 S14 或以后条件性能力，没有新发行、GA、采用或收益声明。
