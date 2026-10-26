# 外部队列约束与原生资格

本页覆盖 S06-01a 的约束与固定资格，以及 S06-01b 的冻结队列族、共同预算、持久双模型执行与只读复核。执行支持满足受限合同的用户导入 development 输入，分类为 `MODEL_SENSITIVITY`；不输出成交预测、收益估值、原命题真假或 `NOT_IDENTIFIABLE_WITHIN_MODEL`。实际状态见 [Sprint 6](planning/sprint-06-status.md)，精确合同见 [Queue constraints v1](contracts/queue-constraints-v1.md) 和 [Queue Family v1](contracts/queue-family-v1.md)。

## 外部观测和模拟订单分开

L2 的价位数量与逐笔成交不能识别真实撤单位置，也不能单独识别 gross additions/cancellations。声明必须显式给每个目标价位 checkpoint 的增量、撤量及其间唯一归属的 trades，满足：

```text
V_after = V_before + additions - cancellations - trades
ahead + behind = external visible volume
```

本模型假定外部 FIFO、无隐藏流动性，增量在 checkpoint 加到队尾、撤单再按 front-first 或 back-first 分配。外部 tape 不包含 shadow probe；其无市场冲击假设**未经验证**，不能因为两条队列账本都守恒，就宣称已证明真实市场的两个相容世界。

同一数据和同一组 gross flows 只改变撤单分配政策。每笔 trade 先按 FIFO 消耗外部 ahead/behind；随后绝对 L2 更新是对账 checkpoint，不能再将同一减少量当作额外撤单。超可见量成交、未对账 EOF、重复/缺失 trade 引用、错误目标或来源均拒绝。当前只支持固定首 snapshot/capture 1 的声明入口、零 insert latency、单流 EUR-USD 目标 bid；实际接受点仍须独立原生验证。

## 在远端检查声明

从当前分支的固定 commit，在受支持远端 CPU 环境安装核心包。核心校验不需要原生 extra 或 GPU：

```sh
set -eu
TW_QUEUE_ENV=/tmp/tickwitness-queue-core
UV_PROJECT_ENVIRONMENT="$TW_QUEUE_ENV" uv sync --locked --python 3.12
TW="$TW_QUEUE_ENV/bin/tickwitness"
TW_DEV=$("$TW" import-events queue-observations.jsonl --input-root examples --store .local/queue-data --id-only)
TW_CONFIRM=$("$TW" import-events replay-confirmation.jsonl --input-root examples --store .local/queue-data --id-only)
TW_PROTOCOL=$("$TW" freeze-experiment experiment-request.json --input-root examples --development-dataset "$TW_DEV" --confirmation-dataset "$TW_CONFIRM" --store .local/queue-data --registry .local/queue-registry --id-only)
"$TW" validate-queue-constraints "$TW_PROTOCOL" queue-constraint-request.json --input-root examples --store .local/queue-data --registry .local/queue-registry --split development
```

前面的 import/freeze 显式写入新证据根；最后的 `validate-queue-constraints` 是只读。v2 协议只提供实际来源和旧 ReplaySpec 绑定，不因此授权新 queue 模型执行。命令没有 `--runs` 或 engine 参数，不创建 attempt，不运行策略，不改原行情或协议。确认集请求先于输入文件及仓库 IO 拒绝；查询缺失仓库不创建空根。

输出保存 `constraint_id`、`validation_id`、canonical constraint 和两种解释的逐步 ahead/behind/external trace。成功只证明在给定输入及明示假定下引用、量守恒与非负约束通过，并固定标注：

队列 trace 的虚拟入口不代表旧 v2 策略订单实际被接受、全程存活或尚未撤单；纯校验不模拟其生命周期。某种成交／深度时序被拒绝，也只说明它不满足当前声明的 profile，不能据此排除其他隐藏流动性或不同 interleaving 下的所有历史解释。

```text
classification = MODEL_SENSITIVITY_CANDIDATE
actual_acceptance_verified = false
impact_compatibility_verified = false
native_execution_verified = false
execution_approved = false
```

样例为初始外部量 5，新增 3，撤 3，再卖出 3，最后绝对量 2。front-first 在 trade 前为 `(ahead=2, behind=3)`，back-first 为 `(5,0)`；最终分别 `(0,2)` 与 `(2,0)`，两边外部量始终与同一对账证据一致。这些字段不叫 fill，也不提供 PnL。

## 固定原生资格的边界

原 `queue_position=True` 只有一个内置规则，不能通过开关名称冒充前/后撤单解释。新的资格脚本仅处理仓库固定合成案例，使用公开 `SimulationModule`、自定义 `FillModel`、接受与成交回调；关闭内置 queue gate，在每 capture 的显式容量授予/消费账本下，仍由原生引擎产生订单、成交、费用和账户记录。

返回空 OrderBook 表示本次不授予成交量；返回 None 会回退旧撮合，因此必须专项测试。自定义 book 路径不能假定已有标准 liquidity-consumption 保护，重复 hook、非 trade 和接受前输入都不能重复或提前授予成交量。EOF 不补虚构数据，也不强制清空在途命令。

只有固定案例真实远端运行后才记录资格通过。生产队列执行使用独立 engine semantic，严格区别于资格 probe 和原 v1；旧 ReplaySpec、v2 可执行协议、baseline auditor、bundle 和 S05 比较器不接纳新结果。真实观测相容性与命题分歧仍是后续独立门。

## 冻结并执行双模型

以下命令仍只在远端执行。沿用前文已导入的 development/confirmation ID 与 source protocol，另安装 pinned native extra；每个模型调用消耗新族的一个共同预算槽。首次失败即停止，不会自动重试另一模型。

```sh
TW_QUEUE_NATIVE_ENV=/tmp/tickwitness-queue-native
UV_PROJECT_ENVIRONMENT="$TW_QUEUE_NATIVE_ENV" uv sync --locked --extra nautilus --python 3.12
TW="$TW_QUEUE_NATIVE_ENV/bin/tickwitness"
"$TW" freeze-queue-family "$TW_PROTOCOL" queue-family-request.json queue-constraint-request.json --input-root examples --store .local/queue-data --registry .local/queue-registry --families .local/queue-families
```

从返回 JSON 取得 `family_id` 后设置 `TW_FAMILY`；首次双模型会消耗样例预算的全部 2 槽。重复执行不会复用结果或获得免费尝试。源 v2 原预算不授权新队列政策；冻结的新族包含完整来源与两政策，拥有一份共同预算。

```sh
"$TW" run-queue-family "$TW_FAMILY" --families .local/queue-families --store .local/queue-data --runs .local/queue-runs
"$TW" inspect-queue-family "$TW_FAMILY" --families .local/queue-families --store .local/queue-data --runs .local/queue-runs
```

输出列出各 run/attempt/intent ID、实际成交量/费用、独立评价与模型 scope。双调用可能部分成功；JSON 明确列出成功 runs、失败模型与是否消耗预算、未尝试模型，并返回非零 exit code。第二次失败不会撤销第一份结果。仅需显式补一个模型时可用 `run-queue-model FAMILY POLICY`；仍需剩余预算，不会更换 intent 复用旧槽。

将某一成功 `run_id` 设置为 `TW_RUN` 后，只读复核不运行 native，也不再消耗尝试：

```sh
"$TW" inspect-queue-run "$TW_RUN" --families .local/queue-families --store .local/queue-data --runs .local/queue-runs
```

复核核对实际 store、immutable family、reservation/intent/receipt 的持久闭包，并从源重新计算队列与金融审计。返回实际输入、队列/授予/原生订单/成交/费用/账户 trace；`native_replayed=false`。族视图展示当时可见的 committed slot 前缀，失败、超时与未结束 attempt 均消耗预算。缺失 ledger 根返回缺失证据错误，不创建空目录或假报 0 次研究。

样例成功预期是 front 实际成交 1 lot、费用 1 USD；back 实际成交 0、费用 0，两者都在 capture 6 收到真实撤单回执。此预期必须由远端实际安装包验收确认。非 1 的价格/数量增量、不同数量/资金与不同最终取消 capture 也有独立原生测试。文件尾缺回执不会被标为 verified；已取得的有界原生结果保留为失败诊断。
