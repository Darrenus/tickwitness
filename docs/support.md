# 0.1 技术预览支持范围

适用版本：已发行的`0.1.0a1`技术预览，固定源提交、CI与原制品见[发布记录](releases/0.1.0a1.md)。没有PyPI发布。`0.2.0.dev0`是后续开发分支，其新增场景校验及耦合回放时钟压力执行不属于0.1发行物；开发检查以对应PR实际结果为准。场景回执仅支持ledger持久化及独立复核；旧八角色bundle导出只支持baseline。

## 按任务划分的环境矩阵

以下是现有 [Engineering CI](../.github/workflows/engineering.yml) 配置对应的验收组合。只有候选 commit 的实际 job 成功后，才能在发布记录中记为该组合通过；历史 PR 成功或配置存在不能替代本候选的结果。

| 任务 | CI 环境 | Python | 依赖与验收范围 |
| --- | --- | --- | --- |
| 核心工程回归 | `ubuntu-24.04`、`macos-15` | 3.12 / 3.13 / 3.14 | 不安装可选引擎；数据、声明、证据、CLI 与文件系统回归；native case 的 skip 不算原生通过 |
| 核心发行物安装 | `ubuntu-24.04` | 3.12 | 干净环境/不同工作目录安装 wheel，执行核心安装 smoke 与离线核验 |
| 原生回放及安装后完整链路 | `ubuntu-24.04`、`macos-26` | 3.12 | 精确 `nautilus-trader==1.231.0`；原生测试及 wheel 安装后的受监督 CLI 回放、导出、迁移核验 |

runner 标签不是所有 CPU 架构、发行版或文件系统的认证。实际架构、解释器、依赖与 job 链接须保留在发布证据中；未在候选记录中验证的组合属于未验证。核心包的 `py3-none-any` wheel 标签同样不表示所有操作系统均支持安全文件 IO。

文件存储依赖 POSIX directory fd、no-follow、regular-file 检查、hard link 与 fsync。原子目录发布只实现 Linux/macOS 的 no-replace 接口，缺少能力就明确失败。Windows、其他 OS、网络文件系统、云盘挂载、不同原生 Python 组合及上游源码编译不在本预览认证范围。macOS 原生 wheel 还须满足上游平台标签，不能把 macOS 15 的核心回归当作原生支持。细节见[开发入口](development.md)。

建议在符合矩阵的远端 CPU 主机或 GitHub Actions 上验收；当前受限工作流不要求 GPU，也没有 GPU 加速承诺。Colab 可作为临时手动验收环境，其运行时与本地磁盘可能回收；它不是 24×7 托管、数据持久性或本项目额外支持矩阵的保证。需要保留的原始数据、CAS、attempt ledger 和导出包应按 owner 的备份流程保存。

## 功能与模型边界

| 能力 | 本候选范围 |
| --- | --- |
| 数据导入 | 规范化 JSONL 的 snapshot/delta/trade；不是交易所原始 WebSocket 采集器。导入 accepted 不是回放许可或真实来源认证 |
| 声明 | v1 不可执行声明继续保持 `execution_ready=false`；v2 单独绑定受支持内置策略、数据、模型、估值与预算 |
| 回放 | 单流 EUR-USD、一次初始 snapshot、受支持的完整序列与 receive-order 时钟；内置 post-only 限价买单、MARGIN/NETTING；无用户 Python 策略执行 |
| 估值 | 最后观测 bid 的 USD marked PnL；不是平仓收益，没有模拟退出深度、冲击或退出费用 |
| 费用 | 对列明 native 费用数值模型独立复算；模式存在歧义时估值/claim 保持未知，不能凭一分钱容差放行 |
| 尝试预算 | 每个 protocol ID 的不可返还 attempt；失败与中断消费预算，不是跨协议的完整 trial family/exposure 账本 |
| 证据 | 固定目录包、完整性/绑定/账务复算；离线 verifier 不运行 native 撮合，不认证作者、真实市场成交、确认集或全部历史尝试 |
| 接口 | 文档列出的 CLI。Python 领域/应用接口仍在迭代，不提供广泛稳定公共 SDK 兼容保证 |

当前不提供反例搜索 finding、观测相容队列证书、确认集解封、实时交易、任意代码沙箱、checkpoint 恢复、HTTP/MCP/UI 或生产性能承诺。未来规划见[路线图](planning/roadmap.md)，不能将规划当作本版本能力。

回放硬上限仍为 8 MiB / 10,000 events；协议预算为最多 100 attempts、单次 native worker 最多 60 秒，具体协议可以更严格。wall budget 覆盖 worker 阶段，不覆盖导入、导出和全部验证总时长。导入与 bundle 的独立配额见[数据导入](data-import.md)和[bundle 契约](contracts/evidence-bundle-v1.md)。

## 信任与运行状态

本预览采用可信本地 owner 模式：owner 信任输入根和存储根的祖先配置，并使用自己有权处理的数据。平台应用入口拒绝确认集读取，但不能对宿主 owner 隐藏其文件。子进程提供崩溃/超时边界，不是恶意代码、凭据、网络或宿主文件系统的安全沙箱。

`completed`、`claim_observation.eligible` 和 `satisfied` 分别描述执行结束、是否可评价及是否满足冻结阈值。incomplete、费用歧义、错误或预算终止不能变成研究通过。`reserved_unfinalized` 表示终态未知，不能解释为失败已确认或预算可退款。

## 兼容、升级与回退

预览阶段 CLI/schema 仍可能变化；所有已声明的格式与领域语义分别版本化。兼容范围以该发行的记录和 fixture 回归为准，不以包版本号推断新 loader 可以理解所有旧对象，也不承诺自动迁移。

1. 升级前停止对相关目录的写入，备份完整 catalog、CAS、registry、attempt ledger 与已导出 bundle，保留旧解释器环境和安装制品。
2. 将新版本装入独立环境；用原始导出包和新的独立工作目录验收。不要删除或重写旧 CAS 对象、旧协议、slot、outcome 或 bundle manifest。
3. 不支持旧格式时应明确拒绝并保留原件。未来转换应生成新对象和新的来源记录，不能原地重解释旧证据。
4. 回退使用保留的旧安装环境与匹配的完整备份；不要把新旧版本的可变 catalog 或 ledger 混合。新版本产生的未知格式不能假设旧版可读。

本预览没有自动备份、通用迁移、跨版本恢复或真实断电认证。导出目标已存在时不覆盖；发布后若返回持久性未确认，先验证已存在目标并保留诊断，再决定恢复路径。

## 获取帮助

普通缺陷通过 [GitHub Issues](https://github.com/Darrenus/tickwitness/issues) 提交：版本/commit、OS/Python、相关 schema/engine ID、命令、退出码，以及可公开的最小合成复现。不要上传私有行情、策略、凭据或未经许可的完整证据包。安全问题按 [SECURITY](../SECURITY.md) 私密报告。

维护者按可用时间处理预览问题，不提供 24×7、付费 SLA、长期维护期限或修复日期保证。尚无独立人类领域复核和真实采用证明时必须保留相应缺口，不能把 AI 审阅或自动测试称作外部认证。
