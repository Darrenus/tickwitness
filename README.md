# TickWitness

[![Documentation](https://github.com/Darrenus/tickwitness/actions/workflows/docs.yml/badge.svg)](https://github.com/Darrenus/tickwitness/actions/workflows/docs.yml)
[![Engineering](https://github.com/Darrenus/tickwitness/actions/workflows/engineering.yml/badge.svg)](https://github.com/Darrenus/tickwitness/actions/workflows/engineering.yml)

Freeze a scoped quantitative research experiment, audit its replay accounting, and export independently verifiable evidence.

**Status: `0.1.0a1` technical preview candidate, 2026-10-26.** PR #77 established the executable v2 protocol, consumed attempt budgets, accounting/fee audit, scoped bid-marked claim observations, portable evidence export and offline verification. This candidate packages that limited workflow; a version number alone does not mean a GitHub release or PyPI publication exists. The supported profile is EUR/USD and one built-in limit buy. Arbitrary strategy source, confirmation unsealing and counterexample search remain unsupported. User interviews and independent human domain review remain outstanding; consistency checks do not certify actual market fills.

Start with the [quickstart](docs/quickstart.md), [task-specific support matrix](docs/support.md), and [preview notes](docs/releases/0.1.0a1.md). The core install can verify the supplied synthetic evidence without an engine or GPU. Native replay is a separate optional installation. Run compute in a remote Linux environment or CI; Colab is suitable for temporary qualification, while persistent collection and long-lived services require their own deployment validation.

TickWitness 将研究声明、行情证据、执行假设和反例联系起来，帮助研究员回答：**什么有依据的假设变化会使结论翻转，如何复现，下一步需要采集什么证据？**

The initial product is a local-first research verification toolkit for quantitative developers and researchers. It will integrate an existing replay engine rather than build a trading system. Observation-compatible interpretations and counterfactual stress scenarios have separate semantics. A bounded search which finds no counterexample is not a proof of robustness.

## Read the plan

| Document | Purpose |
| --- | --- |
| [Quickstart](docs/quickstart.md) | Clean installation, synthetic replay and portable offline verification |
| [Preview support](docs/support.md) | Tested environments, trust boundaries, compatibility and maintenance scope |
| [0.1.0a1 preview notes](docs/releases/0.1.0a1.md) | Candidate artifacts, release gates and known limitations |
| [Development entry point](docs/development.md) | Locked environment, local checks, package build and current limitations |
| [Data import guide](docs/data-import.md) | Executable import/inspect workflow, format, limits, and trust boundaries |
| [Frozen protocol guide](docs/research-protocols.md) | Bind actual data/source, seal a declaration, read development data and verify confirmation denial |
| [Complete evidence workflow](docs/evidence-workflow.md) | Run import → v2 freeze → budgeted replay → export → portable offline verify |
| [Bounded replay guide](docs/replay.md) | Install the optional engine, qualify a sealed dataset, inspect trace/completeness and compare results |
| [Replay baseline](docs/research/sprint-03-replay-baseline.md) | Ten independent runs, original timings, golden trace and controlled input difference |
| [Engine selection](docs/research/engine-selection.md) | Limited integration decision, partial-fill evidence, timing and queue restrictions |
| [Sprint 1 status](docs/planning/sprint-01-status.md) | Evidence-based progress and remaining external dependencies |
| [Sprint 2 status](docs/planning/sprint-02-status.md) | Implemented data scope and unresolved research/selection gates |
| [Sprint 3 status](docs/planning/sprint-03-status.md) | Adapter, trace and baseline progress with remaining research execution gates |
| [Sprint 4 status](docs/planning/sprint-04-status.md) | Accounting audit, executable protocol, evidence packaging and remaining preview gates |
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

The current [milestones](https://github.com/Darrenus/tickwitness/milestones) and [issues](https://github.com/Darrenus/tickwitness/issues) track the plan and actual progress separately. Data sealing, limited engine selection and frozen declarations are accepted; user discovery and the full trial lifecycle remain open while independent replay engineering proceeds. The later schedule remains a forecast.

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

The CLI now includes `freeze-experiment`, `replay-protocol`, `inspect-attempt`, `inspect-run`, `export-evidence`, and `verify-evidence`, alongside the earlier data/protocol/replay commands. V1 declarations remain non-executable; v2 binds the supported built-in profile and development-only policy. Failed or interrupted attempts consume budget, and ambiguous fee models produce no claim truth. The verifier recomputes source bindings, accounting and valuation without a native engine, while explicitly stating that it has not replayed matching, authenticated an author or audited a complete historical trial ledger. The remaining architecture is a proposed target.

## Contribute

Start with [CONTRIBUTING](CONTRIBUTING.md). Report product defects with the defect template and propose domain or interface changes with the RFC template. Research results must distinguish observed data, modeled assumptions, empirical search results, and formal guarantees.

## License and data

TickWitness is licensed under [Apache-2.0](LICENSE), selected by the owner on 2026-10-25. Dependency and dataset rights require separate records. No third-party market dataset is redistributed in this planning baseline.
