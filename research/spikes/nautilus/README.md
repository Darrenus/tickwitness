# NautilusTrader v1 可行性 spike

这是 S01-01 的独立研究试验，不是正式 adapter，不自动进入核心依赖或核心 CI。

- 选定版本：`nautilus-trader==1.231.0`，v1 stable API。
- 本机执行：CPython 3.12.14、macOS 27.0.1、arm64。
- 数据：脚本原创的 7 条合成 EURUSD L1 quote，无下载行情、账户、密钥或实盘连接。
- 完整结论与局限见 [可行性报告](../../../docs/research/nautilus-feasibility.md)。

## 重跑

先准备与 wheel 匹配的 CPython 3.12。以下命令从仓库根目录执行；环境和 uv 缓存全部放在临时目录。软件依赖来自官方 PyPI，运行 fixture 本身不访问网络。

```sh
UV_CACHE_DIR=/private/tmp/tickwitness-s01-nautilus/uv-cache uv venv --python python3.12 /private/tmp/tickwitness-s01-nautilus/venv
UV_CACHE_DIR=/private/tmp/tickwitness-s01-nautilus/uv-cache uv pip install --python /private/tmp/tickwitness-s01-nautilus/venv/bin/python --index-url https://pypi.org/simple --only-binary :all: -r research/spikes/nautilus/requirements.txt
/private/tmp/tickwitness-s01-nautilus/venv/bin/python research/spikes/nautilus/run_spike.py --output research/spikes/nautilus/results/macos-arm64-python312.json
/private/tmp/tickwitness-s01-nautilus/venv/bin/python research/spikes/nautilus/inspect_capabilities.py --output research/spikes/nautilus/results/installed-api-inventory.json
```

`requirements.txt` 是本次独立环境解析出的 15 个精确版本，不包含私有 index 或绝对路径；它不是全平台锁文件。其他平台先检查官方 wheel 的 Python ABI、系统版本和架构。macOS 的本次 stable wheel 要求 `macosx_26_0_arm64`。不允许在没有 wheel 时静默源码构建，因此使用 `--only-binary :all:`。

`run_spike.py` 会新建两个相同的 baseline engine，比较归一化语义结果；再执行一次额外 1.5 秒下单延迟的压力情景。输出保留 `baseline` 和 `baseline_repeat` 两份完整语义轨迹及各自哈希，不仅保留一个成功标记。随机事件 UUID、引擎 instance/run ID、墙钟耗时与日志不属于比较字段。

脚本使用断言检查输入/决策/fill 数量、仓位关闭、手算现金、两次语义一致及固定版本下的预期成交价格；请不要使用 `python -O`。时间戳统一为十进制纳秒字符串，价格、数量、现金保留十进制字符串。

## 已提交的小型证据

| 文件 | 内容 |
| --- | --- |
| [macos-arm64-python312.json](results/macos-arm64-python312.json) | 两次 baseline 全轨迹、延迟压力全轨迹、账户报告、安装版本与限制 |
| [installed-api-inventory.json](results/installed-api-inventory.json) | 本机 v1 公开成员、回调、扩展点存在性及安装源码哈希 |
| [pypi-1.231.0-metadata.json](results/pypi-1.231.0-metadata.json) | 2026-10-25 从官方 PyPI JSON 读取的版本、许可及 12 个 wheel 元数据 |

PyPI 元数据文件是发布信息记录，不是本轮完成 Sigstore/attestation 验证的凭据。API 存在性不等于行为验证，两个同机重跑不等于跨平台支持认证，也没有性能 benchmark 结论。

本次代码与合成 fixture 为 TickWitness 原创；NautilusTrader 本身按上游 LGPL-3.0-or-later 许可安装，没有复制或重新许可其二进制。
