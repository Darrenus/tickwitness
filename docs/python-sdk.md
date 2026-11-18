# Python SDK：从行情证据接入现有研究工程

首个稳定接口是 [SDK v1 子集](contracts/python-sdk-v1.md)，`SDK_CONTRACT_VERSION=1`，包版本仍是 **0.2.0.dev0 技术预览**。五个方法提供数据导入/检查、不可执行声明冻结/检查和受冻结预算限制的 development 读取，七个公开名称以合同为准。CLI 与 SDK 调用相同应用服务；研究执行、Job、维护和确认窗口暴露不在公共 SDK 范围。扩展先冻结合同、再独立验收；内部 import 路径、CLI 全部能力和包 GA 不属于这项兼容承诺。

## 安装与真实消费者

按 [接入指南](user-onboarding.md#3-取得同一份已验收包和匹配材料) 取得可信预期 hash、实际 wheel 和匹配 sdist。仅有相同版本号不够；wheel 不携带输入示例。将已核对的 core wheel 安装到独立环境，使用 `--no-index --no-deps`，不使用 editable 或源码 `PYTHONPATH`。本轮构建、安装和所有项目执行均在远端 GitHub Actions CPU，具体独立环境准备见 [现有 CI 安装步骤](../.github/workflows/engineering.yml)；无需 GPU 或 nautilus extra。

[真实消费者及输入](../examples/sdk/README.md)随 sdist 分发。将该目录复制到研究工程外的独立目录，以安装环境的 Python 和 `-I` 运行其具名命令模板。消费者只用公共 SDK 与标准库，封存已知输入和不执行的策略源码，读取有界 development 观察并输出确定性 capture 摘要；未知接收时间继续未知。摘要不是收益预测、回测或命题结论。

Python 声明范围为 3.12–3.14；六档核心源码回归与四档已安装消费者/strict-type 资格不同，后者目前均为 **3.12**，详见 [支持矩阵](support.md#按任务划分的环境矩阵)。不要由 wheel 标签或源码回归推断未验证平台支持。

## 在调用方使用

下面是本页唯一具名执行示例。调用方提供已有合法 `.jsonl` 的相对路径和可信绝对根；函数执行真实导入后返回重新检查得到的 receipt。它不自行选择机器路径、执行策略或隐藏错误。

<!-- sdk-example:import-and-inspect:v1 -->
```python
from pathlib import Path

from tickwitness.sdk import Client, ImportReceipt


def import_and_inspect(
    input: str, *, input_root: Path, store: Path, registry: Path
) -> ImportReceipt:
    client = Client(store=store, registry=registry)
    imported = client.import_events(input, input_root=input_root)
    return client.inspect_dataset(imported.dataset_id)
```
<!-- /sdk-example:import-and-inspect:v1 -->

返回值是 inspect 的 `ImportReceipt`，因此其 `created=false`；这不说明前一步 import 是否首次新增数据。需要区分首次导入时，保留导入自己的 receipt。`SDKError` 原样传播，调用方可以在边界记录其 `code`、`exit_code` 与 cause；本函数不 catch 后伪造空结果或自动重试。

构造只保存配置，不创建数据库、打开数据、导入引擎或执行策略。相对输入在指定 `input_root` 下由已有安全读取实现限额与无跟随打开；根及父目录仍是可信 owner 配置。非法事件在创建目标 store 前拒绝。显式重复导入不消耗研究槽，`created=false` 表示没有新增 Catalog 登记；不把它当成新研究证据或自动研究重试。

`freeze_protocol` 需要两个前向不交叠的数据集、JSON 请求和 Python 策略源码相对路径。源码仅解析和哈希，冻结声明不是执行授权。`read_protocol_data(protocol_id, limit=...)` 仅返回 development；limit 必须是真实整数 1..1000，且不超过原声明 max_events。confirmation 或任何非 development 请求在身份检查、根打开和数据读取之前拒绝。保留 `receive_time_ns=None`、报告未知值与 `replay_certified=false`，不以补值制造回放认证。

SDK 的 declaration-v1 不是 CLI `freeze-experiment` 的 executable-v2，两种 ID 不可互换，没有公共转换/run 桥。需要完整研究时先检查 [自有案例指南](user-onboarding.md) 的现有受限 CLI profile；通用 JSONL 导入不承诺任意资产或任意 Python 策略执行。

## 未知字段、参数与存储检查

“未知”需要按入口区别处理，精确规则见 [兼容合同](contracts/sdk-compatibility-v1.md)：

| 入口 | 现有行为与边界 |
| --- | --- |
| 规范化事件 | 不支持的版本、缺少/未知字段以 `invalid_data / 2` 拒绝；不先删除字段再接受，且不创建目标 store |
| 声明 request、claim、configuration、budget | 封闭字段集，未知/缺少键为 `invalid_protocol / 2`；不创建 registry 或发布协议。此前可能构造已有 DatasetStore 的只读实例，不能承诺全部 IO 前拒绝 |
| 声明 `parameters` | 开放但受限的 scalar map，合法自定义键和值原样保留并参与 protocol 身份；仅参数变化不改变 claim 身份。object/list 等不合法值拒绝；参数名 `execution_ready` 不修改顶层 false、冻结预算或权限 |
| Python 未知 keyword/签名误用 | 普通 `TypeError`，不静默丢弃参数，也不一概转成 SDKError |
| 已存储 dataset report | inspect 验证其 hash/canonical 存储闭包并保留 JSON 字段；这不等于重新认证规范化研究语义。研究绑定/读取另行 normalize 并比较完整 report，额外或不一致字段会拒绝 |
| 未知 receive 时间 | `None` 保留未知；不等于 0、event time、扩展键或回放许可 |

返回 dataclass 的字段、顺序和默认值按 SDK v1 合同；嵌套 JSON 是 detached 副本，不是“忽略未来字段”的兼容层。SDK 没有公共 receipt-JSON ingest/decoder，不通过删除返回字段制造 CLI 等价性，也不承诺任意新 schema 可被旧 loader 读取。

## 类型、错误与重试

从 `tickwitness.sdk` 导入的 ValidationLimits、ImportReceipt、ProtocolReceipt、DevelopmentRead 是已有应用类型。返回对象浅冻结，嵌套 JSON 是独立副本；修改副本不改变持久证据。序列化使用 dataclasses.asdict；tuple 编为 JSON 数组属于普通编码，不删去 `created` 或未知字段制造等价性。

SDKError 保留稳定 `code`、CLI 相容 `exit_code` 与原始 cause，`as_dict` 返回同形错误 JSON。详细映射见 [SDK 合同](contracts/python-sdk-v1.md)。身份格式错误有 SDK 专用 `invalid_sdk_argument / 2`；CLI 对应 argparse 用法错误，不能要求两者错误输出字节一致。未知 keyword 或其他编程错误不会被一概伪装成校验失败，ValidationLimits 值构造本身保留 ValueError 派生校验。

SDK 不自动重试。IO 或完整性拒绝后先检查原始错误和持久状态，按已有明确恢复规则操作；不通过重建 registry、修改协议或退款取得新研究权限。首版读取不能执行研究，所有现有 5/8/11 槽及已提交结果不变。

## 错误与明确恢复

保留完整错误、调用、版本/commit、OS/Python 和持久 ID；`message` 是诊断文字，不作为跨版本稳定解析协议。按稳定 `code` 和 `exit_code` 分流：

| SDKError code | exit_code | 支持的下一步 |
| --- | ---: | --- |
| `unsafe_input` | 2 | 检查相对路径、可信输入根、文件类型和限额；提供合法普通文件，不关闭 no-follow 或跟随 symlink 绕过 |
| `invalid_data` | 2 | 核对原 JSONL/schema/字段/数值/序列；保留原件及失败，按合同修正来源输入，不补时钟或忽略未知键 |
| `invalid_protocol` | 2 | 检查请求、开放参数值、分区、冻结限额和源码语法；不通过增加预算或改权限绕过拒绝 |
| `invalid_sdk_argument` | 2 | 传入正确的小写 64hex 身份；CLI 对应 argparse 用法错误，不要求错误文字/JSON 字节一致 |
| `dataset_not_found`、`protocol_not_found` | 4 | 检查原 receipt、匹配版本及真实 store/registry；不创建空根冒充原证据 |
| `confirmation_access_denied` | 5 | 保留阶段拒绝；普通 SDK 仅 development，不用原始文件旁路或 CLI 转换作解封办法 |
| `store_integrity_or_publication_failure`、`protocol_integrity_or_publication_failure` | 3 | 停止自动后续操作，保留原错误和已有字节；发布可能已发生，只读核验原身份/闭包，损坏原件不覆盖修复 |
| `io_failure` | 3 | 保存实际 cause/errno 和已观察状态，检查受支持环境、权限和存储；先确定提交是否存在，不能推断回滚或免费重跑 |

`TypeError`、未覆盖的编程错误以及 `ValidationLimits` 自身的 ValueError 派生校验与 SDKError 区别处理。修正调用不意味着已执行研究可重跑；SDK 不自动恢复、不退款。已知来源到新 store 的特定 DatasetStore 恢复、WAL/锁处理及 Job ACK/显式重试请走 [支持政策](support.md#sdk-自助诊断与恢复) 和各自 CLI 合同，不手工删除 WAL、清空根或重置原 ledger。

## 验收范围

本轮 [兼容与文档执行合同](contracts/sdk-compatibility-v1.md) 要求四个既有 controls profile 使用独立 core wheel：读取实际 guide 字节，提取唯一具名 Python 块，保存完整 source/hash，在新 owned 根和独立 cwd 中实际加载并调用 `import_and_inspect`。SOURCE 使用实际 sdist 的 driver、文档和示例。缺少、重复或错误语言块必须拒绝，不能只验证模板存在就声称运行通过。

既有完整消费者继续运行，SDK/CLI 对比完整首发、重复及只读回执、原始持久闭包、错误、未知时钟和限额。README 的唯一具名命令模板绑定到真实逻辑参数；外层实际使用 `-I/-B` guarded wrapper 与 runpy，记录真实 argv，**不声称占位 shell 逐字执行**。这是明确 allowlist，不是任意 Markdown/shell 执行器。

SDK/CLI 源码入口回归覆盖未知字段/版本拒绝、开放 scalar 参数保留、非法参数值拒绝，以及扩展报告的 inspect/研究绑定区别。安装后复用现有负例批次验证事件未知键、声明四层未知键、非法参数值及开放参数，并通过两个代表性 CLI 拒绝比较完整错误；不声称安装后批次执行了版本或扩展报告用例。非法事件/协议分别验证各自发布边界，不改原 domain 规则。下游 strict mypy 读取实际安装包和 `py.typed`；既有正例与本示例进入正向类型检查，负例精确匹配三条错误且不执行。

资格共用原 functional28/总32 次直接监督调用、四个保留类型调用、单次普通等待最多30秒及同一180秒 deadline，不增加 native/研究槽。新 SDK 记录与旧 controls/retention/fault 分开，三个旧树只做前后哈希保护。保留原17 checks 和 timeout；本候选实际执行、四档新 SDK 功能/类型记录及其审计通过后才回填结果，不继承旧绿勾，也不把旧树重复称作16份新 FULL DATA 审计。

本例是自动化集成资格，不是外部真人使用。外部真人仍0 attempts/0 successes/PENDING，#24 OPEN；[自有案例流程](user-onboarding.md)将技术接入、CLI完整研究、激活及30天复用分别记录，[实际案例登记](planning/s12-02-recruitment-gap.md)为空。HTTP/MCP 的规划兴趣与尚未提供的已核验阻塞任务分开，当前 [入口决定为 DEFER](support.md#httpmcp-入口需求与当前决定)，保留 S14 或以后条件门。原 S12-03 8h / S12 总34h与持续质量容量不变，没有新 release、GPU、采用或收益声明。
