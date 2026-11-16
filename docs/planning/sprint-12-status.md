# Sprint 12 SDK 与实际集成状态

更新2026-11-16 Asia/Singapore。Owner已合并 [PR108](https://github.com/Darrenus/tickwitness/pull/108)，真实merge `667ca69733e95b133b29c1dc479cef585742cc6e`，05:26:05Z，接受S11-03和伴随#109 journal竞态修正。其候选39137fd的17项远端检查、四档各三份完整DATA审计共12份通过；实际CI checkout28d4eb10不是owner merge。原失败记录及旧封存不改写。

| 故事 | 原容量 | 当前状态 |
| --- | ---: | --- |
| S12-01 / #34 | 12h | 先冻结 [稳定SDK子集](../contracts/python-sdk-v1.md)／[ADR0041](../adr/0041-stable-python-sdk-subset.md)，再实现五个共用应用服务方法、独立真实消费者和类型验收；新资格未预先计通过 |
| S12-02 / #35 | 14h | Planned；真实外部用户及反馈为外部依赖 |
| S12-03 / #36 | 8h | Planned；支持与自助文档按原计划推进 |

原S12专项34h与持续质量容量不变，不补造实际工时。SDK首版聚焦data/declaration/bounded-development-read，不宣称所有CLI命令均为稳定SDK。构造无IO、文件入口复用安全读取、错误与CLI相容、原冻结max_events限制不可绕过；新资格不执行研究、不增加native或槽、不重置/退款原5/8/11协议预算。

全部项目测试、构建、安装、格式、类型、原生执行仅远端GitHub Actions CPU。外部真人0 attempts/0 successes/PENDING（#24 OPEN）；自动消费者、CI、AI和owner不计外部激活或30天复用。HTTP保留到S14条件性入口或以后，GPU延后，没有release、采用或收益声明。#34在owner实际接受后才Done。
