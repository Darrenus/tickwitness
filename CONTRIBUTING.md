# Contributing to TickWitness

TickWitness is currently a planning baseline. Read the [roadmap](docs/planning/roadmap.md), [domain model](docs/architecture/domain-model.md), and [working agreement](docs/planning/working-agreement.md) before implementation.

## Before contributing

The project uses [Apache-2.0](LICENSE). Contributions are submitted under the same license. Please open an issue to discuss substantive changes before submitting code. Confirm that you have the right to contribute the code and any accompanying data; third-party material retains its own terms.

Use the story template for an agreed user outcome, the defect template for observed failures, and the RFC template for domain, schema, public API, security, or architectural changes. English or Chinese is welcome. Shared type names, identifiers, and verdict semantics must match the domain model.

## Pull requests

Keep changes scoped to one independently reviewable outcome. Explain the concrete behavior, domain rules, evidence, compatibility and limitations. Reference the story and affected ADR. Add risk-appropriate verification; documentation-only changes do not require fabricated product tests.

Run the currently available documentation checks:

```sh
python3 scripts/check_docs.py
```

Product install, test, and benchmark commands will be added with their implementation. All existing required checks must pass before merge. AI assistance must not be represented as independent human approval; contributors remain responsible for correctness and rights.

## Research reports

Include frozen input references, protocol and scenario versions, engine capabilities, seeds, search budget, stop reason and a reproducible witness when available. Redact secrets and proprietary strategies. State whether scenarios are observation-compatible or counterfactual stress. No-counterexample-found does not mean proved robust.

Report security vulnerabilities according to [SECURITY](SECURITY.md), not in public issues with exploit details or secrets.
