# TickWitness

[![Documentation](https://github.com/Darrenus/tickwitness/actions/workflows/docs.yml/badge.svg)](https://github.com/Darrenus/tickwitness/actions/workflows/docs.yml)
[![Engineering](https://github.com/Darrenus/tickwitness/actions/workflows/engineering.yml/badge.svg)](https://github.com/Darrenus/tickwitness/actions/workflows/engineering.yml)

Find reproducible counterexamples to quantitative research claims under explicit data and execution assumptions.

**Status: Sprint 2 frozen-protocol development, 2026-10-26.** Data-evidence import and integrity inspection were accepted in PR #74. The current branch adds frozen research declarations bound to real datasets and strategy source, immutable protocol registration, development-only reads, and confirmation-read denial. NautilusTrader 1.231.0 is the proposed limited L2 integration target; its product adapter, replay, search, the research SDK, API, MCP server, and UI are not implemented. Real interviews remain outstanding; there are no measured product performance or adoption results yet.

TickWitness 将研究声明、行情证据、执行假设和反例联系起来，帮助研究员回答：**什么有依据的假设变化会使结论翻转，如何复现，下一步需要采集什么证据？**

The initial product is a local-first research verification toolkit for quantitative developers and researchers. It will integrate an existing replay engine rather than build a trading system. Observation-compatible interpretations and counterfactual stress scenarios have separate semantics. A bounded search which finds no counterexample is not a proof of robustness.

## Read the plan

| Document | Purpose |
| --- | --- |
| [Development entry point](docs/development.md) | Locked environment, local checks, package build and current limitations |
| [Data import guide](docs/data-import.md) | Executable import/inspect workflow, format, limits, and trust boundaries |
| [Frozen protocol guide](docs/research-protocols.md) | Bind actual data/source, seal a declaration, read development data and verify confirmation denial |
| [Engine selection](docs/research/engine-selection.md) | Limited integration decision, partial-fill evidence, timing and queue restrictions |
| [Sprint 1 status](docs/planning/sprint-01-status.md) | Evidence-based progress and remaining external dependencies |
| [Sprint 2 status](docs/planning/sprint-02-status.md) | Implemented data scope and unresolved research/selection gates |
| [Engine feasibility comparison](docs/research/engine-comparison.md) | Version-fixed synthetic spike evidence and unresolved selection gates |
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

The current [milestones](https://github.com/Darrenus/tickwitness/milestones) and [issues](https://github.com/Darrenus/tickwitness/issues) track the plan and actual progress separately. Two Sprint 1 engineering stories are accepted; user discovery remains open while independent data-evidence engineering proceeds. The later schedule remains a forecast.

For development, install uv 0.12.13 and use the locked Python environment:

```sh
make sync
make check
make build
```

To export the planning source as machine-readable JSON without modifying GitHub:

```sh
uv run --locked python scripts/export_backlog.py
```

The installed CLI provides `import-events`, `inspect-dataset`, `freeze-protocol`, `inspect-protocol`, and `read-protocol-data`; the guides provide complete local examples using synthetic fixtures. Sealing verifies content integrity. Frozen declarations remain `execution_ready=false`, and confirmation denial is an application routing policy, not secrecy from the host owner. Strategy execution and research verdicts arrive in later Sprints; the remaining architecture is a proposed target.

## Contribute

Start with [CONTRIBUTING](CONTRIBUTING.md). Report product defects with the defect template and propose domain or interface changes with the RFC template. Research results must distinguish observed data, modeled assumptions, empirical search results, and formal guarantees.

## License and data

TickWitness is licensed under [Apache-2.0](LICENSE), selected by the owner on 2026-10-25. Dependency and dataset rights require separate records. No third-party market dataset is redistributed in this planning baseline.
