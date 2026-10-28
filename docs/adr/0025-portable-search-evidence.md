# ADR 0025：以独立内容闭包封存搜索证据并离线重审

- 状态：Accepted；owner 已合并 [PR #92](https://github.com/Darrenus/tickwitness/pull/92)，merge `275b5e1a8c8f706f5636773061b11da53231194a`。
- 日期：2026-10-28。
- 基线：owner 已合并 [PR #91](https://github.com/Darrenus/tickwitness/pull/91)，merge `2a83d39022ce5d53edbb42dafef897c6b5d1bd0c`。
- 合同：[Search Evidence v1](../contracts/search-evidence-v1.md)。

## 问题

S07-03 的 LOCAL_REAUDITED 报告依赖原 source、registry、plans 和 runs。单独保存报告，只能检查其声明与规则自洽，不能让另一台 core-only 环境重建实际派发、原预算、账务和停止事实。复制整份工作目录又会引入数据库、无关历史、可变路径和确认数据，并模糊缺件与原本不存在的 outcome。

## 决策

新增独立 `search_evidence_bundle_v1`，不修改旧 baseline／tagged evidence、原执行身份或预算。以固定内容寻址目录保存必要角色与 exact snapshot：真实 development raw／normalized／quality／manifest、finding authority、预算及入场、原 owner reservation prefix、本次候选 dispatch／link／result、selected attempts 的 intent／outcome 与必要 CAS、finding report 和相邻完成见证的诊断。

Presence 与 absence 显式封存，角色集必须等于 snapshot 派生的必要闭包。已声明对象缺失是带 role／hash 的损坏错误；未决槽位的 absent outcome 保持未知，不能借缺件产生 NOT 或 NO。没有 inner campaign 时不扫描 ledger，不把未观察历史当成零尝试证明。

Export pin 当前 report ID，重审实际来源后收集真实 bytes，再以不可变内存 ports 复算并比较完整报告，发布前重读检测变化。Verify 只读新包，重新规范化 source、校验完整绑定、派发、原 slots、intent、结果与账务，并通过原 readonly inspectors 重建结论；禁止原工作目录、数据库、native、worker、网络或临时恢复 workspace。

同时重算 `adjacent_completed_candidate_traces_v1` 诊断，保留参数、原始轨迹、具体比较、预算和停止原因。它不把相邻压力候选比较变成 baseline flip、纯延迟因果或全局最早分歧证明。

新 profile 有独立256MiB aggregate、4096文件、2MiB manifest和各 role上限，调用者只能收紧。超限整体拒绝，不悄悄裁后缀。复用既有低层 no-follow／bounded regular-file／原子 no-replace IO，不改变旧格式契约。

## 结果与范围

完整发布并读回或独立验证后返回 FINAL，含义是 sealed内容及审计闭包成立。内容身份不认证作者、原发布、原资源历史、全局试验账本或 confirmation 引用；纯 finding report 自身仍不承担这些权限。导出与验证不执行策略、不 reserve、不退款、不修改原 runs 或 budget。

core3／native10既有真实合成案例承担安装验收，无需再花研究槽位。新 smoke 删除复制的发行者所有目录并移动包后，以独立 core-only guard验证同一语义报告与诊断，并覆盖精确缺件与全量重算hash攻击。实际测试、格式化、构建、安装和原生前序执行全部远端；实际功能 head、merge checkout、运行与产物见 [Sprint 8 验收记录](../planning/sprint-08-status.md#s08-01-远端验收记录)。AI 静态交叉审阅单独计为 AI 辅助审阅，不替代独立人类领域接受。

S08-02 确认协议、S08-03 alpha与外部复验、S10恢复继续单独交付，不据此提前发行或声称真实采用。原12h专项估算与持续质量预算不重记，独立人类领域接受、工时及用户证据不补造。
