# 冻结研究协议：本地可执行流程

本批交付声明冻结、实际数据/源码绑定、不可变登记、开发集读取与确认集拒绝。冻结文档始终为 `execution_ready=false`；它记录可核验的输入和命题，还没有运行策略、计算收益或给出研究判定。

领域 schema 与身份规则见 [Frozen Protocol v1](contracts/frozen-protocol-v1.md)，数据预检边界见[数据导入](data-import.md)。以下仅用仓库自有合成数据，未连接交易所。

## 从数据到冻结声明

先按[开发入口](development.md)安装，以下命令从仓库根目录运行。`TW_DEV` 等是当前 shell 中的示例变量，不包含真实策略或私有凭据。

```sh
TW_DEV=$(uv run --locked tickwitness import-events normalized-events-valid.jsonl --input-root examples --store .local/data --id-only)
TW_CONFIRM=$(uv run --locked tickwitness import-events normalized-events-confirmation.jsonl --input-root examples --store .local/data --id-only)
TW_PROTOCOL=$(uv run --locked tickwitness freeze-protocol research-request.json --input-root examples --strategy-source research-strategy.py --development-dataset "$TW_DEV" --confirmation-dataset "$TW_CONFIRM" --store .local/data --registry .local/protocols --id-only)
uv run --locked tickwitness inspect-protocol "$TW_PROTOCOL" --store .local/data --registry .local/protocols
uv run --locked tickwitness read-protocol-data "$TW_PROTOCOL" --limit 2 --store .local/data --registry .local/protocols
```

不加 `--id-only` 的 freeze 返回 `protocol_id`、`claim_revision_id`、`created` 与完整 `document`。相同输入重复登记返回同一 ID 且 `created=false`。修改参数、费用模型或策略源码会产生新 protocol ID，原协议不会覆盖；修改 claim 的规范化内容还会产生新 claim revision ID。没有执行记录时不生成虚构的 trial。

`read-protocol-data` 默认 `--split development`，最多返回 `--limit` 条按 capture order 保留的 observation，附带 `total_records` 与 `truncated`。limit 必须为 1..1000，且不超过本协议 `max_events`。这只是**单次读取限制**，还不是跨请求预算计数或执行资源控制。

## 验证和提交边界

应用层冻结前依次检查：

1. request 为有界严格 JSON，源码为 1..256 KiB UTF-8 Python 3.12 语法；源码仅解析和哈希，**不 import 或执行**。Python 语法合法不代表未来运行安全，依赖和环境指纹尚未绑定。
2. 两个 dataset 均实际存在、manifest 与 raw/normalized/report 的完整性闭合，format 为 normalized-events-v1；重新运行预检并逐字节比较规范化数据，逐字段比较报告，且均为 `accepted`。不能用自洽哈希包裹一份伪造的质量报告。
3. 两分区具有完全相同的 `(source, instrument, session)` stream 集合；每个 stream 的 development 最大 capture_seq 严格小于 confirmation 最小值。book的snapshot视为单点sequence、delta视为闭区间，development最大末序列必须小于confirmation最小首序列；同stream重复trade_id无论时间/数量是否修改均拒绝。用这些稳定来源身份检查交叠，不能靠修改时间戳、capture元数据或市场payload把同一来源事件变成独立样本。
4. 验证全部通过后才创建 registry，先写并核验策略源码 CAS，再以协议文件的原子提交作为发布点；失败可能留下未引用源码对象，不能出现可读取的半份协议。

这个严格的初版分区合同只接受同采集 session 内的向前分区，需要每份输入自身满足 snapshot/sequence 预检。它不推断跨 session、跨交易所的经济事件相等，不认证 UTC、因果时钟、完整盘口或样本统计独立性。双边都 `accepted` 也不等于 `replay_certified`；目前 clock policy 只能为 `capture_order_unbound_v1`。

registry 使用独立可信 owner 根目录、内容寻址源码与协议文件，所有相对 artifact 路径拒绝 symlink 和非普通文件，读取核验 digest。协议入口通过 application ports 操作，domain 不依赖文件系统、SQLite 或第三方引擎。数据与协议存储不是同一事务：先封存 dataset，再登记引用它的协议，后续每次 inspect 重新核验引用完整性。

## 确认集的访问政策

```sh
uv run --locked tickwitness read-protocol-data "$TW_PROTOCOL" --split confirmation --store .local/data --registry .local/protocols
```

此命令以退出码 **5** 拒绝，stderr 为 `confirmation_access_denied`，stdout 无 observation。拒绝发生在构造或读取 repository **之前**；即使传入不存在的路径也不创建目录。当前没有解封 flag、override 或 confirmation evaluator。inspect 只返回声明与引用，不返回行情值。

这是 CLI/application 的路由约束，适用于调用这些接口的受约束客户端。拥有宿主文件访问权限的用户仍可直接读取或另行导入原始数据；它不是多租户授权、保密 vault 或防止恶意研究员旁路的安全证明。确认集的单次使用、跨协议尝试计数、泄漏审计及完整 trial attempt ledger 仍需后续实现，不能将本功能宣传为“绝不会作弊的 Agent”。

## 机器可读错误与验收

| 退出码 | 常见 error.code | 含义 |
| --- | --- | --- |
| 0 | 无 | 已完成当前命令 |
| 2 | `unsafe_input` / `invalid_protocol` | 输入路径、格式、绑定、预算或策略语法无效 |
| 3 | `protocol_integrity_or_publication_failure` / `store_integrity_or_publication_failure` / `io_failure` | 存储损坏或 I/O/发布失败 |
| 4 | `protocol_not_found` / `dataset_not_found` | 已指定身份不存在，不创建缺失存储 |
| 5 | `confirmation_access_denied` | 当前阶段禁止读取 confirmation |

argparse 参数错误仍走标准用法与退出码 2。核心测试覆盖身份规则、边界、重复与并发登记、故障/篡改、真实数据绑定、伪报告拒绝、确认集拒绝及 CLI；distribution smoke 在源码目录之外用新环境安装 wheel，验证同一链路。它们不替代真实访谈、外部复验、策略沙箱或引擎集成验收。
