# Alpha Scorecard v1

状态：S08-03a 实现中，远端验收尚未完成。基线为 owner 已合并 [PR #93](https://github.com/Darrenus/tickwitness/pull/93)，merge `97822d7a74931a829bd3355fb40d85d4504de59d`；决策见 [ADR 0027](../adr/0027-reproducible-alpha-scorecard.md)，外部操作见[复验手册](../alpha-reproduction.md)。

本切片提供可转交的 core-only 复验 kit、实际技术 scorecard 和保留成功／失败的提交 runner。用户负责联系外部参与者；当前没有真实外部尝试，`external_attempts=0`、`external_successes=0`、门槛 `PENDING`。[S08-03 / #24](https://github.com/Darrenus/tickwitness/issues/24) 保持打开，不把软件交付、CI、AI、owner 自测或独立 cwd 自动解释为外部复验完成，不发行新版本。

## 1. 真实冻结语料与 suite

两个案例完整复制自 owner 接受的 S08-01 合成 native 证据：Engineering `40662769753`、artifact `12804098468`、actual checkout `42af1e23987835a9975cff1225175cbf3eec0bfb`、functional head `1623aaccaa8f4e8f6432989e6a877e4b1790e4c8`。当前 kit 组装 revision 与旧证据 producer 分别记录；不重造成功回执，不占新研究 attempt 或扩大原预算。

| 案例 | 原案例 | 既有 bundle ID | 必须独立复算的 oracle |
| --- | --- | --- | --- |
| `counterexample` | `source-normal` | `2261f5c82bf19d3f088ecd64fed131ae71635d686a4a4a4b1a8e9e6c43c78369` | `COUNTEREXAMPLE_FOUND`、完整已审计 `[1,3]`、真值 false、有实际 false 见证 |
| `clean_control` | `all-true` | `c5c3080fc6ab0ebd81b71373faee2f282e99feb95b904dd36bbc9631bd2b2c5e` | `NO_COUNTEREXAMPLE_FOUND`、完整非空 eligible=audited=true `[1,3]`、全计划真值 true、无 unknown／unevaluated 后缀 |

原 report IDs 分别为 `398ead2cd2ed7db4f4ba69a1cd3e4dd4acc6ae9d80abd7897307ca94d4af75bb` 与 `8b902a687eeeb6897aa9237074b8a4fe7e5b336264a47bf52a9cc8427c20b3da`。两个案例分别冻结 `net_marked_pnl_v1 > 0 USD` 与 `> -3 USD`；它们是不同谓词的技术正／负对照，不构成同命题的 baseline 翻转、因果识别或市场获利证据。预算内 true 前缀不能充当完整 clean control。

`AlphaSuite` 的 exact document：

```json
{
  "kind": "alpha_reproduction_suite_v1",
  "schema_version": 1,
  "profile": "development_technical_alpha_v1",
  "cases": {
    "counterexample": {"bundle_id": "<SHA256>", "report_id": "<SHA256>"},
    "clean_control": {"bundle_id": "<SHA256>", "report_id": "<SHA256>"}
  },
  "invalid_perturbation": {
    "source_case": "counterexample",
    "policy": "frozen_delay_upper_bound_plus_one_v1"
  },
  "publication_probe": "alpha_kit_precommit_sync_postcommit_parent_sync_v1",
  "external_gate": "human_confirmed_external_attempt_required_v1"
}
```

Suite 上限64KiB，scorecard 上限1MiB。`AlphaSuite(suite_id, canonical_bytes)` 与 `AlphaScorecard(scorecard_id, canonical_bytes)` 为不可变值，`.document` 返回独立 view，ID 是 exact canonical UTF-8 JSON bytes 的 SHA-256。严格 schema／常量／类型／canonical loaders 拒绝未知字段、重复 key、float、bool 假冒 integer 和非 canonical 字节。不能通过重算 hash 为另一个谓词获得原 pin 的权限。

## 2. 可移动 kit

新 manifest exact 顶层为 `kind="alpha_reproduction_kit_v1"`、`schema_version=1`、`scope="development_technical_alpha_v1"`、`producer`、完整 `suite`、`wheel_path`、`files`。`producer` exact 包含有界 declared `version` 与40位小写 hex `source_revision`；`files` 是 path → `{sha256,size_bytes}`，不包含 manifest 自身。

固定内容只有：

```text
manifest.json
README.md
reproduce.py
distribution/tickwitness-<version>-py3-none-any.whl
cases/counterexample/manifest.json
cases/counterexample/objects/sha256/<HASH>
cases/clean-control/manifest.json
cases/clean-control/objects/sha256/<HASH>
```

case 内包含完整原 search evidence 对象，不能用报告摘要代替。只收 development 证据，不复制原 SQLite／registry／runs／confirmation 数据。Kit loader 只审查 bytes 与嵌套内容，**不执行 runner、不安装 wheel**；接收方安装／运行来自其明确操作。

独立 profile 最多32MiB aggregate、512文件，均包含 manifest；manifest 最多256KiB、wheel 最多4MiB、README 与 runner 各64KiB，嵌套 search evidence 仍受原格式自己的限制。`AlphaKitLimits` 只能收紧；超限整体拒绝，不裁案例或对象后缀。只接受 exact tree、bounded regular files，以 FD-anchored no-follow／nonblocking IO 拒绝 symlink、FIFO、隐藏／额外文件、空目录、别名和任意路径。

`AlphaReproductionKit(manifest_bytes, _files)` 直接构造同样验证 immutable 闭包；公开 `kit_id`、detached `manifest`／`files`、`suite_bytes` 与 `case("counterexample" | "clean_control")`。`.case()` 返回实际 immutable search evidence package，不恢复发行者 workspace。

`export_alpha_kit` 接受 suite bytes、wheel／guide／runner bytes、两个实际包及 declared producer；`publish_alpha_kit` 发布已验证的 kit；`read_alpha_kit(root, expected_kit_id=..., limits=...)` 读回。输出必须是已存在可信 parent 下的新目录。完整 stage 所有文件与目录 fsync 后 atomic no-replace rename，再同步 parent；不覆盖、不 repair。

## 3. 实际技术评估

`evaluate_alpha_kit(kit, expected_kit_id=..., publication_probe_factory=...)` 先核 kit／suite pin，对两例调用原 `verify_search_package`，要求实际 bundle/report IDs 与 suite 相等，并核完整覆盖、原 stop 和真假 oracle。所有封存 source、账务、预算与诊断仍按 [Search Evidence v1](search-evidence-v1.md) 重新审计。

无效扰动从实际 CE 假设的上界 `maximum` 导出 `maximum+1 ns`，重新构造受软件范围允许的 ScenarioSpec 并调用实际 validator，必须得到 `AssumptionValidationError("Scenario delay is outside its frozen assumption range")`。保存真实 assumption／scenario identity、上界与 challenge；不硬编码另一份上限，也不把拒绝包装成 `NOT_EVALUABLE` 或研究反例。上界加一不可表示时整体拒绝该 suite/profile。

`LocalAlphaPublicationProbe(new_root)` 在独占新 scratch root 内三次调用**同一新 kit publisher**，以 per-call hooks 注入同步错误，不全局 monkeypatch `os`，不从 kit 接受任意执行 hooks：

| 实际 probe | 必须观察到的边界 |
| --- | --- |
| 正常发布、读回、重复同目标 | kit 完整相等；重复获 destination-exists，已发布字节树不变 |
| 提交前同步失败 | 真实失败，无成功回执、无最终目标、stage 清理 |
| rename 后 parent sync 失败 | `AlphaKitDurabilityError`，无成功回执，保留完整目标，durability 未确认 |

probe 保留实际目录供诊断。应用必须从 `postcommit_kit` 独立重验两例内容，不能只相信 probe 返回的 flags。内容复验通过不把这次失败发布变成同步成功。受控注入不是物理断电实验，不认证 crash durability；普通同步失败也不能伪装成预期 probe 成功。

Scorecard 不含路径、时间戳、平台异常 prose；相同 kit 在不同目录重跑，实际技术语义应保持 exact ID。只有真实案例、无效扰动与所有发布边界均满足时 `technical_checks="PASS"`。固定门槛为：

```json
{
  "external_attempts": 0,
  "external_successes": 0,
  "external_attempt_gate": "PENDING",
  "release_decision": "TECHNICAL_ALPHA_ONLY_EXTERNAL_PENDING"
}
```

固定 scope 的 `native_replayed`、`new_research_attempts`、`confirmation_accessed`、`source_claim_authority_extended`、`global_history_authenticated`、`external_identity_authenticated`、`power_loss_durability_certified`、`s10_recovery_qualified` 全为 false。它是 supplied-content 技术审计，不扩展原研究权限，不认证独立参与者身份、真实采用、收益或 S10 通用恢复。

`alpha_scorecard_v1` exact 顶层为 `kind`、`schema_version=1`、`profile="development_technical_alpha_v1"`、`kit_id`、`suite_id`、完整 `suite`、`cases`、`invalid_perturbation`、完整 `publication_probe`、`gates`、`scope`。`cases` exact 为 `counterexample` 与 `clean_control`；每份 summary exact 包含：

| 字段 | 语义 |
| --- | --- |
| `bundle_id`、`report_id`、`finding_protocol_id`、`source_protocol_id`、`predicate_id` | 实际重审的内容身份 |
| `outcome`、`planned_predicate_truth` | 按 case role 精确匹配 CE/false 与完整 NO/true |
| `eligible_ordinals`、`audited_ordinals`、`true_ordinals`、`false_ordinals`、`unknown_ordinals`、`unevaluated_ordinals`、`witness_ordinals` | 排序唯一整数列表，保留实际覆盖与见证 |
| `coverage_complete_for_plan` | 完整有限计划的覆盖状态 |
| `outer_status`、`outer_stop_reason`、`inner_status`、`inner_stop_reason` | 实际重审的执行状态与停止原因 |

Invalid summary exact 为 `kind="alpha_invalid_perturbation_check_v1"`、`schema_version=1`、`source_case="counterexample"`、实际 `source_bundle_id`／`assumption_id`／`scenario_id`、`policy="frozen_delay_upper_bound_plus_one_v1"`、`validator="validate_scenario_spec_v1"`、`frozen_maximum_ns`、`challenge_delay_ns=maximum+1`、`outcome="REJECTED"`、`reason_code="scenario_delay_outside_frozen_assumption_range"`。冻结上界只能为 integer 0..59,999,999,999，domain 重建实际 challenge identity。

Probe document exact 顶层为 `kind="alpha_kit_publication_probe_v1"`、`schema_version=1`、`profile="alpha_kit_precommit_sync_postcommit_parent_sync_v1"`、`kit_id` 及四份结果。`normal_publication` exact 为同原 kit 的 `published_kit_id`／`readback_kit_id` 与 `success_returned=true`；`existing_destination` 为实际 `exception_type="AlphaKitDestinationExistsError"`、`success_returned=false`、`original_tree_unchanged=true`。提交前结果为 `fault_injected=true`、`exception_type="AlphaKitError"`、`success_returned=false`、`target_exists=false`、`staging_entries_remaining=0`；提交后结果为 `fault_injected=true`、`exception_type="AlphaKitDurabilityError"`、`success_returned=false`、`target_exists=true`、同原 kit 的 `retained_kit_id`。这些结果必须来自实际调用，不接受 kit 提供的 probe 快照作为执行替身。

成功回执 exact 为 `kind="alpha_scorecard_receipt_v1"`、`schema_version=1`、`kit_id`、`suite_id`、`scorecard_id`、完整 `scorecard`、`finalization_status="LOCAL_RECOMPUTED_TECHNICAL_ONLY"` 和 `verification`。后者的 `case_contents_reaudited`、`invalid_validator_reexecuted`、`publication_boundaries_reexecuted`、`postcommit_case_contents_reaudited` 为 true，`saved_flags_trusted=false`；没有外部认证或已确认持久性的额外权限。

`verify_alpha_scorecard(kit, saved, expected_kit_id=..., publication_probe_factory=...)` 加载严格保存值后，重新执行整个评估及实际 probe，并比较 exact canonical bytes；已保存 PASS 和重算外层 hash不能替代重审。缺件、错误 pin、伪造 clean／invalid oracle 或任何实际异常都报错，无成功 scorecard stdout。

saved 必须是 qualify 输出的完整上述 receipt，不是裸 scorecard 或节选；输入上限为 scorecard 最大值加4096bytes。`prepare_alpha_suite(counterexample, clean_control)` 是公开 preflight：先真实重审两例并实际拒绝 invalid challenge，再返回 suite，但不执行 publication probe，也不把 preflight 当技术资格通过。

## 4. CLI 与外部提交

```sh
tickwitness export-alpha-kit --counterexample CE_PATH --clean-control CLEAN_PATH \
  --wheel WHEEL --guide GUIDE --runner RUNNER --source-revision REVISION --output NEW_KIT
tickwitness qualify-alpha-kit KIT --expected-kit-id KIT_ID --probe-root NEW_PROBE
tickwitness verify-alpha-scorecard KIT SAVED.json --input-root ROOT \
  --expected-kit-id KIT_ID --probe-root ANOTHER_NEW_PROBE
```

Export 独立核两份原包并 pin 实际报告，发布／读回新 kit；正式技术评估由后续显式 qualify 执行。没有新 native、confirmation split、旧预算或用户策略执行参数。无效 alpha 输入退出2，kit IO／已存在目标／同步不确定退出3，缺根退出4；错误 stdout 为空，真实结构化 error 保留。

| 退出码 | code |
| --- | --- |
| 2 | `invalid_alpha_evidence` |
| 3 | `alpha_kit_integrity_or_io_failure`、`alpha_kit_destination_exists`、`alpha_kit_durability_unconfirmed` |
| 4 | `alpha_kit_not_found` |

随包 stdlib-only `reproduce.py` 使用当前已装 core 的 Python，以独立子进程启动 CLI；它是提交采集器，不是研究 worker。参数为 `--kit`、`--expected-kit-id`、`--participant-id`、`--participant-role external_user|maintainer|automation`、`--output NEW_DIR`。参与者自行在全新 venv 以 `pip --no-index --no-deps` 安装包内 wheel，运行一次，再自行转交整个输出目录；runner 不联网、不自动上传。

提交目录保留 `submission.json={submission_id,submission}` 和实际存在的完整 receipt `scorecard.json`；submission outcome 为 `VERIFIED`、`FAILED` 或 `TIMED_OUT`，review_status 为 `SELF_REPORTED_UNREVIEWED`。保留实际命令、kit pin、OS／Python／project version、子进程退出码与有界 stdout/stderr、receipt error；其真实时间／随机 attempt ID 与语义 scorecard 分开。Runner 自身成功退出0，实际失败记录完成后退出10，超时记录完成后退出11，提交 IO 失败退出3；子进程的原退出码另记，不能用 runner 的10替代。例如错误 kit pin 的 CLI 实际退出3，runner 保留该错误后退出10，不产生 scorecard.json。

Role 自报不认证身份，`external_gate_updated=false`，任何 role 都不能改 scorecard 的 external gate；模板、CI／AI／owner 和尚未执行的邀请不计真实外部尝试。后续收到原始记录再单独核验并由 owner 接受，不能在本切片补造。

远端 smoke 另生成只含已移位验证后 kit 的 `alpha-reproduction-kit.tar.gz`，唯一顶层为 `tickwitness-alpha-kit`。Kit 外的 `handoff.json`／`HANDOFF.txt` 绑定实际 expected kit ID、archive SHA-256、wheel 相对路径／SHA、当前组装 revision、外部0/PENDING及三步离线操作；不把自身 kit ID 写回 README 形成循环。Archive 不含 probe／自动化 submission，解压内容再由 guard 内实际 qualify 重验；sidecar 不认证作者或外部身份。

## 5. 远端验收

计划由 installed core wheel、Ubuntu／macOS 中独立 core interpreter，以及实际 source archive 的脚本／语料／guide／runner 与实际 wheel 执行。Smoke 组装 kit 后移动至独立目录并删除复制的组装输入；guard 禁止 native、原 stores／SQLite、网络、Popen 研究 worker、新 attempts 和旧预算写入。重复 fresh probe、保存值重审、错误 pin、重哈希 oracle、missing／unsafe、实际 runner automation 成功与失败记录均需检查。

报告、完整可转交 kit、probe 与 submission records 保留30天。全部项目代码、测试、构建、安装、格式化和执行在远端；当前合同不预记成功。技术交付完成后仍只标 S08-03a，#24 的真实外部尝试与 owner 接受继续待办，S10 恢复及公开 release 另行验收。

主 qualification／saved verification 的 installed interpreter 受严格 guard；真实随包 runner 则原样在同一 core-only Python 单独运行，不 interpose 它的子进程命令。安装报告分别声明这两种覆盖范围，不能把 runner 子进程描述成受主 guard 拦截。
