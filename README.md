# TickWitness

[![Documentation](https://github.com/Darrenus/tickwitness/actions/workflows/docs.yml/badge.svg)](https://github.com/Darrenus/tickwitness/actions/workflows/docs.yml)

Find reproducible counterexamples to quantitative research claims under explicit data and execution assumptions.

**Status: planning baseline, 2026-10-25.** This repository currently contains the product and engineering plan. The research engine, SDK, CLI, API, MCP server, and UI are planned, not implemented. There are no measured product performance or adoption results yet.

TickWitness 将研究声明、行情证据、执行假设和反例联系起来，帮助研究员回答：**什么有依据的假设变化会使结论翻转，如何复现，下一步需要采集什么证据？**

The initial product is a local-first research verification toolkit for quantitative developers and researchers. It will integrate an existing replay engine rather than build a trading system. Observation-compatible interpretations and counterfactual stress scenarios have separate semantics. A bounded search which finds no counterexample is not a proof of robustness.

## Read the plan

| Document | Purpose |
| --- | --- |
| [Product strategy](docs/product/product-strategy.md) | Users, workflows, scope, differentiation, product outcomes |
| [Discovery and adoption](docs/product/discovery-and-adoption.md) | User validation, experiments, ecosystem, adoption gates |
| [DDD domain model](docs/architecture/domain-model.md) | Ubiquitous language, bounded contexts, aggregates, invariants |
| [System design](docs/architecture/system-design.md) | Modules, runtime, data flows, APIs, execution and recovery |
| [Architecture decisions](docs/architecture/decisions.md) | Initial decisions and explicit reconsideration triggers |
| [Roadmap](docs/planning/roadmap.md) | 24 two-week Sprints, release gates, capacity assumptions |
| [Sprint backlog](docs/planning/sprint-backlog.md) | Stories, dependencies, acceptance criteria and deliverables |
| [GitHub execution index](docs/planning/github-backlog.md) | Links to 24 planned Sprint milestones and 72 story issues |
| [Agile working agreement](docs/planning/working-agreement.md) | Refinement, Definition of Ready/Done, review and change control |
| [Requirements traceability](docs/planning/traceability.md) | Domain rules and product goals mapped to stories and release evidence |
| [Quality and research validation](docs/quality/quality-strategy.md) | Research correctness, verification matrix and release gates |
| [Security and operations](docs/operations/security-and-operations.md) | Isolation, supply chain, observability, backups and response |
| [Sources](docs/references.md) | Primary references and evidence boundaries |

## Development status

The planning horizon assumes one full-time human maintainer supported by AI tools. Two-week iterations and milestone gates control scope; dates are forecasts, not promises. The early CLI release is a usable incremental product, while v1.0 requires external replication, operational evidence, compatibility guarantees, and maintenance readiness.

The current [milestones](https://github.com/Darrenus/tickwitness/milestones) and [issues](https://github.com/Darrenus/tickwitness/issues) describe planned work. No Sprint dates or product completion claims have been assigned.

Documentation checks can be run now with Python 3:

```sh
python3 scripts/check_docs.py
```

To export the planning source as machine-readable JSON without modifying GitHub:

```sh
python3 scripts/export_backlog.py
```

There is no product installation command yet. Sprint 1 will establish the package and reproducible development environment. Do not interpret proposed directory layouts or API examples as existing functionality.

## Contribute

Start with [CONTRIBUTING](CONTRIBUTING.md). Report product defects with the defect template and propose domain or interface changes with the RFC template. Research results must distinguish observed data, modeled assumptions, empirical search results, and formal guarantees.

## License and data

TickWitness is licensed under [Apache-2.0](LICENSE), selected by the owner on 2026-10-25. Dependency and dataset rights require separate records. No third-party market dataset is redistributed in this planning baseline.
