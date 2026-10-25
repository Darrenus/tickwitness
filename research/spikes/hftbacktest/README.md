# HftBacktest S01 可行性 spike

状态：2026-10-25 已执行的有限实验；**不是正式 adapter，也不是性能 benchmark**。研究结论见 [可行性记录](../../../docs/research/hftbacktest-feasibility.md)。

本目录只包含人工合成行情、固定可信策略、脚本、依赖快照和两次运行记录。策略只在本地历史回放中提交模拟订单；脚本不访问网络、不采集行情、不连接账户、不执行真实交易。

## 已执行的环境

- macOS 27.0.1 / Darwin arm64；CPython 3.12.14。
- HftBacktest 2.4.4；NumPy 2.2.6；Numba 0.68.0；llvmlite 0.50.0。
- 环境位于 `/private/tmp/tickwitness-s01-hft/.venv`，未修改项目根环境或依赖配置。
- 完整解析结果见 [requirements.lock.txt](requirements.lock.txt)。这是本机 spike 的固定依赖快照，不是项目正式 lockfile，也不证明其他平台可安装。

## 复跑

需要已有 Python 3.12 与 uv。以下步骤将环境和运行结果放到独立临时目录；包安装阶段访问官方 PyPI，fixture 本身离线运行。

```sh
UV_CACHE_DIR=/private/tmp/tickwitness-s01-hft/uv-cache uv venv --python 3.12 /private/tmp/tickwitness-s01-hft/.venv
UV_CACHE_DIR=/private/tmp/tickwitness-s01-hft/uv-cache uv pip install --python /private/tmp/tickwitness-s01-hft/.venv/bin/python --index-url https://pypi.org/simple --only-binary :all: -r research/spikes/hftbacktest/requirements.lock.txt
/private/tmp/tickwitness-s01-hft/.venv/bin/python research/spikes/hftbacktest/run_fixture.py --output-dir /private/tmp/tickwitness-s01-hft/reproduce-a
/private/tmp/tickwitness-s01-hft/.venv/bin/python research/spikes/hftbacktest/run_fixture.py --output-dir /private/tmp/tickwitness-s01-hft/reproduce-b
cmp /private/tmp/tickwitness-s01-hft/reproduce-a/trace.json /private/tmp/tickwitness-s01-hft/reproduce-b/trace.json
```

`cmp` 的退出码 0 表示这两份规范化 trace 逐字节相同。脚本断言最终持仓、成交次数、gross cash 与费用；失败会以非零退出码结束。浮点费用采用 `1e-12` 绝对容差。该检查不保证跨平台、任意策略或任意模型确定性。

如只核验本次已提交记录，可执行：

```sh
cmp research/spikes/hftbacktest/results/run-a/trace.json research/spikes/hftbacktest/results/run-b/trace.json
shasum -a 256 research/spikes/hftbacktest/results/run-a/trace.json research/spikes/hftbacktest/results/run-b/trace.json
```

## 记录结构

- [run_fixture.py](run_fixture.py)：8 条合成输入，其中 6 条业务事件、2 条尾部 guard；2 次决策；在 feed/order-response 边界轮询订单和资金状态。
- [capture_metadata.py](capture_metadata.py)：读取已下载的官方 PyPI JSON，保存 wheel 文件信息与已安装源码/二进制哈希；不自行联网。
- [release-metadata.json](results/release-metadata.json)：官方 2.4.4 文件清单及本机安装信息。
- [comparison.json](results/comparison.json)：两次规范化 trace 的哈希与逐字节比较结果。
- [第一次 trace](results/run-a/trace.json)、[第二次 trace](results/run-b/trace.json)：输入、策略决策、14 个观测边界和汇总；环境记录在各自目录的 `environment.json`。

`available_input_ids` 是本 fixture 根据本地时间字段计算的可用事件集合，用于可检查的外部归因；不是引擎提供的原始事件 callback。`last_trades()` 表示公开市场成交，不能拿它冒充自己的 fill ledger。

订单的 `local_timestamp_ns` 来自上游 `Order.local_timestamp`，表示本地下单请求时间；响应被观察到的时间用外层 trace 的 `timestamp_ns` 表示。执行价格/数量字段只在 FILLED / PARTIALLY_FILLED 时有语义，早期状态中的默认零值不是成交记录。

本例每个订单只有一次 fill，因此能轮询到两个成交状态；它没有验证同时间多次部分成交的完整记录能力。数据结束时最后一条尾部 guard 尚未在本地可见，trace 如实保留终止时间；业务成交已在更早时刻完成。正式 adapter 必须补齐 EOF drain 契约测试。
