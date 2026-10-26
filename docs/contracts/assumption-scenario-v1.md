# AssumptionSpec / ScenarioSpec v1

状态：S05-01 开发合同，目标构建 `0.2.0.dev0`；待对应 PR 与远端 CI 验收。设计决策见 [ADR-012](../architecture/decisions.md#adr-012-场景声明与延迟压力执行分开验收)，操作见[场景校验](../scenarios.md)。本切片只验证声明与给定输入的约束，不执行情景、不消费 attempt、不改变 [ExecutableProtocol v2](executable-protocol-v2.md) 或旧 bundle。

首个变换 `replay_receive_suffix_shift_v1` 的含义是：从实际存在的 `from_capture_seq` 起，为该记录及其后全部记录的 receive 时间声明增加同一个非负值。它是额外压力的 typed declaration，不是历史修复、真实网络测量或独立 feed-delay 模型；本批不生成或发布变换后的行情。

## 请求与 canonical spec 分开

请求不接受自报的 protocol/data/spec bindings。builder 必须取得已经验证的 `ExecutableProtocol` 和 `ReplayInput`，据此注入身份。后续 loader 可以重新检查 canonical 编码及内嵌身份形状，不能仅凭一份 spec 验证外部对象存在或 capture anchor 可用。

两类请求与 canonical spec 均最多 **64 KiB**，必须为非空 UTF-8 JSON object，采用 exact schema。拒绝重复 key、未知/缺少字段、float token、NaN/Infinity、BOM、非法 Unicode 和不合法的整数；bool 不能冒充 int。不能利用未知字段添加任意配置、脚本、路径或外部执行入口。

### Assumption request

```json
{
  "kind": "assumption_request_v1",
  "schema_version": 1,
  "scenario_kind": "COUNTERFACTUAL_STRESS",
  "transform": {
    "semantic_id": "replay_receive_suffix_shift_v1",
    "from_capture_seq": 3
  },
  "additional_delay": {
    "minimum": 0,
    "maximum": 50000000,
    "unit": "ns"
  },
  "parameter_basis": {
    "kind": "researcher_defined",
    "calibration_status": "uncalibrated",
    "calibration_evidence_refs": []
  }
}
```

| 字段 | v1 规则 |
| --- | --- |
| kind / schema_version | `assumption_request_v1` / 真 int 1 |
| scenario_kind | 仅 `COUNTERFACTUAL_STRESS`；不能重新标记为观测相容解释 |
| transform | exact `{semantic_id,from_capture_seq}`；semantic_id 仅上述注册变换 |
| from_capture_seq | 正 signed int64，须指向绑定 development 输入中的实际记录 |
| additional_delay | exact `{minimum,maximum,unit}`；真 int，`0 <= minimum <= maximum <= 60000000000`，unit 严格为 `ns` |
| parameter_basis | exact `{kind,calibration_status,calibration_evidence_refs}`；依次固定为 `researcher_defined`、`uncalibrated`、空 list |

范围表达研究者准备探索的参数集合。60 秒是本版本的工程支持限额，不是物理上界、交易所协议保证、网络测量或校准区间；它也不是执行 worker 的 wall budget。第一版拒绝非空校准引用和自报 calibrated。没有实际测量闭包时，不能用一个看似正规的 hash 把研究者设置的范围升级为证据。

canonical AssumptionSpec 保留上述规范化内容，将 kind 改为 `assumption_spec_v1`，另注入 exact bindings：

```text
bindings = {
  protocol_id,
  development_dataset_id,
  normalized_sha256,
  replay_spec_id
}
```

每个 ID/hash 都是 64 字符小写 SHA-256。`normalized_sha256` 绑定实际 ReplayInput 的规范化字节；dataset ID 引用 sealed manifest，两者不能混为一个身份。protocol 和 replay spec 必须与实际 development 输入匹配。

### Scenario request

```json
{
  "kind": "scenario_request_v1",
  "schema_version": 1,
  "scenario_kind": "COUNTERFACTUAL_STRESS",
  "additional_delay": {
    "value": 10000000,
    "unit": "ns"
  }
}
```

scenario 从已冻结 assumption 中选择一个参数值，不自行改变变换、anchor、范围或来源绑定。value 为非负真 int，在所引用 assumption 的闭区间内，unit 同样严格为 `ns`；类别必须匹配。canonical ScenarioSpec 将 kind 改为 `scenario_spec_v1`，增加 `assumption_id`，不重复提供另一份可冲突的 bindings。

示例的 10,000,000 ns 只是 10 ms 候选参数，不表示已运行或已观察到影响。零值同样必须满足范围与 anchor 约束；不能用零参数绕过来源校验。

## 身份、不可变性与 API

`assumption_id` 与 `scenario_id` 分别是其完整 canonical spec bytes 的 SHA-256，不内嵌自引用 ID。key 排序、紧凑 UTF-8 JSON 固定编码；load 要求精确 canonical bytes，build 可接受普通 JSON key 顺序。DTO 保存不可变字节，`document` 每次提供独立解码副本。

范围、anchor、参数依据、类别、变换语义或任一来源绑定改变，产生新的 assumption ID。所选 delay 或 assumption 引用改变，产生新的 scenario ID。新情景不能原地改写旧协议、数据、spec 或已有证据包。

```python
from tickwitness.domain.assumptions import (
    AssumptionValidationError,
    build_assumption_spec, load_assumption_spec,
    build_scenario_spec, load_scenario_spec, validate_scenario_spec,
)

assumptions = build_assumption_spec(
    assumption_request_bytes, protocol=protocol, replay_input=replay_input,
)
scenario = build_scenario_spec(scenario_request_bytes, assumptions=assumptions)
validated = validate_scenario_spec(
    scenario, assumptions, protocol=protocol, replay_input=replay_input,
)
```

loaders 只检查值对象自己的结构、canonical encoding、自身 hash 及内嵌身份类型。assumption builder 在注入实际绑定前做输入核验；scenario builder 核对引用、类别、单位与区间。`validate_scenario_spec` 对两 spec 与再次提供的真实 protocol/input 重新校验，不能把此前 builder 的通过当作可变外部输入永远有效。

## 上下文输入约束与回执

CLI/application 先在只读 repository 模式下核验 development dataset 的完整 manifest/raw/normalized/report 闭包和严格报告一致性，再构造 ReplayInput。domain 不能仅从自报 dataset ID 推导上层 sealed manifest，单独加载 spec 不能替代应用的闭包校验。

上下文校验至少要求：

1. protocol ID、development dataset ID、规范化字节 hash、ReplaySpec ID 全部匹配；确认数据不能作为 development 替代。
2. 通过[现有 replay preflight](replay-v1.md#3-native-import-之前的预检)：受支持单流 EUR-USD、一次初始 snapshot、规范化/序列/盘口与已知非递减 receive 时间等输入约束，并满足冻结协议自身更严格的 event budget。
3. `from_capture_seq` 是输入中的实际 anchor，不能用下一个 capture 补位。
4. assumption builder 检查最后 receive time 加 `additional_delay.maximum` 及 insert/cancel execution horizon 不溢出 signed int64；validate 重验该范围上界，并显式检查所选 candidate value 的 horizon。仅参数落在 60 秒限额内不代表实际输入时间安全。

后缀统一增加非负值在已通过基线时序检查的输入上不需要重新排序。不得 sorting、clamping、补包、删除事件或修改 capture identity 来让不支持的输入“通过”。原 event_time、原 receive_time、原始 bytes 与 lineage 均应保留；本批只核约束，不输出 derived tape。

成功回执为 `kind=validated_scenario_constraints_v1`、schema_version 真 int 1，包含 scenario_id、assumption_id、bindings、scenario_kind、transform 与所选 additional_delay，以及：

| 字段 | 含义 |
| --- | --- |
| source_bindings_verified=true | 本次提供的 protocol/development/input/spec 身份绑定通过；不是交易所来源或作者真实性认证 |
| input_constraints_verified=true | 本次实际输入与候选参数通过列明的输入/范围/anchor/时间预算约束 |
| calibration_status=uncalibrated | 没有获得真实延迟的校准证明 |
| execution_approved=false | 未批准或执行该情景，未验引擎对其语义的兼容性 |

回执没有收益、成交、claim observation、可行历史世界或搜索 finding；不能翻译为“市场情景已经证实可行”。`source/input` 校验通过、校准、模型兼容和实际执行是不同门槛。

`ValidatedScenario` 保存四个已经验证的不可变 typed value（protocol、ReplayInput、assumption 与 scenario），`document` 派生上述结果；没有另造 `validation_id` 或 canonical evidence artifact。要持久化研究执行证据仍须经过后续单独的协议与发布门。

## 后续执行门

当前 `receive_order_v1` 把 native 市场及策略使用的时间映射到 receive，并按 capture_seq 触发内置策略。若 anchor 是首条记录，常数平移可能只改变时间戳、订单 ID 和 hash；局部后缀改变相对时间也不自动等于独立的 market-data 接收延迟。

S05-02 需另行确定市场/观察/决策与命令时钟、变换数据的 lineage、新 adapter/clock semantic、能力协商和独立审计。零变换、全流平移经济不变对照、有效非零案例、同刻顺序、future-cache、EOF 与金额核算属于后续执行资格门，不能在本批写成已完成实验。原始协议和旧 semantic 不可静默放宽。

S05-03 应披露 controlled intervention 的共同条件和允许变化；改变 dataset/spec/model 后不强迫旧比较器给出 `strictly_paired=true`。输入 hash 或 first-divergence 改变不等于命题翻转。只有满足完成规则且双方 eligible 时，才可按冻结的 metric/comparator 比较数值；未成交、费用歧义或未决命令不构成经济反例，更不能据此签发 `NOT_IDENTIFIABLE_WITHIN_MODEL`。
