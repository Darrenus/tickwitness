# JSONL 数据证据导入

状态：S02-01/S02-02 首条工程链路，2026-10-25。当前支持一种明确的规范化JSONL协议、安全导入、不可变内容存储和完整性核验。策略回放、反例搜索、时点查询和最终研究判定将在后续Sprint交付。

## 在本地运行

按[开发入口](development.md)安装锁定环境后，运行：

```sh
DATASET_ID=$(uv run --locked tickwitness import-events normalized-events-valid.jsonl --input-root examples --store ./runtime/datasets --id-only)
uv run --locked tickwitness inspect-dataset "$DATASET_ID" --store ./runtime/datasets
uv run --locked tickwitness import-events normalized-events-valid.jsonl --input-root examples --store ./runtime/datasets
```

第一次导入返回dataset ID；inspection会读取并核验整个证据引用闭包。再次导入相同字节、相同规范化结果与报告时，ID相同且`created=false`，不会产生另一条catalog记录。默认输出是JSON；`--id-only`仅用于shell串接。identity不包含本机绝对文件路径、运行时刻或随机ID。

样例是本项目原创合成数据，没有连接真实交易所。它的首条接收时间刻意为`null`；系统保留未知，`unknown_receive_count=1`，不会以事件时间代填接收时间。

缺口样例可以单独导入：

```sh
uv run --locked tickwitness import-events normalized-events-gap.jsonl --input-root examples --store ./runtime/datasets
```

其第2条更新跳过必要序列，之后新snapshot建立新epoch。报告仍为`quality_status=quarantined`，缺失历史没有被修复。导入成功表示证据已完整封存，不能据此认为缺口期间可可信回放。

## 支持的协议与边界

完整字段见[规范化事件v1合同](contracts/normalized-events-v1.md)。支持snapshot、delta和trade，使用有界int64 ticks/lots、独立事件/接收时间、捕获顺序与会话身份。价格/数量、时间和序列不接受浮点或bool；未知字段、重复JSON键、非UTF8和超预算输入会被拒绝。

v1采用严格非重叠的规范化增量序列政策；它不是Binance等交易所原始WebSocket解码器。真实来源需要独立的协议adapter与原始证据映射。`accepted`只表示列明的结构与序列预检通过；报告恒有`replay_certified=false`、`clock_binding=unbound`，完整盘口状态和真实时钟尚未认证。

默认上限：8MiB原始字节、100000条记录、每条65536字节、每侧1000档。`--max-bytes`和`--max-records`可由本地owner显式调整；内存处理受配置预算约束。Parquet、流式大文件与采集器按后续验收门扩展，当前不发布吞吐或查询性能数字。

## 导入与提交边界

1. 在显式`--input-root`下按目录描述符打开相对`.jsonl`路径，每层禁止跟随symlink，拒绝目录/FIFO等非普通文件，并限制读取字节。
2. 在内存预算内验证/规范化全部记录；解析失败时不创建目标仓库或半份dataset。
3. 原始字节、规范化JSONL与质量报告分别写入SHA-256 CAS，校验并持久化；确定性manifest绑定其hash、size与受限相对引用。
4. 所有对象和manifest核验完成后，SQLite事务才登记sealed catalog引用。进程中断可能留下未引用对象，但不会把它们列成可用dataset；重试使用同一内容身份。
5. inspection重新核对catalog、schema、manifest和每个对象的hash/尺寸。篡改失败；它不是盈利、真实成交或数据来源真实性认证。

文件系统和SQLite没有跨两者的ACID事务，本实现采用先持久化不可变对象、后提交catalog的顺序。当前没有自动回收孤立对象；不能手工删除仍被manifest引用的文件。跨进程作业恢复、备份工具与自动GC仍属于后续工作。

## 信任模型与错误

支持POSIX本地环境。输入根及其上级目录、store根为owner的可信配置；根下相对输入路径使用no-follow操作。store中的symlink、特殊文件、异常catalog/schema和不合法内容引用会被拒绝。此机制不提供恶意宿主owner并发替换目录的安全沙箱。

`inspect-dataset`使用已有store模式；错误ID、缺失store或查询不存在的dataset不会创建新的catalog。任何外部策略代码都未在这条链路执行。原始数据、manifest与catalog不应提交public仓库；`runtime/`已被忽略。

| 退出码 | 语义 |
| --- | --- |
| 0 | 导入/inspection成功；质量仍以报告为准 |
| 2 | 不安全路径、非法格式或预算失败；CLI参数语法错误也为2 |
| 3 | 发布、完整性、存储或I/O失败 |
| 4 | store或dataset不存在 |

应用错误以stderr JSON输出；命令行参数语法错误由argparse报告。当前由实际临时文件系统/SQLite测试及独立wheel smoke验证这些路径，尚未做真实断电或完整安全审计。
