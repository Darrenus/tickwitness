# Tagged Pair Evidence v1：可迁移的双模型证据闭包

状态：S06-02c 功能与远端验收已完成，[PR #86](https://github.com/Darrenus/tickwitness/pull/86) 待 owner 接受。基线为 owner 已合并的 [PR #85](https://github.com/Darrenus/tickwitness/pull/85)，merge `dcf38714b5ee306e9328f1ad25624fc687f036e8`。本合同承接 [Tagged Queue v1](tagged-queue-v1.md)，决策见 [ADR 0019](../adr/0019-portable-tagged-pair-evidence.md)，实际验收记录维护于 [Sprint 6](../planning/sprint-06-status.md#s06-02c-远端验收记录)。

本切片将两个已提交 run 封装为可移动目录，随后在只有 core wheel 的环境重新计算来源、守恒、原生回调账务及配对关系。它不运行 native，不连接原 catalog／registry／ledger，也不把 frozen protocol 中的 `finding_issued=false` 改成 true。新命题的同／异真值关系仍只限于声明的有限 tagged reconstruction，findings 保持空数组。

## 用户流程与可重复身份

从已冻结、已完成的 tagged pair 开始。在受信任且已存在的父目录下选一个不存在的输出路径：

```sh
tickwitness export-tagged-queue-pair FRONT_RUN_ID BACK_RUN_ID \
  --store /path/to/data --registry /path/to/registry --ledger /path/to/ledger \
  --output /path/to/exports/tagged-pair

mv /path/to/exports/tagged-pair /path/to/another-machine/relocated

tickwitness verify-tagged-queue-pair /path/to/another-machine/relocated \
  --expected-bundle-id BUNDLE_ID
```

执行 native 的环境与离线核验环境可以不同；离线环境只需安装 core。`--expected-bundle-id` 为可选的小写 SHA-256 pin；需可信出处的调用者应在另一条可信渠道取得该 ID。自算 hash 不认证作者。导出参数可反序提供，应用按冻结的 front／back policy 排序；同一批证据内容不因参数顺序、目录位置或导出次数改变身份。

两命令默认 `--split development`。confirmation 在 repository factories、证据路径读取和目标发布前拒绝。导出先从实际 ledger 核对 committed reservation／intent／receipt，重新读取 accepted development 数据并审计两个 run；没有新增 attempt，不启动 worker，不消耗重放预算。任一来源、回执或实际账务无效时不得发布成功证据包。既有输出目录即使为空或同内容也拒绝，重复导出使用另一目标。

离线 verifier 只读固定目录。原数据 store、注册表、attempt ledger 或 native 安装可以不存在；读取不恢复数据库、不初始化新 store、不连接网络、不导入 native、不调用 subprocess worker。应用重算 assessment，与包内封存字节完全相同才返回成功。它不依据包里自报的 `verified` 或真值布尔值直接放行。

## 固定目录、markers 与十二角色

```text
<bundle-root>/
  manifest.json
  objects/
    sha256/
      <lowercase SHA-256>
      ...
```

manifest markers 固定为 `kind=tagged_queue_pair_evidence_bundle_v1`、`schema_version=1`、`scope=development_tagged_queue_pair_v1`。结构与 [旧 bundle v1](evidence-bundle-v1.md) 使用相同的安全固定树原则，业务身份与 role 集合独立；旧八角色 reader 不接受新包，新 reader 不接收旧包。

每个 role 的引用严格为 `{sha256,size_bytes,ref}`，其中 `ref` 必须等于 `objects/sha256/` 加其 hash，size 为真正的正整数。manifest 为精确 canonical JSON，无未知／重复字段、浮点数、bool 冒充整数、BOM 或尾随换行。`bundle_id=SHA256(manifest canonical bytes)`；相同字节在不同位置得到相同 ID。

| role | 字节上限 | 业务内容 |
| --- | ---: | --- |
| `protocol` | 256 KiB | 完整 TaggedQueueProtocol，内嵌 source v2 与 gross 声明 |
| `dataset_manifest` | 64 KiB | 绑定的 development dataset manifest |
| `raw` | 8 MiB | 原始 development 输入 |
| `normalized` | 8 MiB | 对 raw 重新规范化可复算的事件字节 |
| `report` | 4 MiB | 可重新计算的数据质量报告 |
| `front_result` / `back_result` | 各16 MiB | 各自真实 native result，包括源、分配、订单、成交、账户、horizon／cleanup |
| `front_evaluation` / `back_evaluation` | 各64 KiB | 可从实际源及结果独立重算的评价 |
| `front_receipt` / `back_receipt` | 各1 MiB | 完整 tagged receipt，内嵌各自 intent 与 reservation |
| `assessment` | 256 KiB | 固定审计政策重建的双模型 assessment |

总量默认最多64 MiB，包含 manifest 与每个唯一 CAS 对象；最多32文件，manifest 最多64 KiB。跨 role 相同字节共享 CAS 对象；同 hash 不得声明不同 size。IO 上限不会放宽每个 domain loader 自己的限制。confirmation 观测没有 role；协议内的 confirmation ID 仍只是外部声明引用。

`TaggedPairArtifactBundle` 是 frozen 值对象，保存 immutable manifest bytes 和 immutable role／bytes tuple。公开 `.bundle_id`、`.manifest_bytes`、`.manifest`、`.artifacts`；后两个属性返回独立 view。直接构造同样检查严格 role、预算、大小和 hash 闭包，不能以 mutable bytearray 伪装冻结证据。

## 发布与读取失败边界

导出前验证全部 payload，再在打开的可信 parent 下建立0700私有 sibling stage。对象先写入并 fsync，最后发布 canonical manifest、同步目录，之后原子 no-replace rename 并 fsync parent。Linux／macOS 的 no-replace 接口与旧 bundle 保持同样安全边界；不降级成可以覆盖目标的普通 rename。

发布前失败不留下可用目标，私有未提交 stage 尽力清理。rename 后 parent fsync 失败则完整目标可能已可见，返回 `BundleDurabilityError` 并保留目标；不能声称可安全覆盖重试。并发导出争同一目标只允许一个提交。

读取完整枚举固定三层，目录／文件 no-follow 打开，文件须为 regular file，并使用 nonblocking open 拒绝 FIFO。未知、隐藏、缺失、额外文件／目录与 symlink 均拒绝；对象 size／预算先核，再读内容并核 SHA-256。不执行包内内容，不解析任意用户路径列表。可信 parent/root 祖先、恶意 owner、硬链接和真实断电的边界与旧 IO 合同相同，本轮不新增安全认证。

IO 复用 `BundleError`、`BundleNotFoundError`、`BundleDestinationExistsError`、`BundleDurabilityError` 和正整数 `BundleLimits`。CLI 沿用缺失4、目标冲突／IO3、semantic evidence 无效2、confirmation5的分类；无效证据不能被报告为命题 false 或 verified。

## 离线语义重建

重建按下列依赖顺序进行：

1. 检查固定 role 与不可变字节、protocol 完整内容及其身份。
2. 校验 dataset manifest 绑定到该协议的 development ID，raw／normalized／report 引用闭合；重新从 raw 生成规范化和完整质量报告，拒绝 quarantined 或不复现的内容。
3. 按冻结 source ReplaySpec 构造实际 ReplayInput，验证两种 protected-tagged 政策均可行，重建 witness pair。
4. 分别加载真实 result、完整 receipt／intent／reservation；核对 policy、协议、新 claim revision、输入／spec／gross、result／evaluation digest 与完成状态。
5. 独立重算每笔 trade 的单次分配、实际授予／成交、订单回执、费用／账户前缀以及估值前 horizon 与后续 cleanup；封存 evaluation 必须逐字节复现。
6. 检查两次 reservation 属同一协议、各自预算字段符合冻结值，attempt ID 与 attempt index 均不同；同一 attempt 不能伪装两种政策。
7. 重建固定 assessment 并与封存字节比较。即使重算外层所有 hash，错误 flow、资金、费用、时钟、命题或 horizon 仍须失败。

两个 receipt 的存在只能证明包里这两个 reservation 的字段一致性。离线没有原 ledger，不能证明它们曾在某台机器 committed、没有遗漏其他尝试、预算历史完整、作者可信或统计多重检验已解决。导出时查询过原 ledger 与离线认证完整 ledger 是两个不同承诺。

## Assessment 与未知状态

`tagged_queue_pair_assessment_v1` 的固定 `audit_policy=tagged_queue_pair_offline_audit_v1`，绑定全部其余十一 role 的 hash，保存 protocol／claim／dataset／witness pair 身份、固定模型与 scope。按 front／back policy 的每份 run 保留 run／attempt／intent ID、attempt index、result／evaluation hash、truth、valuation 与实际 horizon。

`comparison` 只报告：

- 两侧都 eligible 且实际 execution environment 的 canonical JSON 相同：`same_truth_value` 或 `opposite_truth_values`。
- 费用歧义或命题不可评价：`relation=ineligible`，真值保留 null，原因 `claim_evaluation_ineligible`。
- 实际执行环境不同：保留各自独立审计，配对 `relation=ineligible`，原因 `execution_environment_mismatch`。

完整终止但无成交，继续按已冻结 flat-zero 政策评价为0，不能把无成交和未知混为一谈。标准 bid100／gt0 的要求为 F/F；另一份冻结的 bid102／gt0 为 T/F；bid102／ge0 为 T/T。所有案例使用原创 synthetic 数据；这些是运行前确定的 oracle，远端通过记录另行登记。

模型错误、非法输入、缺件、篡改或坏回执是验证错误，不能转成 false、`INSUFFICIENT_EVIDENCE` 或 `NOT_IDENTIFIABLE_WITHIN_MODEL`。`findings=[]` 保持冻结权限；同真值不证明所有模型可识别，异真值也不在本切片签发最终 finding。

## 验证回执

`export-tagged-queue-pair` 和 `verify-tagged-queue-pair` 返回同一可移交验证回执，内容含 `bundle_id`、`assessment_id`、完整 assessment 及 `kind=tagged_queue_pair_offline_verification_v1`、`schema_version=1`。

| 字段 | 固定含义 |
| --- | --- |
| `integrity_verified=true` | 本次读取的固定树、大小、预算与 hash 闭包通过 |
| `bindings_verified=true` | 源、协议、命题、policy、intent、reservation 和结果绑定复现 |
| `source_revalidated=true` | 从封存 raw 重新规范化并核对质量报告 |
| `queue_execution_audited=true` | 独立守恒、原生回调账务和 horizon／cleanup 审计复现 |
| `native_replayed=false` | 没有再次调用撮合；不认证日志真实出处 |
| `author_signature_verified=false` | 没有作者签名认证 |
| `confirmation_reference_checked=false` | 未访问或解封 confirmation 观测 |
| `full_attempt_ledger_checked=false` | 没有完整试验历史或预算账本认证 |
| `ledger_commitment_checked=false` | 离线闭包不证明 receipt 曾由原 ledger 提交 |

回执不包含剩余预算估计，不为实际新插单、历史所有权、市场冲击、退出可成交性或未来收益背书。新 finding 授权、确认集 lifecycle、跨协议试验账本与外部人类复核仍是后续门。
