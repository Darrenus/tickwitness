# ADR 0017：先资格化观测与真假语义

- 状态：Proposed；S06-02a 完整远端验收通过，待 owner 审阅接受。
- 日期：2026-10-26。
- 合同：[Queue Semantics Qualification v1](../contracts/queue-semantics-qualification-v1.md)。

## 问题

两个按声明模型正确执行的结果不自动成为同一观测下的真实执行世界。当前 external tape 全额消耗 trade，own fill 另算；把两者直接合为单次真实 trade 会违反特定插单投影的数量守恒。旧 family 对 source claim 只保留 lineage；擅用新 flat-zero／mark 政策会扩大旧合同。

## 决策

生产入口只读重审两份 committed run，固定完整共同来源和政策集合，分别报告条件外部投影及一个命名插单投影的必要残差；保留 `MODEL_SENSITIVITY`、真假 null、空 findings。输入与执行错误采用具体错误，不归为 false。

另以独立 purpose／kind 冻结候选谓词，仅用于固定原创 synthetic 资格案例。每个原生调用仍持久占一个共同预算槽，候选计算从实际审计结果及源最后 best bid 重建，用 Fraction 验证四比较符与同／异真值。没有用户数据的免费引擎资格入口，不能把候选诊断移植成原命题评价或最终 finding。

## 后果与退出

资格结果验证的是明示有限路径的模型语义；一个投影的反例不排除所有 ghost 模型，无残差也不证明完整相容世界。同真值 pair 不证明全部模型已识别。S06-02 后续需要独立冻结 queue claim、观测／干预合同、完整兼容性校验及 sealed evidence 流程；本轮不关闭整条故事，不提前签发不可识别 finding。
