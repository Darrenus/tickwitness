# 0.1.0a1 技术预览快速开始

`v0.1.0a1`技术预览已在[GitHub Releases](https://github.com/Darrenus/tickwitness/releases/tag/v0.1.0a1)发布，没有上传PyPI。先查看[发布记录](releases/0.1.0a1.md)和[支持范围](support.md)。以下命令固定发行tag，在**远端受支持主机**运行，首选原生矩阵中的Ubuntu 24.04 / Python 3.12；不要求GPU。Colab仅适合临时验收，不承担长期任务和持久存储。当前开发分支的新增场景检查另见[场景指南](scenarios.md)。

## 选择固定发行代码

安装uv 0.12.13和Git。发行tag指向已接受且通过远端检查的`a84edddef00db8af69c7e6e67be31f0763310dca`，不要用移动中的main替代：

```sh
git clone --branch v0.1.0a1 https://github.com/Darrenus/tickwitness.git
cd tickwitness
git checkout --detach a84edddef00db8af69c7e6e67be31f0763310dca
```

本页使用固定checkout中的`uv.lock`和原创`examples/`。wheel仅包含Python包，安装wheel不会自动创建这些样例；发行源码包另包含锁文件、样例、文档与开发脚本。只拿到wheel时，应同时取得发行记录指定的源码包/样例来源，不能从移动中的main混搭文件。PyPI没有对应发行，不使用`pip install tickwitness==0.1.0a1`作为取得方式。

## 核心安装与离线核验

先在远端 `/tmp` 建立不安装 Nautilus 的独立核心环境；若这些路径已有别的环境，应换一个新的绝对路径。环境放在 checkout 外，避免污染源码及文档扫描目录：

```sh
TW_CORE_ENV=/tmp/tickwitness-preview-core
UV_PROJECT_ENVIRONMENT="$TW_CORE_ENV" uv sync --locked --python 3.12
"$TW_CORE_ENV/bin/python" -I -m tickwitness --version
"$TW_CORE_ENV/bin/python" -I -m tickwitness verify-evidence examples/evidence-demo
```

版本应为`tickwitness 0.1.0a1`。核验命令直接使用已安装环境，不进行uv依赖同步；完成安装和样例取得后，此核验不需要网络、Nautilus、原始catalog或原attempt ledger。输出的`bundle_id`应与发行记录固定的样例ID相同。哈希自洽不能替代从可信来源取得预期ID。

样例来自本仓库原创合成行情和固定 native 回放，预期回执为 `accounting_verified=true`、`native_replayed=false`。它证明该 profile 内的输入绑定和账务复算一致，不证明日志来自真实交易所、作者身份或撮合已重新执行。不要向严格 bundle 目录加入 README、隐藏文件或其他对象。

## 创建一次真实合成回放

在同一 checkout 中建立另一个原生环境，保留核心 verifier 环境：

```sh
set -eu
TW_NATIVE_ENV=/tmp/tickwitness-preview-native
UV_PROJECT_ENVIRONMENT="$TW_NATIVE_ENV" uv sync --locked --extra nautilus --python 3.12
TW="$TW_NATIVE_ENV/bin/tickwitness"
"$TW" --version
TW_DEV=$("$TW" import-events replay-partials.jsonl --input-root examples --store .local/preview-data --id-only)
TW_CONFIRM=$("$TW" import-events replay-confirmation.jsonl --input-root examples --store .local/preview-data --id-only)
TW_PROTOCOL=$("$TW" freeze-experiment experiment-request.json --input-root examples --development-dataset "$TW_DEV" --confirmation-dataset "$TW_CONFIRM" --store .local/preview-data --registry .local/preview-experiments --id-only)
TW_RUN=$("$TW" replay-protocol "$TW_PROTOCOL" --store .local/preview-data --registry .local/preview-experiments --runs .local/preview-runs --id-only)
"$TW" inspect-run "$TW_RUN" --store .local/preview-data --registry .local/preview-experiments --runs .local/preview-runs
mkdir -p .local/preview-exports
"$TW" export-evidence "$TW_RUN" .local/preview-exports/baseline --store .local/preview-data --registry .local/preview-experiments --runs .local/preview-runs
mv .local/preview-exports/baseline .local/preview-exports/relocated
"$TW_CORE_ENV/bin/python" -I -m tickwitness verify-evidence .local/preview-exports/relocated
```

在完成核心安装的同一 shell 中运行这段命令；`set -eu`让失败立即停止，避免把空 ID 传入后续步骤。这些命令使用真实应用、存储和可选原生引擎，不连接交易所，不执行用户源码。只对 development 回放；confirmation 仅在冻结时检查分区关系，观测不进入导出包。首次使用新的 `.local/preview-*` 目录；再次执行 replay 会消费新 attempt，已有导出目标不会被覆盖。

例子两笔各成交 1 EUR、价格 100 USD、费用各 1 USD；最后观测 bid 为 100，`net_marked_pnl=-2`。冻结声明为 `>0`，所以预期 `eligible=true, satisfied=false`。这不是平仓收益，没有退出费用、退出深度或冲击模拟，也不是搜索找到的反例。完整字段和费用歧义边界见[证据工作流](evidence-workflow.md)。

## 检查拒绝与失败

确认集访问应退出 5，且不创建下列仓库目录：

```sh
if "$TW" replay-protocol "$TW_PROTOCOL" --split confirmation --store .local/must-stay-absent/data --registry .local/must-stay-absent/experiments --runs .local/must-stay-absent/runs; then
  echo 'Unexpected confirmation access' >&2
  exit 1
else
  TW_EXIT=$?
  test "$TW_EXIT" -eq 5
fi
test ! -e .local/must-stay-absent
```

这个非零退出是预期拒绝，不是安装失败。没有 native 依赖的核心环境尝试执行回放时返回引擎不可用；只要预检已通过并预留 attempt，该失败仍消费预算。其他错误应按退出码和 stderr JSON 处理，不能在命令失败后继续使用空的 shell ID。

| 退出码 | 处理含义 |
| --- | --- |
| 2 | 输入、协议或证据不合法；CLI 参数语法错误也为 2 |
| 3 | 存储/完整性/发布错误，或发布后持久性未确认 |
| 4 | 引用或目录不存在 |
| 5 | 确认集拒绝 |
| 6 | 原生引擎环境不可用 |
| 7 | 运行失败；查看返回的 attempt ID |
| 8 | 协议 attempt 预算已耗尽 |

发生已消费尝试的错误后，保留错误中的 `attempt_id` 并检查：

```sh
"$TW" inspect-attempt REPLACE_WITH_ATTEMPT_ID --runs .local/preview-runs
```

`reserved_unfinalized` 表示未确认终态，预算不能退款。导出后 parent fsync 未确认时，目标可能已经完整存在；先核验该目录，不删除或覆盖重试。升级、回退、可信 owner 和未支持能力见[支持政策](support.md)。
