# 外部队列约束与原生资格

本页对应 S06-01 的第一阶段：核对明示的外部排队约束，并用固定原创合成观测验证公开原生扩展。它不是任意用户数据的队列执行入口，不输出成交预测、收益、原命题真假或 `NOT_IDENTIFIABLE_WITHIN_MODEL`。实际状态见 [Sprint 6](planning/sprint-06-status.md)，精确合同见 [Queue constraints v1](contracts/queue-constraints-v1.md)。

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

只有固定案例真实远端运行后才记录通过结果。新 engine semantic 明确区别于原 v1；旧 ReplaySpec、v2 可执行协议、baseline auditor、bundle 和 S05 比较器不接纳新队列执行。下一阶段还须冻结 queue family 协议、两解释集合、共同预算、不可替换 intent、queue trace、独立账务与执行审计；用户数据上的模型调用必须占研究预算，不能借“资格检查”绕过。真实观测相容性与命题分歧仍是后续独立门。
