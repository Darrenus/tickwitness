# Sprint 2 数据证据与冻结协议状态

更新：2026-10-26（Asia/Singapore）。PR#73与PR#74已获owner接受并合并；S1两项工程故事及S02-01已完成。**真实访谈仍为0次。** 本批继续不依赖真实用户证据的技术切片，不把工程通过当作市场验证或整个Sprint完成。

| 故事 | 当前工程进度 | 剩余验收 |
| --- | --- | --- |
| S02-01 / Issue#4 | PR#74已合并，规范化JSONL、有界安全输入、结构/序列预检与隔离报告已接受；Issue已关闭 | 真实交易所adapter、完整盘口/时钟认证和大文件扫描属于后续范围 |
| S02-02 / Issue#5 | PR#74的不可变dataset已接受；本批完成Nautilus L2补测并提出固定1.231.0的有限选型ADR | 本批选型待PR验收；S3再实现adapter与正式性能基线 |
| S02-03 / Issue#6 | 本批新增冻结领域合同、真实数据/源码绑定、不可变registry、开发集读取与确认集拒绝 | 完整ClaimSpec/trial生命周期、累计预算与真实访谈仍未完成，故事保持开放 |

可执行流程见[数据导入](../data-import.md)和[研究协议](../research-protocols.md)。CLI新增`freeze-protocol`、`inspect-protocol`和`read-protocol-data`；当前没有replay、搜索、收益评价或最终研究判定命令。

## 冻结切片的验收范围

- 纯domain验证bounded strict JSON，生成独立claim revision与完整protocol身份。费用/参数/数据/策略变化创建新协议，命题变化修订claim；历史版本不覆盖。
- application经端口核验真实封存数据及策略源码。重新计算规范化与报告，拒绝隔离数据、伪质量报告、capture回退、重叠book序列及重复trade身份；源码只解析语法和哈希，不执行。
- infrastructure独立存储策略CAS和协议，协议原子发布，读取验证完整性；与数据catalog没有跨存储ACID承诺。故障可能留下未引用对象，不发布可用的半份协议。
- 所有冻结声明`execution_ready=false`。只有绑定的development可读，confirmation请求在任何repository初始化前拒绝；当前无解封入口。单次读取limit不代表累计预算，也不对宿主owner隐藏数据。
- 架构检查禁止domain向外依赖和application直接导入storage adapter；真实临时FS/SQLite、并发/篡改/故障、应用与CLI测试及安装后wheel smoke分别覆盖技术边界。

数据`accepted`只表示规范化v1明示的结构/序列预检；报告仍为`replay_certified=false`、clock未绑定。冻结不把它升级为时点/统计独立或真实队列认证。完整trial attempt ledger、确认集一次性使用、策略sandbox和最终判定仍待后续切片。

## 引擎选型与S3交接

[HFT补测](../research/hftbacktest-selection-gates.md)发现固定版本部分成交账务不一致与fill轮询缺口；旧EOF推断已通过receipt更正并保留原证据。[Nautilus真正L2补测](../research/nautilus-l2-selection-gates.md)的六案例在两次独立进程中一致，分时/同刻partial回调与现金、持仓、费用对齐。

据此提出[ADR-008](../architecture/decisions.md)及[综合选择记录](../research/engine-selection.md)：S3首个单资产L2 adapter以NautilusTrader1.231.0 stable v1为目标。正式adapter和optional extra尚未加入；数据步驱动延迟、EOF在途命令incomplete是硬边界，S6精确相容队列见证仍closed。Apache原创项目与LGPL第三方依赖保留各自许可。

S3下一技术切片应实现输入反腐映射、逐笔trace与账务契约、显式终止完整性，然后测量同语义基线；不能把研究脚本改名即视为正式集成。当前没有向上游发送Issue、PR、消息或报告。

本批完整工程检查与CI结果随PR保存。选型在owner验收前不关闭Issue#5；Issue#6不因技术部分完成而关闭，访谈与试验生命周期要求继续可见。实际人工工时尚未登记，不将AI运行时间冒充人力投入。
