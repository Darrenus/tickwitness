# 只读校验一项压力场景声明

状态：S05-01 开发用例，目标版本 `0.2.0.dev0`；对应 PR/远端 CI 验收前不记为已接受能力。`validate-scenario` 核对一份 assumption 与候选 scenario 的冻结来源和输入约束。它**不执行变换或回放、不占用 attempt、不计算收益或 finding**。0.1 技术预览的发行状态仍以[其发布记录](releases/0.1.0a1.md)为准。

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

## 为什么暂不运行延迟压力

目前引擎 profile 使用同一 receive-order 时钟推动市场数据与策略，并以 capture_seq 触发内置下单。把全部记录加一个常数可能只平移时间戳，trace/hash 不同不能证明经济结果不同。后缀平移也尚未被资格验证为“市场照常、研究者晚收到信息”的双时钟接收延迟模型。

S05-02 将另行验证时间、lineage、adapter 能力和审计语义；S05-03 再处理有明确共同条件的干预配对。零延迟对照、全流平移负对照与已知有效压力案例是未来门槛，本页不声称已完成。当前无情景执行结果、命题翻转、搜索覆盖、收益范围或观测相容性结论。
