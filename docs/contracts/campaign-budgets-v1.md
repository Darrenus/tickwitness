# Campaign Budgets v1

状态：S07-02 实现合同，[远端验收已通过](../planning/sprint-07-status.md#s07-02-远端验收记录)，[PR #90](https://github.com/Darrenus/tickwitness/pull/90) 待 owner 接受。基线为 owner 已合并的 [S07-01b / PR #89](https://github.com/Darrenus/tickwitness/pull/89)，merge `4cc6ce49d99f2f89da87a4993570e5c4a0a178fa`；本轮不发行新版本。

## 用途与兼容边界

本合同为一份固定 [SearchPlan](search-plan-v1.md) 增加独立的受控执行入口：冻结 campaign 评估次数、执行阶段总墙钟时间和受管理文件 payload 存储上限。实际候选仍通过 [Search Execution v1](search-execution-v1.md) 的原 reservation／intent／outcome 链执行，继续消费原 `ExecutableProtocol v2` 的共同 attempt budget；新预算不能克隆原协议、退款或恢复已经消费的槽位。

新 profile 为 `supervised_search_campaign_v1`，与旧 `run-search-plan` 及 campaign v1 隔离。旧文件不追加新权限、不重写身份，不把以前只具备逐次 deadline 和单文件上限的运行改称具备总资源预算。新入口只支持原有 development-only、固定 anchor、未校准一维 receive-suffix `COUNTERFACTUAL_STRESS`。本轮仍不评价原 baseline claim，不签发 search finding，不认证连续空间覆盖、真实市场概率或完整统计 trial-family 历史。

## 冻结请求

请求须为有界、非空 UTF-8 JSON，严格拒绝重复键、未知／缺失字段、浮点数、布尔冒充整数和非有限值。精确字段如下：

```json
{
  "kind": "campaign_budget_request_v1",
  "schema_version": 1,
  "max_evaluations": 5,
  "max_wall_time_ms": 120000,
  "max_storage_bytes": 536870912
}
```

`max_evaluations` 为 `1..100`，约束不可退款的候选入场次数，包含失败、中断或未决尝试，不能只计算成功结果。`max_wall_time_ms` 为 `1..3_600_000`。`max_storage_bytes` 为 `32 MiB..16 GiB`。实际协议拥有的剩余原槽位可能更少；任一限制先到都应停止，并保留另一预算的原始事实。

预算对象绑定 plan、原 protocol、限额、计量政策和新 nonce，使用 exact canonical JSON 的 SHA-256 身份。它是执行前的固定合同，不是预算使用量的自报证明、作者签名或物理发布时间认证。再次运行同 plan／runs 根只重审原记录，不刷新 deadline、不重新授予容量、不自动恢复。请求的限额发生变化时拒绝覆盖已有预算；新 plan 仍与其它运行争用同一原协议 slots。

## 总执行时间

外层 supervisor 在启动协调进程前建立同一次运行的绝对 `monotonic_ns` deadline。协调器的候选预检、派发、原 ledger 写入、原生执行和账务处理位于该执行阶段内。每个 native worker 使用同一绝对 deadline，实际期限不晚于原逐次超时和剩余 campaign 时间的较小值；剩余不足时不启动 worker，不能把毫秒向上取整为额外完整秒。

执行协调器拥有独立进程组，native 子进程继承该组。超时或异常收尾时 supervisor 终止整个组并回收协调器，不能只杀协调器而留下 native 执行。Native 退出后、结果接纳前也核对期限，不能因 `poll()` 已得到退出状态而把刚过期的结果当成期限内成功。

这个上限约束受监督的执行阶段，不是整个 CLI 返回的硬实时保证。输入合同校验和已有证据的只读重审在执行前进行；终止、停止元数据发布及实际来源／账务的最终复核在独立收尾阶段进行。操作系统调度、进程终止和文件系统同步存在延迟，不能承诺纳秒级物理截止或无界恶意宿主上的实时性。持久化的 monotonic 数值只用于同次运行诊断，不跨重启续用，不作为 UTC 真值或历史未见证明。

## 存储硬门的计量范围

计量为平台直接管理的**新增文件 payload 字节**，不是文件系统 block／inode／目录 entry 的空间配额，不是 RAM、Python／native runtime cache 或整个宿主磁盘限额。既有 inputs／protocol／plan，以及其它 campaign 自身产生的文件不计入本次新增存储；本次复制到原 ledger 的派生制品、CAS／intent／outcome payload、campaign result 和 staging 均在范围内。

固定预留政策为：

| 容量 | 大小 | 责任 |
| --- | --- | --- |
| Control reserve | 32 MiB | 新预算头、旧内层 campaign 头、最多100份入场记录、协调元数据和停止收尾 |
| 每候选不可退款预留 | 64 MiB | 此候选的 dispatch／link／result、原 ledger 新增 payload 和临时 staging／复制的保守上界 |
| Parent terminal reserve | 64 KiB，包含在 control reserve 中 | 执行进程被终止后仍可写明确停止记录 |

每个候选在 reserve 原协议槽位前，先持久提交一份容量入场记录。若剩余存储不能容纳完整候选预留，则在占槽和构造引擎之前停止；不能等结果产生后才因空间不够丢弃它，也不能根据 CAS 去重命中或较小实际结果退款，给后续候选“补次数”。容量预留与实际已提交结果分开记录。

原 ledger 和 campaign store 在每个新文件 payload 写入前经过 guard；本次候选的累计写入不得超过其预留 envelope，control lane 也受独立限额保护。预算记录和终态空间不与候选结果争用最后几个字节。新 native adapter 使用有界内存 pipes 传递请求、stdout 和 stderr，不使用不受该限额约束的磁盘 spools；输出洪泛被拒绝并终止 worker，不能靠事后 `st_size` 采样宣称硬上限。

存储耗尽不会删除已经提交的结果、退款原槽位或重建目录“修复”历史。若物理磁盘本身已满、权限错误或系统调用返回不确定，仍可能无法完成收尾；应保留已有记录并显示未决／发布不确定，而非保证所有故障均能写出终态。这个可信本地模式不防恶意 owner 直接写文件或绕过应用，也不提供多租户磁盘隔离。

## 停止、持久化与复核

新记录位于 `runs/bounded-search-campaigns/<plan_id>/`，预算头、入场记录、外层停止记录和协调锁单独保存；`managed/` 中保留旧内层 campaign namespace，原 attempt ledger 仍在 `runs`。所有 committed 记录不可替换，读取保持 no-follow、有界常规文件与完整合同校验；已提交的 payload 不覆盖或删除。

外层停止原因区分完成、评估次数耗尽、存储耗尽、时间耗尽、内层执行停止／未决、worker 失败和发布不确定。预算终止不能写成整份计划完成，也不能把未派发后缀当作已评估。原 outcome 已提交但返回路径报错时保持原内容，检查重新核对实际结果，不能改成失败或自动重跑。

检查同时重建预算声明、按序入场及累计预留，核对每个已发生的候选与内层原 reservation／nonce／intent／result／outcome。若时间终止发生在协调器建立内层头之前，应明确显示没有内层执行记录；缺记录不能伪造成空集完整搜索。只读检查不启动 supervisor 或 native、不 reserve、不发布、不补写停止状态，也不重计 elapsed time。

## CLI

```sh
tickwitness run-bounded-search-plan PLAN_ID campaign-budget-request.json \
  --input-root examples --plans plans --store data --registry registry --runs runs

tickwitness inspect-bounded-search-campaign PLAN_ID \
  --plans plans --store data --registry registry --runs runs
```

两条命令均在 ID、文件读取和 repository factory 前拒绝 confirmation。无效请求、plan 或 source 在创建新运行根前拒绝；inspect 缺失根不创建。对于可重审的已记录停止状态，运行命令返回机器可读报告并以非零退出码区分预算／执行／存储停止；inspect 成功只说明可重审，不表示研究命题成立。最终报告保持 finding 权限关闭。
