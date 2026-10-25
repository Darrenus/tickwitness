# TickWitness 参考资料与来源边界

资料核对日期：2026-10-25。以下链接支持领域与工程背景；产品路线、工作量、目标阈值及采用假设是本项目规划，不是这些来源证明的结果。具体依赖版本及许可在 Sprint 1–2 选型时固定。

| 来源 | 支持的内容 | 不能由此推出 |
| --- | --- | --- |
| [Martin Fowler：Bounded Context](https://martinfowler.com/bliki/BoundedContext.html) | 模型边界、通用语言和上下文间关系 | 每个上下文都必须部署成微服务 |
| [Scrum Guide](https://scrumguides.org/scrum-guide.html) | 经验反馈、迭代、检查与调整 | 单人加AI天然构成完整Scrum团队 |
| [Binance WebSocket官方文档](https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md#how-to-manage-a-local-order-book-correctly) | 快照/增量同步、缺口后重新同步、流的更新语义 | 后续快照补回全部缺失历史路径；所有WS消息等于全部逐订单事件 |
| [HftBacktest官方成交说明](https://hftbacktest.readthedocs.io/en/latest/order_fill.html) | 队列模型、部分成交、历史回放和market impact的局限 | L2能确定真实队列或模拟订单的真实市场影响 |
| [HftBacktest仓库](https://github.com/nkaz001/hftbacktest) | 候选回放引擎与接口背景 | 已选定为本项目默认引擎 |
| [NautilusTrader仓库](https://github.com/nautechsystems/nautilus_trader) | 另一个候选回放架构和适配生态 | 本项目已经支持其全部市场和能力 |
| [Freqtrade lookahead-analysis](https://www.freqtrade.io/en/stable/lookahead-analysis/) | 已存在的切片重跑式前视检查 | 自动扰动查偏差本身具有原创性 |
| [Qlib](https://github.com/microsoft/qlib)、[RD-Agent](https://github.com/microsoft/RD-Agent) | 已存在的量化研究自动化工作 | Agent研究入口天然具有独特性 |
| [AlphaAgent](https://github.com/kamendula/AlphaAgent) | 已公开PIT工具访问护栏思路，README标Pre-alpha | 已证明成熟可靠，或完全排除模型记忆污染 |
| [Sharpen](https://github.com/bigcan/sharpen) | 已有预注册、统计护栏、成本敏感性和压力测试方向 | TickWitness可宣称发明了证伪或压力测试 |
| [quant-research-platform-project](https://github.com/arjunsood2025/quant-research-platform-project) | 原始综合量化平台方案的直接重叠 | README性能数字经本项目复跑验证 |
| [HF Binance订单簿数据](https://huggingface.co/datasets/predict-quant/binance-future-orderbook) | 公开数据与Parquet分发先例 | 可直接视为完整真实队列、时点认证或符合任意用途许可 |
| [GitHub Actions安全建议](https://docs.github.com/en/actions/reference/security/secure-use) | 最小权限、不可变Action版本和不可信工作流边界 | 加入CI就自动达到软件供应链安全 |
| [MCP安全最佳实践](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices) | 工具授权、令牌和服务边界风险 | MCP本身构成研究正确性或代码执行沙箱 |
| [Apache-2.0](../LICENSE) | 本项目owner已选择的软件与自有文档许可 | 自动授予第三方数据和依赖的额外权利 |

后续研究方法文献、统计实现与其假设由对应RFC加入，不能只贴DSR、PBO等名称充当已实现的研究保证。所有外部仓库能力描述均需在依赖升级时重新核对。
