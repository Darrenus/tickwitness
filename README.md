# TickWitness

[![Documentation](https://github.com/Darrenus/tickwitness/actions/workflows/docs.yml/badge.svg)](https://github.com/Darrenus/tickwitness/actions/workflows/docs.yml)
[![Engineering](https://github.com/Darrenus/tickwitness/actions/workflows/engineering.yml/badge.svg)](https://github.com/Darrenus/tickwitness/actions/workflows/engineering.yml)

Freeze a scoped quantitative research experiment, audit its replay accounting, and export independently verifiable evidence.

**Status: Sprint 8 alpha scorecard and external reproduction kit in progress, `0.2.0.dev0`, 2026-10-28.** The [technical preview v0.1.0a1](https://github.com/Darrenus/tickwitness/releases/tag/v0.1.0a1) is published. Owner-merged PRs #79–93 accepted persistent replay/queue evidence, frozen search plans, campaign budgets, [scoped findings](docs/contracts/search-findings-v1.md), [portable search evidence](docs/contracts/search-evidence-v1.md) and [one-time confirmation access](docs/contracts/confirmation-access-v1.md). This branch adds a [technical alpha scorecard](docs/contracts/alpha-scorecard-v1.md) and [transferable reproduction kit](docs/alpha-reproduction.md): re-audit two actual frozen synthetic cases, rerun invalid-perturbation validation and controlled publication failures, then capture real reproduction submissions. Remote acceptance is pending. An external participant is being contacted by the owner; external attempts remain **0 / PENDING** until actual evidence is received and reviewed. Automated CI, AI review and owner acceptance do not satisfy that gate. No new release, strategy execution, research attempts or confirmation finding is granted by this scorecard.

Start with the [quickstart](docs/quickstart.md), [task-specific support matrix](docs/support.md), and [preview notes](docs/releases/0.1.0a1.md). The core install can verify the supplied synthetic evidence without an engine or GPU. Native replay is a separate optional installation. Run compute in a remote Linux environment or CI; Colab is suitable for temporary qualification, while persistent collection and long-lived services require their own deployment validation.

TickWitness 将研究声明、行情证据、执行假设和反例联系起来，帮助研究员回答：**什么有依据的假设变化会使结论翻转，如何复现，下一步需要采集什么证据？**

The initial product is a local-first research verification toolkit for quantitative developers and researchers. It will integrate an existing replay engine rather than build a trading system. Observation-compatible interpretations and counterfactual stress scenarios have separate semantics. A bounded search which finds no counterexample is not a proof of robustness.

## Read the plan

| Document | Purpose |
| --- | --- |
| [Quickstart](docs/quickstart.md) | Clean installation, synthetic replay and portable offline verification |
| [Preview support](docs/support.md) | Tested environments, trust boundaries, compatibility and maintenance scope |
| [0.1.0a1 preview notes](docs/releases/0.1.0a1.md) | Candidate artifacts, release gates and known limitations |
| [Scenario workflow](docs/scenarios.md) | Validate declarations, execute budgeted stress, re-audit baseline/scenario pairs and locate trace changes |
| [Queue workflows](docs/queues.md) | Verify gross flows, execute both models with one budget, and inspect paired semantics without promoting sensitivity to a finding |
| [Conserved tagged queue contract](docs/contracts/tagged-queue-v1.md) | Freeze a separate conditional claim and total-depth projection, partition trades once, and mark inventory before administrative cleanup |
| [Portable tagged pair evidence](docs/contracts/tagged-pair-evidence-v1.md) | Export both committed witnesses, relocate the sealed closure and independently re-audit with core only |
| [Frozen tagged finding authority](docs/contracts/tagged-findings-v1.md) | Freeze a separate scoped report authority, issue deterministic findings and verify the full fourteen-role closure with core only |
| [Frozen search candidate plans](docs/contracts/search-plan-v1.md) | Reproduce grid/random proposals, preserve duplicate and rejection decisions, and recheck the actual development source |
| [Persistent candidate execution](docs/contracts/search-execution-v1.md) | Run eligible candidates against the original shared budget and re-audit their dispatch/attempt/outcome links with core only |
| [Supervised campaign budgets](docs/contracts/campaign-budgets-v1.md) | Freeze evaluation, execution-time and managed-payload limits; stop explicitly and preserve committed results |
| [Scoped search findings](docs/contracts/search-findings-v1.md) | Freeze a separate stress criterion and re-audit exact witnesses, coverage, budget stops and unknown cases |
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

The CLI includes `freeze-experiment`, `replay-protocol`, `inspect-attempt`, `inspect-run`, `export-evidence`, and `verify-evidence`, alongside the earlier data/protocol/replay commands. Development-only `validate-scenario` remains a read-only input check with `execution_approved=false`. Separate `run-scenario` persists intent before native execution and consumes the original protocol's attempt budget; `inspect-scenario-run` recomputes its view and accounting without replay. `compare-scenario-runs` re-audits two committed runs, validates their shared source/model, and reports exact metric differences plus raw and business trace changes. It consumes no attempt and makes no global earliest-cause or baseline-claim verdict. Scenario receipts are distinct from baseline claim observations and cannot enter baseline evidence-bundle v1. V1 declarations remain non-executable; v2 binds the supported built-in profile and development-only policy. Failed or interrupted attempts consume budget, and ambiguous fee models produce no claim truth. Verification does not authenticate an author or audit a complete historical trial ledger. The remaining architecture is a proposed target.

## Contribute

Start with [CONTRIBUTING](CONTRIBUTING.md). Report product defects with the defect template and propose domain or interface changes with the RFC template. Research results must distinguish observed data, modeled assumptions, empirical search results, and formal guarantees.

## License and data

TickWitness is licensed under [Apache-2.0](LICENSE), selected by the owner on 2026-10-25. Dependency and dataset rights require separate records. No third-party market dataset is redistributed in this planning baseline.
