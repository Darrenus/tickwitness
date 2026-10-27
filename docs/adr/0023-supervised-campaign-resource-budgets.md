# ADR 0023：以独立合同监督 campaign 总资源预算

- 状态：Proposed；S07-02 实现，远端验收和 owner 审阅待完成。
- 日期：2026-10-27。
- 基线：owner 已合并 [PR #89](https://github.com/Darrenus/tickwitness/pull/89)，merge `4cc6ce49d99f2f89da87a4993570e5c4a0a178fa`。
- 合同：[Campaign Budgets v1](../contracts/campaign-budgets-v1.md)。

## 问题

S07-01b 已将自动候选与原协议 slots／intent／outcome 持久关联，但逐次 deadline 与单文件上限不构成 campaign 总时间或总存储硬门。只在候选间看时钟，会遗漏预检、审计和正在运行的 native；只统计最终目录大小，会遗漏原 ledger CAS／intent／outcome 的复制与临时 spools，并可能在结果产生后才发现无空间。

## 决策

新增独立 `supervised_search_campaign_v1` profile 和预算合同，保持旧 plan、campaign v1、scenario scope 和原协议 budget owner 不变。新入口冻结候选入场次数、同次执行的总 monotonic deadline 和受管理新增文件 payload 容量。Baseline、其它 plan、失败和中断仍共同消费原协议不可退款的 slots。

时间由外层进程 supervisor 约束完整协调执行阶段，native worker 继承同一可终止进程组，并使用原逐次限制与绝对剩余时间的较小值。Deadline 不能按候选重置或向上取整；退出后也检查期限。父进程在终止执行组后单独发布停止元数据并只读重审已有结果。输入校验与收尾的边界明确，不宣称整个 CLI 的硬实时返回或跨 reboot 继续使用 monotonic 值。

存储采用执行前不可退款容量预留：control32MiB、每候选64MiB，parent终态64KiB包含在control内。拿不到完整候选 envelope 时在原 slot reserve 前停止。原 ledger 和 campaign store 每个新文件写入都经过 payload guard；native stdin/stdout/stderr改用有界内存 pipes。CAS复用不据此增加候选容量，所有已提交结果保留。范围是受管理 payload，不是 FS block／RAM／runtime cache 或宿主磁盘 quota，也不防恶意 owner 绕过应用。

新 `bounded-search-campaigns/<plan_id>` 保存预算、入场及外层停止，内层继续使用已验收 v1 追溯链。重复执行新入口只重审旧记录，不更新限额、重置时钟或自动恢复未决工作。

## 停止与完整性

时间、容量或评估次数耗尽时明确停止后缀，已提交 outcome 与已消费原 slots 不删除、不退款；缺失和未决状态不伪造成完整搜索。预留终态容量保护正常预算耗尽收尾，但不保证物理磁盘满、权限或不确定系统调用下必有停止文件。发布不确定时保留实际内容，不能以函数报错覆盖已经提交的成功结果。

只读检查重建预算、累计入场和内层 source／reservation／intent／result／outcome，不启动引擎或 supervisor，不补写记录，不凭 metadata 自报认证实际物理时间、作者身份或全局统计试验历史。Search findings仍由S07-03、确认／sealed search evidence由S08、一般恢复／取消由S10分别交付。

## 验收

远端正例为正常两个候选共用原预算，并由独立core-only环境重审。边界包含首候选完成后评估次数或存储耗尽、零候选容量在占槽前停止、毫秒级剩余时间、执行中超时和全组清理、输出洪泛、精确容量边界、终态空间保留、修改限额不覆写、已提交结果不丢和原预算耗尽。实际wheel及actual source archive内脚本／样例分别验证；未发生的结果不写成通过。独立人类领域接受、实际工时、访谈和采用证据不补造。
