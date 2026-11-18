# Sprint 12 SDK 与实际集成状态

更新2026-11-18 Asia/Singapore。Owner已合并 [PR111](https://github.com/Darrenus/tickwitness/pull/111)，真实 merge `d7696ba01f92a58a3bb26f6b58e421a30698c93a`，2026-11-18T14:37:31Z，接受S12-02招募缺口路径材料及伴随#112测试修正。候选 `cfce0128b6247d239dc56975a9b4565f3af90b14` 的17项远端检查全通过；六core各4371通过/112跳过、两native各4480通过/3跳过、定向344通过，实际CI checkout `06ff8c0aa2b809cff41e10c9d8d4be0d012658a9` 不是owner merge。原失败、PR111预验收149成员封存及PR110既有16份DATA审计均保留原身份，实际接受另存；不把历史审计或材料接受计作真人激活。

| 故事 | 原容量 | 当前状态 |
| --- | ---: | --- |
| S12-01 / #34 | 12h | PR110已接受；[稳定SDK子集](../contracts/python-sdk-v1.md)／[ADR0041](../adr/0041-stable-python-sdk-subset.md)的五个共用应用服务方法、独立安装消费者和类型验收完成 |
| S12-02 / #35 | 14h | PR111已接受[手工接入证据规则](../contracts/onboarding-evidence-v1.md)／[接入指南](../user-onboarding.md)、[空白记录](../templates/onboarding-case-v1.md)、[判定示例](../templates/onboarding-review-examples.md)和[真实缺口](s12-02-recruitment-gap.md)；真人接入仍PENDING |
| S12-03 / #36 | 8h | 先冻结[SDK兼容与可执行文档](../contracts/sdk-compatibility-v1.md)／[ADR0043](../adr/0043-sdk-compatibility-and-executable-docs.md)，再补适配器回归、安装后文档样例及分版本支持；新资格不预计通过 |

原S12专项34h与持续质量容量不变，不补造实际工时。SDK首版聚焦data/declaration/bounded-development-read，不宣称所有CLI命令均为稳定SDK。构造无IO、文件入口复用安全读取、错误与CLI相容、原冻结max_events限制不可绕过；SDK消费者资格不执行研究、不增加native或槽、不重置/退款原5/8/11协议预算。SDK摘要不是命题评价或自有研究激活；declaration-v1与CLI executable-v2不可互换。

S12-02伴随质量缺陷 [#112](https://github.com/Darrenus/tickwitness/issues/112)已随PR111接受：首候选 `374e75a` 的macOS native完整测试在取消控制线程读到已有合同允许的Catalog冲突时真失败，原日志保留。仅修正该既有测试的有界心跳轮询，并参数化无注入/控制线程首次冲突注入；原时限、三次真实心跳及取消/回收断言不放宽，生产代码与协议预算不改。中间 `e604de3` 格式失败及取消的未完成作业保留；最终cfce独立全绿，不改变原故事容量或补造实际工时。

S12-03保持既有领域规则：封闭schema拒绝未知键，开放有界标量parameters保留并进入协议身份，None保持未知。计划新增文档1次和代表性CLI拒绝2次，共27功能+4类型调用，仍共用原32次/180秒期限，原研究预算不重置。分清Python3.12–3.14源码回归与仅Python3.12的四档已安装消费者资格；新四档SDK证据需真实产生，不继承旧绿色。

全部项目测试、构建、安装、格式、类型、原生执行仅远端GitHub Actions CPU。外部真人0 attempts/0 successes/PENDING（#24 OPEN）；自动消费者、CI、AI和owner不计外部激活或30天复用。尚未收到可核验真人参与及自有案例记录，联系数量和回复情况为UNKNOWN，不推断无人联系或没有需求。HTTP保留到S14条件性入口或以后，GPU延后，没有release、采用或收益声明。#36在owner实际接受前保持OPEN；原独立8h和持续质量容量不变。
