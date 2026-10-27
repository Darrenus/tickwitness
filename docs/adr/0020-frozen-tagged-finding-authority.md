# ADR 0020：冻结独立 finding 权限并封存确定性报告

- 状态：Proposed；S06-02d 实现切片，远端验收待完成，待 owner 审阅。
- 日期：2026-10-26。
- 基线：owner 已合并 PR #86，merge `62fc66b563528fcd03713ec8597ddb66e4d9c870`。
- 合同：[Tagged Findings v1](../contracts/tagged-findings-v1.md)。

## 问题

S06-02c 的十二角色包可以移交后独立重建两种有限条件解释和真假关系，但其 frozen execution scope 与 assessment 都固定 findings=[]。内容封存不能自动扩大判断权限，也不能把旧影子模型或原 source claim 重标为新结论。需要明确哪个命题、哪些模型条件和见证允许哪一种 finding。

## 决策

新增 `TaggedFindingProtocol v1`，显式冻结 `conditional_tagged_findings_v1`。它完整绑定原 tagged subject、新 claim revision、观测／gross／ReplaySpec、固定两政策、报告问题、权限、eligibility、规则和限制；原协议不修改，执行授权与预算不扩展。

权限将冻结谓词 P(w) 的识别问题与已列集合的稳健满足 U_S=∀w∈S P(w) 分开。完整同环境、可评价的 F/F 得针对 U_S 的 COUNTEREXAMPLE；T/F 或 F/T 得针对 P(w) 识别的模型内不可识别，同时得针对 U_S 的 COUNTEREXAMPLE；T/T 只得已列集合内 NO_COUNTEREXAMPLE。相反见证已确定 U_S 为 false，不能把它作为 NOTID 的目标。每份 finding 的 conclusion_target、见证和 scope 必须携带原观测、新命题、模型投影／干预、run／attempt／result／evaluation 及封存 source pair 身份。

原生环境不同或费用歧义时严格拒签（退出9），保留原始 source pair 和每份既有评价，不把未知当 false，也不以 INSUFFICIENT_EVIDENCE 覆盖原记录。非法／未完成／篡改证据为校验错误，不能进入任何研究 finding。

新增严格十四角色报告包：原十二角色 source pair，加独立 finding_protocol 与 finding_report。它与旧八／十二角色 marker 和 loader 隔离；复核先重建原十二角色 manifest 身份及全部 source／queue／native callback 审计，再重算报告。外层 hash 全部重算也不能洗白错误分配或伪造 finding。

## FINAL 与信任边界

领域报告的 source 可为 CONTENT_CLOSED，但不声称文件系统已经发布。应用在完整十四角色闭包发布且重新核验，或独立读取并核验该闭包后，才返回 FINAL；这只表示内容证据和确定性规则闭合。作者签名、人类领域审批、原始发布、完整 ledger 和历史 budget、native 重放、确认集检查都明确为 false。

冻结权限可以在已有 development 数据上建立；它不证明事前预注册。两种政策不是所有 admissible hidden allocations；NO_COUNTEREXAMPLE 不能推广为全模型、全部市场或未来收益保证。NOT_IDENTIFIABLE 仅解释声明的 public 路径及受限 tagged 模型，不认证真实订单到达、所有权、实际新插单或无市场冲击。条件 counter-witness 不是对实际历史实现的反驳。

## 后果与验收

CLI 将 freeze／inspect 权限与 issue／verify 报告分开，source pair pin 在 issue 时必须提供。source pair、旧权限和 ledger 不改写；报告签发不新增研究 attempt 或 native 调用。新目录沿用 CAS／预算／no-follow／no-replace／fsync 规则，发布后持久性未知保留目标。

验收包括独立冻结的 F/F、T/F、T/T、F/T 四种真值方向；F/T 使用新的 bid100／ge0 原生配对，反例只引用 front。还包括严格类型与错权限／subject／pin、ineligible 无输出、同一证据身份稳定、错误 exporter 替包拒绝、全 hash 重算后的报告／分配攻击拒绝、删除 issuer registry 与 source pair 后只有 core 的离线复核，以及真实 wheel／sdist 的安装链路。全部项目执行继续在远端；未运行门不记为通过。撤回／更正 lifecycle、确认集和完整 trial 历史仍是后续能力。
