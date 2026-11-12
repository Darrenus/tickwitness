# Sprint 11 成本与数据生命周期状态

更新2026-11-12 Asia/Singapore。Owner 合并 [PR106](https://github.com/Darrenus/tickwitness/pull/106)，真实 merge `15bc36fec573297b43a1aa21cd51232b6550305b`，04:52:53Z，接受 S11-01。合同先于实现冻结，当前接受的资源报告、元数据专用投影和历史绑定见 [资源合同](../contracts/job-resources-v1.md)／[ADR0037](../adr/0037-observed-job-resources.md)。本轮先冻结 [引用感知保留合同](../contracts/dataset-retention-v1.md)／[ADR0038](../adr/0038-reference-aware-dataset-retention.md)，再实现 S11-02；新资格尚未计通过。

| 故事 | 范围 | 当前状态 |
| --- | --- | --- |
| S11-01 / #31 /11h | 独立 Job 资源报告、CPU／RSS 的真实来源、清理逻辑字节、阶段耗时、严格未知值和只读成本预览 | owner106 已接受；17项远端检查与四份全新完整DATA审计通过 |
| S11-02 / #32 /12h | 引用感知保留策略和 dry-run 清理 | 合同先冻结；仅独占DatasetStore孤立CAS，全部manifest闭包保留，未知或混合命名空间阻断 |
| S11-03 / #33 /10h | 磁盘满、权限、损坏对象、锁冲突故障预算 | Planned；本轮只覆盖资源功能必要失败边界 |

原专项33h（11＋12＋10）与持续质量容量不变，不补造实际工时。资源预算预览不预测未经校准的 CPU／内存／耗时，不把配置上限当成本，也不授予或返还原协议研究槽。当前回放结果未评价缩减命题；原生调用、记录数和心跳不冒充命题评估量。

S11-01接受证据：[Engineering43152423826](https://github.com/Darrenus/tickwitness/actions/runs/43152423826)／[Documentation43152423839](https://github.com/Darrenus/tickwitness/actions/runs/43152423839)，head688e065，实际CI checkout b665719（不是后来的真实owner merge）。定向193 passed，六档core各4224 passed／112 skipped，两档native各4333 passed／3 skipped；355格式文件、160严格源文件、109文档547本地链接。四档完整原始制品审计核对新metadata-only守卫、实际进程／资源／历史SQL和原预算。该资格不预先计为本轮GC能力通过。

全部项目测试、构建、安装、格式、类型、原生执行仅远端 GitHub Actions CPU。S11-02复用四档controls作业和独立保留制品，不增加引擎调用、研究槽或原预算。旧五／八／十一槽、golden、PR94 不变。外部真人0/PENDING（#24 OPEN），CI／AI／owner 不计外部真人；没有新 GPU、release、采用或收益声明。
