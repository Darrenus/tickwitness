# ADR 0026：在整窗确认观测交付前不可逆登记来源暴露

- 状态：Proposed；S08-02 实现中，远端验收尚未完成。
- 日期：2026-10-28。
- 基线：owner 已合并 [PR #92](https://github.com/Darrenus/tickwitness/pull/92)，merge `275b5e1a8c8f706f5636773061b11da53231194a`。
- 合同：[Confirmation Access v1](../contracts/confirmation-access-v1.md)。

## 问题

既有冻结协议只允许探索读取 development；`split=confirmation` 在 repository 和请求文件读取前拒绝。这项路由约束尚不能表达明确开启确认窗口，也不能记录已经接触的样本。若仅给协议增加一次性开关，改实验名、重冻协议、换原 registry、重封 raw 文件或裁剪样本都会产生新身份，把已接触样本重新标成未见。

宿主 owner 已拥有原文件，应用层无法证明研究者此前从未接触它们。结构冻结本来就会读取确认字节以检查质量与 forward-disjointness；这种验证与向调用者交付确认观测必须分别描述。

## 决策

新增独立 `confirmation_protocol_v1`，完整绑定已有 frozen v1 或 executable v2 源声明、实际确认 normalized SHA、完整事件数和稳定来源 footprint。旧源协议的 development-only 政策保持原义；新协议只授权整窗观测交付，不授权 native、策略执行、收益评价或 confirmation finding。

确认状态固定在同一受管理 dataset root 的 `confirmation-state`，CLI 不接受独立 exposure root。以一个 bounded canonical `exposures.json` 保存已提交暴露记录，所有协议共享；原 source registry、实验名和新 confirmation protocol ID 都不能绕开同根来源交叠检查。整个账本 check-and-commit 以线程锁与进程 flock 串行化。

Footprint 依 `(source, instrument, session)` 分组，以 trade ID 和 book 闭区间表示来源；snapshot 为单点，delta 保留 `[first_sequence,last_sequence]`，相邻区间合并。相同 stream 的 trade ID 或 book 区间有交集即冲突。时间、capture metadata、价格、数量、raw 排版、切片、superset 与区间重分段不提供新鲜资格；不建立通用 lineage DAG，也不认证被改写的 source/session 来源。

开启时先检查已冻结协议与账本。已暴露直接拒绝，不再读取确认数据；未发现冲突仍须重验真实源、两份 accepted 数据、完整窗口与来源绑定，然后在暴露事务中再次检查并提交。完整窗口为 `1..min(request.max_events, source.budget.max_events)`，request 上限1000。超限整窗拒绝，没有分页、截断后缀或重开 override。

只有暴露记录完成原子替换与 fsync 后才允许返回观测。暴露表示保守消费，不证明交付成功：commit 后的错误、进程中断、输出失败和异常 port 回执都不退款。损坏、缺失必需账本或锁、未知 schema、超限和不安全文件全部 fail closed；不提供 repair/reset 开关。

同根初始化 anchor 检测状态目录意外丢失；先持久 pending 再替换完整 log 的提交保留不确定性标记。初始化或提交标记残留时整体拒绝，不自动清理成空账本。

## 结果与范围

报告区分 `NO_MATCHING_EXPOSURE_IN_LEDGER` 与 `ALREADY_EXPOSED_IN_LEDGER`，前者只陈述当前受信账本未发现交集，不能称历史未见或预注册证明。Exposure 保留完整 footprint、源协议、确认窗口和来源 hashes；其内容 ID 不认证作者、原始市场来源或全局试验历史。

重复、新名、跨协议、跨原 registry 和来源交叠窗口都继承同根暴露；不相交窗口仍可各自首次开启。数据导入与 owner 直接文件访问继续存在；恶意修改来源标签、删除或替换整个可信 root、使用新 store 仍在可信宿主边界之外。不可宣传为对 owner 保密的 vault，也不能因此声称“绝不会作弊的 Agent”。

安装验收仅使用 core wheel 和真实导入的合成数据，从独立 cwd 调用 CLI，在禁止 native、worker、网络、旧 attempt 和预算写入口的 guard 下检查整个流程。并发、commit 前后故障和文件边界由低层远端测试覆盖；smoke 另保留重复拒绝、origin 变体、完整窗口限制与坏账本拒绝的真实 records。测试、构建、安装、格式化及 source archive qualification 全部远端；验收结果回填 [Sprint 8 状态](../planning/sprint-08-status.md)，本 ADR 不预记成功、外部复验或人类领域接受。
