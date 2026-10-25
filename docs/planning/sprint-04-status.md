# Sprint 4 证据闭环工程状态

更新：2026-10-26（Asia/Singapore）。PR#76已由owner合并，S03-01/03已接受。当前补齐S03-02在明确受限profile内的估值，并实现S04-01/02纵向链路；本批待PR验收。真实访谈仍为0，S02-03完整family/trial/exposure生命周期、S6精确队列见证和S7搜索判定继续开放。

| 故事 | 本批交付 | 剩余范围 |
| --- | --- | --- |
| S03-02 / Issue#8 | 源输入/订单/fill/缓存账户独立审计、费用数值模型、最后观测bid估值与scoped claim observation | 只EUR/USD做多单限价、trade触发maker；无跨资产/平仓/通用投资组合收益评价 |
| S04-01 / Issue#10 | v2 freeze-experiment→预算预留→replay-protocol→export-evidence→verify-evidence；所有CLI调用共享application | 不执行任意策略，不把v1升级为可执行；完整公共SDK/HTTP/MCP/UI后续提供 |
| S04-02 / Issue#11 | 固定8-role目录包、原子no-replace发布、安全quota/no-follow读取、迁移后纯核心独立复算 | 非压缩包/签名系统，不独立重跑native或认证真实市场撮合 |
| S04-03 / Issue#12 | 保留为待细化发布工作，当前构建0.0.2.dev0 | 尚未发布0.1、PyPI或release tag；支持/维护与预览发布清单另验收 |

完整命令见[证据工作流](../evidence-workflow.md)，严格schema见[v2协议](../contracts/executable-protocol-v2.md)、[估值](../contracts/evaluation-v1.md)和[bundle](../contracts/evidence-bundle-v1.md)。[原创native生成样例](../../examples/evidence-demo/manifest.json)可用核心安装离线验证；确认行情不在包中。

## 质量与证据

应用在native构造前消费per-protocol attempt slot；失败/超时不退款，中断保留未知终态且预算已消费。slot与终态CAS不覆盖，实际并发/故障/损坏测试覆盖提交边界；不是完整统计family账本或断电认证。

审计逐项检查源fields、生命周期、单笔数量/价格、缓存现金/持仓及固定费用模型。交叉审查发现并修复“同步篡改费用与现金”“虚构价格改善”“缺收讫生命周期”及“导出先读确认集后拒绝”等漏洞，均保留回归。原生精度模式导致费用不唯一时明确not eligible，低阈值也不能生成claim truth。

原生真实回放涵盖正常/同刻partial、cancel竞态、open/pending EOF及费用half/nearhalf/双量化/歧义；另用固定native公开金额API独立交叉核211个费用数值案例。二者不同：211不是211次回放，更不是真实市场校准。核心与原生CI均验证安装后wheel完整链路；offline测试禁止native import和SQLite连接。

bundle完整性、绑定与账务通过，不等于作者签名、native已重跑、确认集已验或完整attempt账本已审查；回执显式列false。仍是可信本地模式，不承诺任意恶意代码沙箱、真实排队、未来价格保证或产品吞吐。最终测试数量与CI结果随PR保存，AI审查不替代独立人类领域复核，人工工时未登记。
