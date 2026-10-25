# 从冻结协议到可迁移证据

`import → freeze → replay → export → verify`已接为同一application链路，并随`v0.1.0a1`技术预览发行；实际制品见[预览说明](releases/0.1.0a1.md)。当前分支`0.2.0.dev0`开发版保留该链路，另新增只读[场景契约校验](scenarios.md)，不把它当作场景执行。回放支持范围仍是EUR/USD、内置post-only限价买单、开发集baseline与最后观测bid估值，不执行任意Python策略，不解封确认集，也不进行反例搜索或全市场收益认证。发行版安装请看[quickstart](quickstart.md)，环境边界见[支持矩阵](support.md)。

## 先离线验证随附样例

```sh
uv sync --locked
uv run --locked tickwitness verify-evidence examples/evidence-demo
```

`examples/evidence-demo`由安装后的真实native wheel通过下述CLI生成，使用本仓库原创合成行情；不是伪后端路径。它包含完整development输入、结果和账务证明材料，离线核验无需Nautilus、交易所、原catalog或本地attempt ledger。原始回执与目录一起移动后仍可核验，不要向固定目录结构中添加README、隐藏文件或其他对象。

## 在空工作目录跑完整链路

安装[开发入口](development.md)所列uv与Python，先clone仓库。以下从仓库根运行，仅在新建的`.local`下产生私有运行数据：

```sh
set -eu
uv sync --locked --extra nautilus
TW_DEV=$(uv run --locked --extra nautilus tickwitness import-events replay-partials.jsonl --input-root examples --store .local/data --id-only)
TW_CONFIRM=$(uv run --locked --extra nautilus tickwitness import-events replay-confirmation.jsonl --input-root examples --store .local/data --id-only)
TW_PROTOCOL=$(uv run --locked --extra nautilus tickwitness freeze-experiment experiment-request.json --input-root examples --development-dataset "$TW_DEV" --confirmation-dataset "$TW_CONFIRM" --store .local/data --registry .local/experiments --id-only)
TW_RUN=$(uv run --locked --extra nautilus tickwitness replay-protocol "$TW_PROTOCOL" --store .local/data --registry .local/experiments --runs .local/runs --id-only)
uv run --locked --extra nautilus tickwitness inspect-run "$TW_RUN" --store .local/data --registry .local/experiments --runs .local/runs
mkdir -p .local/exports
uv run --locked --extra nautilus tickwitness export-evidence "$TW_RUN" .local/exports/baseline --store .local/data --registry .local/experiments --runs .local/runs
mv .local/exports/baseline .local/exports/relocated
uv run --locked tickwitness verify-evidence .local/exports/relocated
```

导出目标的parent必须已存在，目标自身必须不存在。重复freeze幂等；每次replay都是新的已消费attempt。重复export到同一目标明确拒绝，永不覆盖。新路径或删除后重新导出并不创建新的研究运行，也不改变已有run ID。

例子两次各买入1 EUR、100 USD、实际maker费各1 USD，最后观测bid为100；gross未实现价差为0，已付费用为2，`net_marked_pnl=-2`。声明阈值为`>0`，所以回执为`eligible=true, satisfied=false`。这只描述固定开发集与baseline，不是搜索得到的全局判定，也不是已实现清仓收益；最后bid可见量可能小于持仓，未模拟退出深度、冲击或退出费用。该profile的realized字段只指平仓价差利润，费用单独列账并在net marked中扣除。

## v1与v2的边界

原有`freeze-protocol`/`inspect-protocol`/`read-protocol-data`仍使用[不可执行v1声明](contracts/frozen-protocol-v1.md)。本批新增的`freeze-experiment`使用[ExecutableProtocol v2](contracts/executable-protocol-v2.md)：固定内置策略、engine语义、完整ReplaySpec、claim、开发/确认dataset引用、估值政策与预算；没有把v1的`execution_ready=false`改成true或提供override。

费用、参数、数据或预算变化产生新protocol；命题内容变化才产生新claim revision。可执行资格仍需应用核验真实数据、结构/序列报告、严格向前不交叠分区、receive时钟与盘口，以及冻结event budget。只有development会被执行；`replay-protocol --split confirmation`在任何repository初始化前退出5。导出也先核对run绑定的dataset确为该协议development，才读取行情；确认集观测不进入bundle。

## attempt预算与失败记录

冻结预算是每协议`max_attempts=1..100`、`max_wall_seconds=1..60`、`max_events=1..10000`。event预算在预检验证；wall预算限制native worker阶段，包含该阶段的启动/懒加载，不是导入、freeze、导出、验证总时长。CLI不能用额外参数放宽已冻结预算。

完成预检后、构造引擎前，原子占用一个不可退款slot。native缺依赖、错误、超时或审计失败都留下failed终态；中断或进程崩溃可能留下`reserved_unfinalized`，预算仍已消费，不将未知状态伪称为已失败或允许退款。错误JSON提供`attempt_id`与`budget_consumed=true`，可查看：

```sh
uv run --locked tickwitness inspect-attempt <attempt-id> --runs .local/runs
```

成功或诚实incomplete的运行可通过`inspect-run`重验账务与引用；不合格估值的claim为null。预算耗尽退出8。改参数或预算会生成新protocol，但这不提供experiment family级防绕过机制；本批ledger不是完整统计trial/exposure账本，不能用于宣称已解决自适应多重检验或holdout泄漏。

## 独立核验的范围

verify依次核验[固定目录与哈希闭包](contracts/evidence-bundle-v1.md)，重新从raw计算normalized/report，加载v2协议和结果，逐项核对源输入/订单/成交/缓存账户，独立重算[费用与最后bid估值](contracts/evaluation-v1.md)，再核对claim observation与完整run receipt。重写所有hash不能把与源数据、费率或现金/持仓相矛盾的材料变成有效账务证据。

固定native费用链包含两次USD Money量化；审计用精确有理数模拟IEEE binary64操作，而不是给误差留一分钱宽界。结果未绑定native raw precision mode时同时考虑两种模式，不能依据自报费用选择模式。费用候选不唯一时`fee_model_verification=ambiguous`，估值与claim保持未知，即使native回放completed也不会放行。候选唯一时，一分钱费用篡改、同步改写现金或虚构改善成交价均被拒绝。

验证回执明确：

| 字段 | 含义 |
| --- | --- |
| integrity/bindings/accounting_verified | 在声明profile内，制品、源绑定、独立账务与评价复算通过 |
| fee_model_verification | 费用数值模型唯一可核验、存在歧义或不适用 |
| native_replayed=false | verifier没有重新执行撮合，不能证明native日志真实性 |
| author_signature_verified=false | hash不是作者认证；需要可信bundle ID时必须另行固定预期身份 |
| confirmation_reference_checked=false | 确认集只保留外部hash引用，未携带或验证其观测 |
| full_attempt_ledger_checked=false | 单包不能证明所有历史attempt或完整预算账本 |

没有签名、可信执行证明或native重放时，完整重造一套自洽合成数据和轨迹仍可能形成另一份一致性证据；本回执不把它认证为真实市场成交。也不输出S6相容队列证书或S7搜索finding，当前scope固定`development / baseline_v1 / search_performed=false`。

## 文件系统与错误语义

bundle只允许目录和固定JSON/CAS对象，不接收压缩包、pickle、恢复脚本或动态插件。读取拒绝越界引用、symlink/FIFO、额外/隐藏对象、文件数和总大小超限；迁移不依赖绝对路径。导出先写同parent的私有stage、持久化对象和manifest，再用Linux/macOS原子no-replace发布，竞争导出也不能覆盖新出现的用户空目录。

提交前I/O/ENOSPC失败不会留下可用最终manifest。原子发布后若parent fsync失败，目录可能已完整可读，退出3并标`bundle_durability_unconfirmed`；不会删除它或承诺断电持久性。先verify现有目录，再选择恢复方式，不盲目覆盖重试。

常见退出码：2为无效协议/输入/证据，3为存储/发布/完整性或持久性未确认，4为身份/目录不存在，5为确认集拒绝，6为引擎不可用，7为已记录运行失败，8为attempt预算耗尽。`completed`只指该执行范围，claim是否可评价和是否满足阈值分开表达。
