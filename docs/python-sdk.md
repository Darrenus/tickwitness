# Python SDK：从行情证据接入现有研究工程

首个稳定接口是 [SDK v1子集](contracts/python-sdk-v1.md)，包版本仍是0.2.0.dev0技术预览。它提供数据导入/检查、声明冻结/检查和受冻结预算限制的development读取。CLI与SDK调用相同应用服务；研究执行、Job、维护和确认窗口暴露不在这次公共SDK范围。未来接口扩展先冻结合同，再独立验收，不通过访问内部模块获得兼容保证。

## 安装与真实消费者

在远端Linux CPU或GitHub Actions环境构建候选后，将实际wheel安装到独立环境。无需GPU或nautilus extra；不要用editable安装验证消费者，也不要将源码根加入PYTHONPATH。

```sh
uv venv /tmp/tw-sdk --python 3.12
uv pip install --python /tmp/tw-sdk/bin/python --no-index --no-deps dist/*.whl
```

[真实消费者及输入](../examples/sdk/README.md)随sdist分发。将该目录复制到研究工程外的独立目录，以安装环境的Python和`-I`运行。该消费者仅导入公共SDK与标准库：它封存已知输入与不执行的策略源码，读取冻结development观察，向下游输出确定性的capture摘要，并保留未知接收时间。摘要不是收益预测、策略回测或命题结论。CI使用两份全新的等价store/registry分别运行SDK与CLI，比较完整首发、重复和只读结果。

## 在调用方使用

```python
from pathlib import Path

from tickwitness.sdk import Client, SDKError

client = Client(store=Path("/work/evidence"), registry=Path("/work/declarations"))
try:
    imported = client.import_events("events.jsonl", input_root=Path("/work/inputs"))
    inspected = client.inspect_dataset(imported.dataset_id)
    print(inspected.dataset_id, inspected.report)
except SDKError as error:
    print(error.as_dict(), error.exit_code)
    raise
```

构造只保存配置，不创建数据库、打开数据、导入引擎或执行策略。相对输入在指定input_root下由已有安全读取实现限额与无跟随打开；根及父目录仍是可信owner配置。数据校验失败发生在目标创建前。显式重复导入不消耗研究槽，created=false表示没有新增Catalog登记；不把它当成新证据或自动研究重试。

`freeze_protocol`需要两个前向不交叠的数据集、JSON请求和Python策略源码相对路径。源码仅解析和哈希，冻结声明不是执行授权。`read_protocol_data(protocol_id, limit=...)`仅返回development；limit必须是真实整数1..1000，且不超过原声明max_events。confirmation或任何非development请求在身份检查、根打开和数据读取之前拒绝。保留receive_time_ns=None、报告中的未知值与replay_certified=false；不要给缺失时间补值或把已封存当作可回放认证。

## 类型、错误与重试

从`tickwitness.sdk`导入的ValidationLimits、ImportReceipt、ProtocolReceipt、DevelopmentRead是已有应用类型。返回对象浅冻结，嵌套JSON是独立副本；可以在调用方修改副本，不能因此改变持久证据。需要序列化时使用dataclasses.asdict；tuple到JSON数组属于编码，不删去created或未知字段制造等价性。

SDKError保留稳定code、CLI相容exit_code和原始cause，as_dict返回相同错误JSON外形。详细映射见 [合同](contracts/python-sdk-v1.md)。身份字符串格式错误有SDK适配器专用invalid_sdk_argument/2；CLI对应argparse用法错误，不能要求两者的错误输出字节一致。未知关键字或其他编程错误不会被一概伪装成数据校验失败。ValidationLimits值构造本身保留ValueError派生校验。

SDK不自动重试。IO或完整性拒绝后先检查原始错误和持久状态，按已有明确恢复规则操作；不通过重建registry、修改协议或退款取得新研究权限。首版读取不能执行研究，所有现有5/8/11槽及已提交结果不变。

## 验收范围

CI在四个既有controls环境中通过独立安装core wheel运行消费者，SOURCE环境使用实际sdist内的脚本和示例。新SDK制品与旧controls/retention/fault分开，三个旧记录树只做前后哈希比较。下游strict mypy读取实际安装包与py.typed，正例通过，负例需要匹配特定行/错误码，负例文件不执行。原checks数量和超时保留。新的资格以本候选实际CI和完整制品审计为准，不继承旧候选绿色状态。

本例是自动化集成资格，不是外部真人使用。外部真人仍0attempts/0successes/PENDING；S12-02的[自有案例接入流程](user-onboarding.md)将SDK技术接入、CLI完整研究、激活及30天复用分别记录，[当前实际案例登记](planning/s12-02-recruitment-gap.md)为空。更完整的支持矩阵、自助文档与契约回归继续按原S12-03计划推进。HTTP仍条件性S14或以后；没有新release、GPU、采用或收益声明。
