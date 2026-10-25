# 校验与执行耦合回放时钟压力

状态：S05-01/02 开发用例，目标版本 `0.2.0.dev0`；对应 PR/远端 CI 验收前不记为已接受能力。`validate-scenario` 核对一份 assumption 与候选 scenario 的冻结来源和输入约束，仍然**不执行、不占用 attempt、不计算收益**。单独的 `run-scenario` 负责占预算和运行，`inspect-scenario-run` 重新派生并审计已提交结果。0.1 技术预览的发行状态仍以[其发布记录](releases/0.1.0a1.md)为准。

首个声明是 `replay_receive_suffix_shift_v1`：从指定 capture 起，对整个后缀的 receive 时间声明增加一个非负常数。它属于人为额外压力，范围由研究者设置且未校准；不是对历史网络延迟的还原。精确字段见[Assumption / Scenario 合同](contracts/assumption-scenario-v1.md)，设计理由见 [ADR-012](architecture/decisions.md#adr-012-场景声明与延迟压力执行分开验收)。

## 在远端准备核心环境

在受支持的远端 CPU 主机/GitHub Actions 上，取得本开发切片的固定 commit 和代码；不要用 `0.1.0a1` 已发行制品替代 `0.2.0.dev0` 开发版本。以下从该 checkout 根目录运行，环境放在 checkout 外：

```sh
TW_SCENARIO_ENV=/tmp/tickwitness-scenario-core
UV_PROJECT_ENVIRONMENT="$TW_SCENARIO_ENV" uv sync --locked --python 3.12
TW="$TW_SCENARIO_ENV/bin/tickwitness"
"$TW" --version
```

已有同名环境时换一个新的绝对路径。此用例不需要 `nautilus` extra 或 GPU；校验只使用核心包和已有源输入。环境/文件系统及可信 owner 边界见[支持页](support.md)；0.2 的实际验收组合仍须看本切片 CI，不能从旧预览记录推断已经通过。

## 准备被引用的 development 协议

已有 v2 协议时可以跳过本节。下面的 import/freeze **会显式写入**新的本地数据与 registry，但不运行引擎、不预留 attempt；随后 `validate-scenario` 才是只读操作。样例为仓库原创合成 EUR-USD 数据。

```sh
set -eu
TW_DEV=$("$TW" import-events replay-partials.jsonl --input-root examples --store .local/scenario-data --id-only)
TW_CONFIRM=$("$TW" import-events replay-confirmation.jsonl --input-root examples --store .local/scenario-data --id-only)
TW_PROTOCOL=$("$TW" freeze-experiment experiment-request.json --input-root examples --development-dataset "$TW_DEV" --confirmation-dataset "$TW_CONFIRM" --store .local/scenario-data --registry .local/scenario-experiments --id-only)
```

只使用刚冻结的协议 ID，任何一步报错后停止，不继续传递空 ID。费用、策略参数、数据或预算若发生变化，应先注册新协议；不能编辑已有协议来绑定另一份输入。

## 校验 assumption 与候选参数

使用本切片 `examples/assumption-request.json` 与 `examples/scenario-request.json`：assumption 选择 capture anchor、纳秒区间、研究者参数依据；scenario 在该闭区间内选择一个 delay。请求不允许自行填写 protocol/dataset/spec hash，来源由真实输入注入。

```sh
"$TW" validate-scenario "$TW_PROTOCOL" assumption-request.json scenario-request.json --input-root examples --store .local/scenario-data --registry .local/scenario-experiments --split development
```

命令没有 `--runs`、`--engine-python` 或 execute 开关，不创建 registry/store、不写派生行情、不消费协议 attempt。现有根不存在、对象损坏或参数不支持时明确失败，不通过创建空目录掩盖问题。重复请求对相同冻结输入应产生相同 assumption/scenario 身份，不创建新的研究运行。

成功JSON的顶层为`assumption`、`scenario`、`validation`三份文档；前两者保存canonical spec字段，`validation`包含`kind=validated_scenario_constraints_v1`、两个spec ID、真实bindings、类别、变换与参数，并明确：

```text
source_bindings_verified = true
input_constraints_verified = true
calibration_status = uncalibrated
execution_approved = false
```

这表示给定的来源引用和输入约束通过，不是市场真实性、校准、引擎兼容性或收益判定。参数的 `ns` 不能省略；60 秒是工程支持上限，不是测得的物理界限。`calibration_evidence_refs` 当前必须为空，自报 calibrated 或随意放入证据 hash 不会升级信任等级。

## 确认集请求先于 IO 拒绝

以下命令应退出 5，且不创建指定的仓库根：

```sh
if "$TW" validate-scenario "$TW_PROTOCOL" assumption-request.json scenario-request.json --input-root examples --store .local/scenario-must-stay-absent/data --registry .local/scenario-must-stay-absent/experiments --split confirmation; then
  echo 'Unexpected confirmation access' >&2
  exit 1
else
  TW_EXIT=$?
  test "$TW_EXIT" -eq 5
fi
test ! -e .local/scenario-must-stay-absent
```

非零退出是预期访问拒绝，不是“已读取后丢弃确认数据”。这项策略约束平台入口，不能对宿主 owner 隐藏其文件。

其他应拒绝的输入包括：未知 kind/semantic/字段、错误类别、float/bool 延迟、缺失或非 ns 单位、负值/倒置/超范围区间、非空校准引用、不存在的 capture anchor、与协议不符的数据/spec，以及时间或 execution horizon 溢出。错误保留为校验失败，不登记为策略亏损或反例；缺失 store/registry 不会因检查而自动创建。

## 已限定的时钟含义

引擎使用同一 receive-order 时钟推动市场数据与策略，并以 capture_seq 触发内置下单。native `ts_event` 和 `ts_init` 都取派生 receive 时间；原始 event 时间保留为证据字段。每个真实输入步骤先处理行情/匹配，再派发策略回调并结算命令。到期撤单没有独立 timer 保证，不能假定它必定先于该步骤的成交生效。EOF 不补虚构输入，不强行排空未决命令。

全流平移负对照、零延迟、非零撤单竞争和 EOF 的固定合成案例已先在远端资格门运行，记录见 [Sprint 5 状态](planning/sprint-05-status.md)。该资格限于 pinned engine 与声明的 `coupled_receive_suffix_clock_v1`，不证明“市场照常、研究者晚收到信息”的双时钟 feed-delay，也不构成真实市场校准。完整合同见[场景执行 v1](contracts/scenario-execution-v1.md)。

## 在远端执行与复核

下面例子使用 CPU 原生环境；从本分支固定 commit 安装，不在个人电脑运行测试或回放：

```sh
TW_STRESS_ENV=/tmp/tickwitness-stress-native
UV_PROJECT_ENVIRONMENT="$TW_STRESS_ENV" uv sync --locked --extra nautilus --python 3.12
TW="$TW_STRESS_ENV/bin/tickwitness"
TW_DEV=$("$TW" import-events replay-partials.jsonl --input-root examples --store .local/stress-data --id-only)
TW_CONFIRM=$("$TW" import-events replay-confirmation.jsonl --input-root examples --store .local/stress-data --id-only)
TW_PROTOCOL=$("$TW" freeze-experiment stress-experiment-request.json --input-root examples --development-dataset "$TW_DEV" --confirmation-dataset "$TW_CONFIRM" --store .local/stress-data --registry .local/stress-experiments --id-only)
"$TW" replay-protocol "$TW_PROTOCOL" --store .local/stress-data --registry .local/stress-experiments --runs .local/stress-runs
"$TW" run-scenario "$TW_PROTOCOL" stress-assumption-request.json stress-zero-request.json --input-root examples --store .local/stress-data --registry .local/stress-experiments --runs .local/stress-runs
"$TW" run-scenario "$TW_PROTOCOL" stress-assumption-request.json stress-suffix-request.json --input-root examples --store .local/stress-data --registry .local/stress-experiments --runs .local/stress-runs
```

从成功 JSON 复制实际返回的 `run_id`、`attempt_id`，传给以下命令（用实际 ID 替换 `RUN_ID`、`ATTEMPT_ID`）：

```sh
"$TW" inspect-scenario-run RUN_ID --store .local/stress-data --registry .local/stress-experiments --runs .local/stress-runs
"$TW" inspect-scenario-attempt ATTEMPT_ID --runs .local/stress-runs
```

一次原生调用消耗原协议一个 slot；上面三次运行正好消耗样例三次预算。重复同一候选、改候选、失败、超时和中断都不返还。基线结果要单独运行或引用已有证据，本命令不会暗中额外跑基线。更改范围生成新的 assumption 身份，但不会替同一协议重置预算。

启动 worker 前，reservation、完整 scenario intent、assumption/scenario、派生描述及派生字节先持久化。来源数据仓库和协议不被改写；派生 input 使用 `derived_view_not_catalog_manifest_v1` 身份，不能冒充原 sealed dataset。`inspect-scenario-attempt` 读取已消耗 slot 与场景身份，缺终态显示 `reserved_unfinalized`；intent 持久化失败时不会启动引擎，该 slot 仍然消耗。运行失败返回带 `attempt_id`、`budget_consumed=true` 的错误；持久化终态无法确认时返回 `attempt_outcome_unconfirmed`，先检查 attempt，不能盲目重跑。

`inspect-scenario-run` 不启动 native：重新读取原 development 闭包、校验声明、重新派生字节和身份、核对 CAS/intent/终态，再重算账务与估值。只在完整且费用可审计时输出 `metric_observation.eligible=true`；否则值为 null。它不输出原 baseline claim 的真假、反例、搜索覆盖或历史相容性。完整的基线/干预关联和首次分歧报告仍属于 S05-03。

本切片的场景证据保存在三个持久根（data、registry、runs）中，需一起保留。独立可搬迁的场景 bundle 尚未提供；旧 `export-evidence`/`verify-evidence` 八角色 v1 仍只接受 baseline，场景回执进入旧导出路径应被拒绝。查询失败不会创建缺失的仓库根。
