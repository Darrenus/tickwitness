# Sprint 11 成本与数据生命周期状态

更新2026-11-12 Asia/Singapore。Owner 合并 [PR107](https://github.com/Darrenus/tickwitness/pull/107)，真实 merge `fd440659790a52b153daad3237f516d90ba9dd26`，06:27:24Z，接受 S11-02。此前PR106接受的资源报告见 [资源合同](../contracts/job-resources-v1.md)／[ADR0037](../adr/0037-observed-job-resources.md)；本次接受的 [引用感知保留合同](../contracts/dataset-retention-v1.md)／[ADR0038](../adr/0038-reference-aware-dataset-retention.md)保留全部有效manifest闭包。本轮先冻结 [有限故障预算](../contracts/dataset-fault-budget-v1.md)／[ADR0039](../adr/0039-bounded-dataset-fault-exercises.md)，再实现S11-03；新资格尚未计通过。

| 故事 | 范围 | 当前状态 |
| --- | --- | --- |
| S11-01 / #31 /11h | 独立 Job 资源报告、CPU／RSS 的真实来源、清理逻辑字节、阶段耗时、严格未知值和只读成本预览 | owner106 已接受；17项远端检查与四份全新完整DATA审计通过 |
| S11-02 / #32 /12h | 引用感知保留策略和 dry-run 清理 | owner107已接受；17项远端检查和四档各两份全新完整DATA审计通过；仅独占DatasetStore孤立CAS |
| S11-03 / #33 /10h | 磁盘满、权限、损坏对象、锁冲突故障预算 | 合同先冻结；八个有限操作故障与显式恢复，注入／实际OS故障分开，新资格未预先计通过 |

原专项33h（11＋12＋10）与持续质量容量不变，不补造实际工时。资源预算预览不预测未经校准的 CPU／内存／耗时，不把配置上限当成本，也不授予或返还原协议研究槽。当前回放结果未评价缩减命题；原生调用、记录数和心跳不冒充命题评估量。

S11-01接受证据：[Engineering43152423826](https://github.com/Darrenus/tickwitness/actions/runs/43152423826)／[Documentation43152423839](https://github.com/Darrenus/tickwitness/actions/runs/43152423839)，head688e065，实际CI checkout b665719（不是后来的真实owner merge）。定向193 passed，六档core各4224 passed／112 skipped，两档native各4333 passed／3 skipped；355格式文件、160严格源文件、109文档547本地链接。四档完整原始制品审计核对新metadata-only守卫、实际进程／资源／历史SQL和原预算。该资格不预先计为本轮GC能力通过。

S11-02接受证据：[Engineering43162303048](https://github.com/Darrenus/tickwitness/actions/runs/43162303048)／[Documentation43162303043](https://github.com/Darrenus/tickwitness/actions/runs/43162303043)，head2f44992，实际CI checkout de40516（不是后来的真实owner merge）。17项SUCCESS；定向271 passed，六档core各4302 passed／112 skipped，两档native各4411 passed／3 skipped。363格式文件、164严格源文件、111文档552链接。四档原controls/resources与独立retention各一份新完整DATA审计，共8份通过；每档8个受引用对象保留、精确2个orphan／65逻辑字节删除，重复零新增计数。全部原记录哈希保持一致；实际sdist driver及164模块／5相关脚本／36golden逐字节核对。该资格不预先计为本轮故障预算通过。

全部项目测试、构建、安装、格式、类型、原生执行仅远端 GitHub Actions CPU。S11-03复用四档controls作业、原retention制品和单独新fault制品，不增加引擎调用、研究槽、checks或作业超时。短写防御在CAS link前拒绝，不把旧实现描述成成功发布部分DatasetRecord。损坏对象的普通读取与metadata-only GC职责分开；已知部分与不确定IO不能报告完整成功。旧五／八／十一槽、golden、PR94 不变。外部真人0/PENDING（#24 OPEN），CI／AI／owner 不计外部真人；没有新 GPU、release、采用或收益声明。
