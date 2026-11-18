# Sprint 12 SDK 与实际集成状态

更新2026-11-18 Asia/Singapore。Owner已合并 [PR110](https://github.com/Darrenus/tickwitness/pull/110)，真实 merge `94fc08a98d3237077cfa79065d18c0daf91bcd88`，2026-11-16T10:38:23Z，接受S12-01。候选 `7ea5bce8edefda4f46deaf4981fc31a3d88d4f48` 的17项远端检查、四档各四份完整DATA审计共16份通过；实际CI checkout `b6da41bc3c1dd1728b23a06e4e397007ca3bee44` 不是owner merge。原失败记录和PR110预验收封存均不改写，实际接受另存。

| 故事 | 原容量 | 当前状态 |
| --- | ---: | --- |
| S12-01 / #34 | 12h | PR110已接受；[稳定SDK子集](../contracts/python-sdk-v1.md)／[ADR0041](../adr/0041-stable-python-sdk-subset.md)的五个共用应用服务方法、独立安装消费者和类型验收完成 |
| S12-02 / #35 | 14h | 先冻结 [手工接入证据规则](../contracts/onboarding-evidence-v1.md)／[ADR0042](../adr/0042-manual-own-case-onboarding-evidence.md)；按原验收的招募缺口路径准备指南和空白记录，真人接入仍为外部依赖 |
| S12-03 / #36 | 8h | Planned；支持与自助文档按原计划推进 |

原S12专项34h与持续质量容量不变，不补造实际工时。SDK首版聚焦data/declaration/bounded-development-read，不宣称所有CLI命令均为稳定SDK。构造无IO、文件入口复用安全读取、错误与CLI相容、原冻结max_events限制不可绕过；SDK消费者资格不执行研究、不增加native或槽、不重置/退款原5/8/11协议预算。SDK摘要不是命题评价或自有研究激活；declaration-v1与CLI executable-v2不可互换。

全部项目测试、构建、安装、格式、类型、原生执行仅远端GitHub Actions CPU。外部真人0 attempts/0 successes/PENDING（#24 OPEN）；自动消费者、CI、AI和owner不计外部激活或30天复用。尚未收到可核验真人参与及自有案例记录，联系数量和回复情况为UNKNOWN，不推断无人联系或没有需求。HTTP保留到S14条件性入口或以后，GPU延后，没有release、采用或收益声明。#35在owner实际接受本轮缺口路径交付前保持OPEN；S12-03仍为独立8h范围。
