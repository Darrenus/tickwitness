# Search Evidence v1

状态：S08-01 实现合同，远端验收和 owner 接受待完成。基线为 owner 已合并 [PR #91](https://github.com/Darrenus/tickwitness/pull/91)，merge `2a83d39022ce5d53edbb42dafef897c6b5d1bd0c`。本轮保持 `0.2.0.dev0`，不发行新版本；S08-02 的确认协议与一次性解封另行验收。

## 内容闭包与权限

本合同将 [有范围搜索结论](search-findings-v1.md) 的实际来源、假设、候选、原 attempts／outcomes、[共同预算与停止](campaign-budgets-v1.md) 以及版本声明封存为独立格式。旧 baseline、tagged 与 finding evidence 格式不变；原计划、scenario receipt、预算 owner 和已提交结果不改写。

导出不是把自报 finding JSON 换一个 envelope。它先从真实 readonly inspector 重新建立当前证据链并核对显式 report ID，再收集实际提交的 immutable bytes；缺失的已声明对象不能用推导或补写代替。收集后的内存闭包必须独立重审并重建完全相同的 finding report；发布前再次读取当前报告检测变化。只有完整新目录原子发布并读回复核后才返回回执。

离线验证不读取原工作目录、不构造原 repository、不使用 SQLite、native、network、worker 或临时恢复工作区。Raw development data 的规范化、quality report、manifest、冻结声明、派发、admission、reservation、intent、result、outcome 和账务通过不可变内存 ports 重建原 readonly inspectors；不得只信任包内保存的 verification 旗标。

这次“重放”指数据／声明／账务与结论规则的语义重建，不是重新运行 native 研究尝试。原生引擎输出仍是被审计的已记录见证；任何原 slot 都不退款或增发，导出／验证不 reserve 新 attempt。

## Envelope、角色与资源范围

目录固定为 `manifest.json` 和 `objects/sha256/<lowercase SHA256>`，不包含数据库、可执行 pickle、压缩归档或任意 filesystem 路径。Manifest exact 字段为 kind、schema_version、scope、roles，固定 markers 为：

- `kind=search_evidence_bundle_v1`。
- `schema_version=1`。
- `scope=development_scoped_search_evidence_v1`。

每个 role 的 reference 精确包含 `sha256`、`size_bytes`、`ref=objects/sha256/HASH`。Canonical JSON 拒绝重复键、未知字段、float、bool冒充整数及错误 markers；同 hash alias 只能引用同一大小的 payload。物理文件集合必须与 manifest 的 unique hashes 完全一致，不能夹带额外或隐藏文件。

| Role | 单件 payload 上限 |
| --- | --- |
| `finding_protocol` | 3MiB |
| `snapshot` | 2MiB |
| `dataset_manifest` | 64KiB |
| `raw`、`normalized` | 各8MiB |
| `report`（quality）、可选 `campaign` | 各4MiB |
| `budget`、可选 `outer_stop`／`inner_stop`、`allocation/NNNN` | 各64KiB |
| `finding_report`、`diagnostics` | 各8MiB |
| `candidate/NNNN/dispatch`、`candidate/NNNN/link` | 各64KiB |
| `candidate/NNNN/result`、`cas/HASH` | 各16MiB |
| `reservation/NNNN`、`attempt/HASH/intent`／`attempt/HASH/outcome` | 各16KiB |

`NNNN` 为 `0001..1024`，reservation index 还受原协议实际 max_attempts 约束；HASH 必须为64位小写 hex。可变 role 集合完全由 snapshot 的闭包声明决定，不能增加无关历史 CAS 或遗漏必要对象。

新 profile 的总 unique-object payload 加 manifest 最多256MiB、文件数（含manifest）最多4096、manifest最多2MiB。`SearchEvidenceLimits` 只允许收紧这些上限，没有放大配额的 CLI 开关。超限须整体拒绝，不截掉候选后缀伪称完整，也不修改原已完成 campaign。计量是导出包内容，不能认证原运行的峰值磁盘、RAM或物理时限。

## 显式 presence 与完整关联

Snapshot `search_evidence_snapshot_v1` 绑定 finding protocol、plan、原 protocol、dataset、budget、producer version；版本是声明，非作者或执行环境认证。它保存完整 eligible 候选顺序，包括未入场后缀，并显式声明 outer stop、inner campaign／stop、allocations、dispatch／link／captured result、原 owner reservation prefix、selected attempts 的 intent／outcome，以及所需 CAS 集合。

Flag=false 封存的是该 snapshot 中明确的 absence；flag=true 却没有所需 role／文件则是损坏，不能转成 NOT_EVALUABLE。Missing declared object 使用 `search_evidence_object_missing`，标明逻辑 role 和 SHA256，便于找到具体缺件。没有 inner campaign 时不构造或扫描原 ledger，`ledger_prefix_observed=false` 与空 reservations 表示历史未观察，不代表已证明零尝试。

有 inner campaign 时保存原 owner 的完整已观察 reservation prefix，包括 baseline 和其它 plan 的槽位；只为与本次 dispatch nonce 匹配的 attempts 收集 intent／outcome 闭包。Reservation、已出现的 intent／outcome 同时保留对应 CAS bytes；无须复制无关策略历史或确认数据。

Committed intent 所引用的 assumption、scenario、derived view 和 derived tape 必须来自实际存储，且重新推导一致；已提交失败或未决尝试也不能跳过这项关联。成功／INCOMPLETE outcome 包含实际 result／evaluation CAS。未通过经济审计的 captured raw result 仍可作为 failure／unfinalized 的诊断记录封存，不因此变成有效 false 见证。

## 分歧诊断与 FINAL 的含义

`search_evidence_diagnostics_v1` 使用固定 `adjacent_completed_candidate_traces_v1` 政策，从候选顺序中相邻的 COMPLETED 且 raw_result_audited 见证重算既有 replay comparison。每对包含两个 ordinal／run ID 和完整 comparison 文档；零／一个完成候选时 pairs 为空，最多99对。所有 captured raw traces 仍封存。

这不是 baseline 配对，也不声称分歧仅由 delay 引起或找到了全局最早业务原因。`baseline_comparison_performed=false`、`causal_attribution_issued=false`、`native_replayed=false` 固定保持；诊断不扩大原 finding 的命题范围。

应用回执为 `search_evidence_verification_receipt_v1`，包含 bundle ID、report ID、原 finding report、重算 diagnostics 与 snapshot。`finalization_status=FINAL` 只表示 sealed content／audit closure 已建立；不认证作者、原发布行为、人类审批、跨协议完整 trial 历史、原时限／存储实际执行或 confirmation 引用闭包。原 finding report 的纯领域 audit 声明不靠改字段升级为原历史证明。

## CLI 与失败处理

```sh
tickwitness export-search-evidence FINDING_PROTOCOL_ID \
  --expected-report-id REPORT_ID --plans plans --store data --registry registry \
  --runs runs --finding-registry finding-registry --output new-bundle

tickwitness verify-search-evidence relocated-bundle --expected-bundle-id BUNDLE_ID
```

Export 必须 pin 可信 report ID，防止在导出时静默切换结论；verify 可选 pin 最终 bundle ID。内容 hash 不替代可信渠道、签名或作者身份。Confirmation 在 ID、文件和 repository 访问前拒绝；缺失根不创建。

新包只发布到已存在父目录下的新名字，已有文件、空目录或同内容目录也不覆盖。Payload 先写 staging、fsync，再原子 no-replace 发布并同步父目录。发布后 fsync 不确定时保留已发布内容并明确报告，不删除“修复”。输入保持 no-follow、有界常规文件、固定路径和完整文件集合检查；FIFO 不等待写端。

## 远端验收门

安装验收复用前序真实 `installed_search_finding_acceptance_v1` records：core3个案例、native10个案例，包括 CE、全 true 有限集合、预算内 true 前缀、失败／时间／零覆盖 NOT。复制发行者 workspace 后导出全部包，移动包根并删除复制的全部原目录，再在独立 core-only guard 下离线复验同一报告与诊断。Guard 禁原 stores、SQLite、临时恢复 workspace、native、Popen、network 和所有研究写入口。

验收还包括 report／bundle pin、原记录与 slots不变、重复身份、只读重审、原子不覆盖、精确 missing-object、全量重算外层hash后仍拒绝错误 finding／diagnostics，以及 role／大小／文件数／总量／symlink／FIFO 等攻击。真实 wheel、实际 tar.gz 中脚本与样例的 core／native链路均在远端执行，报告与完整包保留30天；未发生的检查不记为通过。

该切片不替代 S08-02 确认 lifecycle、S08-03 alpha基准与外部复验、S10通用恢复、真实访谈或独立人类领域接受。原12h专项估算与持续质量预算保留，不补造实际工时、性能、采用或市场收益证据。
