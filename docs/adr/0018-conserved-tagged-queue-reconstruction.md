# ADR 0018：独立冻结标记参与者的守恒重建

- 状态：Proposed；S06-02b 实现中，远端验收待运行，待 owner 审阅。
- 日期：2026-10-26。
- 基线：owner 已合并 PR #84，merge `e018100df57e66376c810edce4fdf9ffec698e28`。
- 合同：[Tagged Queue v1](../contracts/tagged-queue-v1.md)。

## 问题

S06-02a 的单次 trade 检查表明：旧 ghost tape 全额消耗公开成交后再额外计 own fill，不能直接解释为一个包含己方的真实总簿。重标旧模型或放宽审计会隐藏研究对象的变化。旧 family 也没有独立 queue claim，不能把新估值政策套在 source claim 上。

## 决策

新增不可变 `tagged_queue_reconstruction_protocol_v1`，拥有独立命题 revision、semantic、观测投影、干预、terminal／valuation 政策及双模型共同预算。source v2 与完整旧约束只提供实际数据、配置、单位和 gross-flow lineage；旧 impact／execution 标志不授权新模型。

入口将原始已显示队尾 q lots 标记为假定己方，初始 `(A,R,B)=(Q-q,q,0)`。公开投影固定 `Q=A+R+B`，新增进 B，外部撤单按 front／back 政策跳过 R。每笔 trade 按 `A→R→B` 单次分配；checkpoint 总量相等、非负及 ownfilled+R=q 均须成立。任一模型要求撤销保护订单即拒绝整份冻结，不能只保留可行一侧。

输入是 public L2／trades 的有限条件重建。模拟 private fills 和 post-horizon cleanup 排除在观测投影外；真实 private observations 当前未读取，也未验证。原生首 capture 接受明确标记 reconstruction proxy，不证明真实历史到达或 ownership。literal 新插单与市场冲击仍不获验证。

horizon 先保存实际源、队列、原生书簿与账户并取最后可见 best bid，再于同一 native 时刻行政取消剩余订单；不增加市场事件或推进时钟。清理后的预测总量 Q−R 与原始 observation cache 分别记录。CANCELED 的未成交量不等于仍存活的 own量。

新独立审计从实际源重算单次分配及订单／费用／账户前缀，只对新命题给条件真值；无成交完整终止采用显式 flat-zero。标准样例预期 ownfill2/0、fee2/0，bid100 net−2/0；bid102 net+2/0，gt0 为 T/F、ge0 为 T/T。预期表不是远端通过记录；实际结果若不同必须解释或修复，不能更改 oracle 掩盖残差。

## DDD 与持久化边界

领域合同和纯模型负责不变量；application 在实际 development store 和注册表闭包上冻结／执行／复核；基础设施负责 POSIX 发布、共享预算和受监督可选 native worker。旧路径保持 strict kind／semantic，新结果不能进入旧 bundle 或比较器。

每次 worker 调用前持久占槽并绑定完整不可替换 intent。失败、超时、中断不退款，取得但未通过审计的原始回调仍保存诊断。双模型顺序执行、失败即停止并保留第一份成功。inspect 重审 committed source／CAS 闭包，无 native 或新槽。

## 后果与后续门

合同范围缩窄为“给定有限 public 观测与声明 gross 条件的假定标记参与者”，不能对真实插单 fill 或真实市场收益做预测。不同研究对象产生新身份和新 oracle，保留旧记录可追溯。

同／异真值仅评价已列解释；`NOT_IDENTIFIABLE_WITHIN_MODEL` 和其他最终 findings 仍关闭。独立 sealed tagged evidence 流程、确认集 lifecycle、跨协议试验追踪、真实 private 证据、外部复验与独立人类领域接受须另行实施和验收。所有项目测试、native 回放、构建与格式化在远端运行，未运行的门不记为通过。
