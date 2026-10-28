# Confirmation Access v1

状态：S08-02 已由owner合并 [PR #93](https://github.com/Darrenus/tickwitness/pull/93) 接受，merge `97822d7a74931a829bd3355fb40d85d4504de59d`；[远端验收](../planning/sprint-08-status.md#s08-02-远端验收记录) 保持原范围。决策见 [ADR 0026](../adr/0026-one-shot-confirmation-exposure.md)。

本合同新增独立冻结与一次整窗确认**观测交付**。它不执行策略、不调用 native、不评价源 claim、不签发 confirmation finding，也不消耗旧执行 attempt 或 campaign 预算。既有 [Frozen Protocol v1](frozen-protocol-v1.md) 与 executable v2 的探索 `split=confirmation` 拒绝保持生效。

## 1. 使用流程

先通过已有 import/freeze 入口绑定实际数据与源协议。在包含这些 accepted 数据的同一个受管理 store 内使用：

```sh
tickwitness freeze-confirmation-protocol SOURCE_ID confirmation-request.json \
  --input-root inputs --store data --registry source-protocols
tickwitness inspect-confirmation-protocol CONFIRMATION_PROTOCOL_ID \
  --store data --registry source-protocols
tickwitness open-confirmation-protocol CONFIRMATION_PROTOCOL_ID \
  --store data --registry source-protocols
```

`--registry` 始终指向原 frozen v1 或 executable v2 源 registry。新确认声明与暴露状态固定在 `data/confirmation-state`；没有 `--exposure-path`、`--limit`、override、reset 或改名重开 flag。Freeze 另支持 `--id-only`。Opening 的完整内容 ID 是本次整窗许可的 pin，不由路径或实验名称替代。

请求必须且只能含：

```json
{
  "kind": "confirmation_request_v1",
  "schema_version": 1,
  "title": "A declared one-shot synthetic observation window",
  "max_events": 1000
}
```

请求上限64KiB；title 为无首尾空白、无控制字符的有效非空 Unicode，最多200字符；`max_events` 是真正 integer 1..1000。实际确认窗口必须含 `1..min(request.max_events, source.budget.max_events)` 条观测，超限整体拒绝。一次开启返回全部窗口，`truncated=false`；不能先取前缀再以新名称取得后缀。

## 2. 纯值与来源身份

`domain.research_contracts.confirmation` 仅使用标准库定义 immutable `OriginFootprint`、`ConfirmationProtocol`、`ConfirmationExposure`，均保存 identity 与 canonical bytes，`.document` 每次返回独立 view。Identity 为规范化 UTF-8 JSON bytes 的 SHA-256。严格 loader 重建 exact schema、所有绑定、hash 和固定 policy；未知字段、重复 key、非 canonical 文档、bool 假冒 integer、非法 Unicode、浮点或非有限值均不获得许可。

公开 API 为 `origin_footprint(records)`、`load_origin_footprint(bytes)`、`footprints_overlap(left,right)`、`build_confirmation_protocol(request, source_protocol=..., confirmation_normalized=...)`、`load_confirmation_protocol(bytes)`、`build_confirmation_exposure(protocol)` 与 `load_confirmation_exposure(bytes)`。`ConfirmationValidationError` 继承 `ProtocolValidationError`；`ConfirmationAlreadyExposed(PermissionError)` 附真实 `.exposures` tuple。

Footprint exact schema：

```json
{
  "kind": "confirmation_origin_footprint_v1",
  "schema_version": 1,
  "identity_policy": "source_instrument_session_trade_id_or_closed_book_interval_v1",
  "streams": [
    {
      "source": "synthetic",
      "instrument": "TEST-USD",
      "session": "confirmation-smoke",
      "trade_ids": ["confirmation-trade"],
      "book_intervals": [[20, 24]]
    }
  ]
}
```

streams 按 `(source,instrument,session)` 词典序排列；trade IDs 排序去重；book intervals 排序并合并交叠及相邻区间。snapshot 的来源是 `[last_sequence,last_sequence]`，delta 是完整闭区间 `[first_sequence,last_sequence]`，trade 是 trade ID。相同 stream 任一 trade ID 或 book 区间相交即冲突；不以 trade 的价格/数量或 book payload 代替来源身份。

Raw 排版、键顺序、capture_seq、event/receive time、市场 payload、切片、superset、book 区间重分段均不能把交叠来源变成未暴露。不同来源标签之间没有自动等价推断；本合同不认证 source/session 未被伪造，不构建任意数据变换的 lineage DAG。

## 3. 冻结确认声明

`confirmation_protocol_v1` exact 顶层为 `kind`、`schema_version`、`title`、`source_protocol`、`bindings`、`origin_footprint`、`read_policy`、`scope`。

`source_protocol` 保存完整严格 frozen v1 或 executable v2 文档。`bindings` 必须且只能含：

| 字段 | 绑定 |
| --- | --- |
| `source_protocol_id` | 完整源声明 canonical SHA-256 |
| `source_claim_revision_id` | 原 claim revision |
| `development_dataset_id`、`confirmation_dataset_id` | 源声明原 dataset 引用 |
| `confirmation_normalized_sha256` | 实际完整确认 normalized bytes |
| `confirmation_event_count` | 完整确认事件数 |
| `origin_footprint_id` | 内嵌规范化 footprint 内容 ID |

`read_policy` exact 为 `{id: "single_full_window_open_v1", max_events: N, exposure_policy: "irreversible_origin_overlap_before_release_v1"}`。

所有协议与回执固定使用以下 scope，不允许增加隐含认证：

```json
{
  "observation_release_only": true,
  "engine_execution_authorized": false,
  "source_claim_evaluated": false,
  "confirmation_finding_issued": false,
  "historical_unseen_certified": false,
  "author_signature_verified": false
}
```

应用服务 `freeze_confirmation_protocol`、`inspect_confirmation_protocol`、`open_confirmation_protocol` 接受 `source_factory`、`datasets_factory`、`confirmations_factory`、`exposures_factory` 无参 ports。Freeze 另接受 request bytes 与 `source_protocol_id`；inspect/open 接受确认 protocol ID。

创建可写新状态前，应用重验真实 source record identity、源策略实际 verified registry 引用、两份 accepted 数据、forward-disjointness、完整确认 SHA/count 与 footprint。结构验证可读取确认字节，但 freeze/inspect 不向调用者返回观测或结果，不证明声明先于任何人查看数据。

Freeze/inspect 回执 exact 为 `kind="confirmation_protocol_receipt_v1"`、`schema_version=1`、`protocol_id`、`created`、`document`、`exposure_status`、排序的 `related_exposure_ids` 和上述 `scope`。`exposure_status` 只能是 `NO_MATCHING_EXPOSURE_IN_LEDGER` 或 `ALREADY_EXPOSED_IN_LEDGER`；前者只描述当前账本未发现交集，不认证历史未见。相同内容重复 freeze 不创建新声明；改 title/source 可能生成新 ID，暴露判定仍依据来源交叠。

## 4. 提交后才交付

已冻结声明与账本核验后，如已交叠，open 直接拒绝，不再读取确认数据。未发现交叠不等于许可：重验来源与完整窗口之后，账本必须在同一锁与事务边界内再次检查，并先持久提交暴露。只有 atomic replace 与 fsync 成功后才能交付观测。

Exposure exact schema 为 `kind="confirmation_exposure_v1"`、`schema_version=1`、`state="EXPOSED"`、`confirmation_protocol_id`、`source_protocol_id`、`confirmation_dataset_id`、`confirmation_normalized_sha256`、`origin_footprint_id`、完整 `origin_footprint`、`policy="irreversible_origin_overlap_before_release_v1"`。内容 hash 为 exposure ID。没有时间戳、nonce、退款或成功输出字段。

成功 open 回执 exact 为 `kind="confirmation_observation_release_v1"`、`schema_version=1`、`protocol_id`、`dataset_id`、`exposure_id`、实际 `exposure` 文档、全部 `observations`、`total_records`、`truncated=false` 与固定 `scope`。不产生另一个 confirmation finding 或 pristine-history 结论。

暴露表示保守消费，**不证明观测实际到达任何人**。在 commit 后读取、port receipt 校验、输出或进程中断失败，均保留已暴露状态，不返回成功回执、不退款；重试不能重开。新实验名称、源协议、原 registry 与交叠派生窗口同样继承状态；不相交窗口可以各自首开。

## 5. 固定共享账本与 IO

`LocalConfirmationRegistry(dataset_root, create=False)` 固定使用 `dataset_root/confirmation-state/protocols`，支持 `get` 和 `seal`；仅发布 domain 验证的 exact bytes，采用 immutable no-replace 发布。`LocalConfirmationExposureLedger(dataset_root, create=False)` 固定使用同根 `confirmation-state`，公开 `find_conflicts`、`expose` 与 readonly `entries()`。

所有暴露记录存于一个 canonical `exposures.json`，只初始化一次为精确空 log。逻辑 append-only，最多256记录、文件最多32MiB；每 exposure 与 protocol 最多3MiB，footprint 最多2MiB。所有扫描及读取有界、no-follow、只接受 regular files。全账本线程锁加进程 flock 覆盖冲突重查、提交与相关 fsync。

dataset root 中的 `.confirmation-state-initialized` anchor 先于状态初始化落盘，用于检测整份状态目录意外丢失；存在 anchor 却缺状态，或存在状态却缺 anchor，都不得重新初始化为空。`.initializing`、`.pending-exposure` 或 `.exposure-next` 残留表示初始化／提交尚未完成或 durability 不确定，后续访问整体拒绝。Exposure 提交先持久写 pending，再写完整 next log、原子替换和同步，最后移除 pending 并同步；不对残留标记做自动清除。

未知、损坏或缺失的必需 log、lock 或结构目录不能解释为空；unsafe／oversize 文件与不确定提交状态 fail closed。没有 repair/reset switch。原子替换后的异常不回滚已发布暴露；无法确认 durability 时不发布成功许可。可信 root 祖先和宿主 owner 仍是信任边界，并非恶意 owner 沙箱。

## 6. CLI 错误与验收

失败不返回 observation 或部分 stdout。

| 退出码 | code | 语义 |
| --- | --- | --- |
| 2 | `invalid_confirmation_protocol` | 声明、实际绑定或整窗限制无效 |
| 3 | `confirmation_store_integrity_or_io_failure` | 确认状态损坏、缺少必需结构或 IO 不确定 |
| 4 | `confirmation_protocol_not_found` | 确认声明不存在 |
| 5 | `confirmation_already_exposed` | 来源已暴露，error 附排序的 `related_exposure_ids` |

既有探索接口的 `confirmation_access_denied`／退出5仍在 repository 与请求读取前生效；这不是新增所有数据导入入口的权限体系。数据 owner 可直接访问文件、导入已有字节、使用新 store 或伪造来源标签。本合同不承诺 owner 保密、跨根完整历史、来源真实性或统计独立性，不把局部账本无记录称为科学新鲜性。

计划远端验收包括真实 installed CLI 的冻结/重复、完整首开、重复拒绝、新名/跨协议/跨 registry、raw repack、子集/superset/重分段、capture/time/payload 变体、trade ID 冲突、不交叠窗口、上限整体拒绝、坏账本 fail closed 与旧 split pre-IO。低层另覆盖并发单赢家、commit 前后故障、missing/unsafe/oversize/corruption。安装验收在无 native 的 core wheel 及实际 source archive 上执行，guard 禁止 native、策略执行、worker、网络、新 attempt 和预算写入；保留报告与合成 records 30天。远端成功前不预记验收结论，实际证据统一回填 [Sprint 8 状态](../planning/sprint-08-status.md)。
