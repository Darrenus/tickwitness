# Python SDK v1

Frozen before S12-01 implementation, 2026-11-16 Asia/Singapore. Owner accepted PR108 at 2026-11-16T05:26:05Z, true merge `667ca69733e95b133b29c1dc479cef585742cc6e`; this accepts S11-03 and its companion journal fix, not this SDK. Original S12-01 capacity12h within S12total34h and ongoing quality capacity remain unchanged; no actual hours claimed. External real humans0 attempts/0 successes/PENDING.

## Supported surface and dependency direction

The initial stable adapter is `tickwitness.sdk`, contract version `SDK_CONTRACT_VERSION = 1`. Its explicit public `__all__` has exactly seven names: `SDK_CONTRACT_VERSION`, `Client`, `SDKError`, `ValidationLimits`, `ImportReceipt`, `ProtocolReceipt`, `DevelopmentRead`. Existing application result/limit classes are re-exported, not duplicated domain models. Internal application/infrastructure import paths are not added to the public compatibility promise.

This initial subset provides a real data-to-declaration-to-bounded-development-observation workflow. It does not expose executable-v2 runs, Jobs, search, confirmation exposure, maintenance or arbitrary strategy/engine callbacks. Those existing CLI capabilities retain their own contracts; they do not silently become stable SDK interfaces. A future supported SDK capability requires another explicit additive contract/qualification. SDK v1 stability does not mean platform GA: package remains0.2.0.dev0, Python3.12–3.14 and existing local POSIX support; no new dependency, version, format or database migration.

SDK and CLI are driving adapters over the SAME `application.datasets` and `application.research` functions and existing storage/safe-input adapters. Never implement SDK by calling CLI, constructing argparse namespaces, launching CLI subprocesses or duplicating validation/research business rules. No CLI refactor is required to replace application services that are already shared.

## Exact public signatures

`Client` is a frozen, slots, keyword-only configuration dataclass: `Client(*, store: Path, registry: Path)`. Construction only stores paths; no protected filesystem access, directory creation, connections, ledger, native import or execution. It owns no persistent handle and requires no `close()`/context manager. Paths are trusted owner configuration, interpreted as supplied under the caller's cwd; examples use absolute roots. Parents/root retain existing trust boundaries; this is not hostile-owner isolation.

| Method | Signature and result | Existing application service |
| --- | --- | --- |
| import_events | `(input: str, *, input_root: Path, limits: ValidationLimits \| None = None) -> ImportReceipt` | datasets.import_events |
| inspect_dataset | `(dataset_id: str) -> ImportReceipt` | datasets.inspect_dataset |
| freeze_protocol | `(input: str, *, input_root: Path, strategy_source: str, development_dataset_id: str, confirmation_dataset_id: str) -> ProtocolReceipt` | research.freeze_protocol |
| inspect_protocol | `(protocol_id: str) -> ProtocolReceipt` | research.inspect_protocol |
| read_protocol_data | `(protocol_id: str, *, split: Literal["development", "confirmation"] = "development", limit: int = 100) -> DevelopmentRead` | research.read_protocol_data |

`input`/`strategy_source` are relative paths under `input_root`, through existing no-follow `read_jsonl`/`read_regular_file`, never `Path.read_bytes()` shortcuts. Import defaults to `ValidationLimits()` (8MiB/100000records/65536line bytes/1000levels); protocol request64KiB and strategy source256KiB have the existing `.json`/`.py` restrictions. Validation precedes destination construction/publication. Strategy source is parsed/bound, never executed. Read-only adapters use `create=False`.

Identity arguments must be lowercase64hex strings. Adapter identity framing rejects invalid strings before protected IO as `SDKError("invalid_sdk_argument", ..., 2)`; CLI argparse likewise refuses them with2 but has its own usage-text framing. This is a declared adapter difference, not JSON-equivalence for invalid parser input. Wrong Python argument types/unknown keywords remain programming errors (e.g. TypeError), not blanket user-validation errors.

For `read_protocol_data`, ANY non-development split is rejected by the existing application service BEFORE identity checks, registry/dataset factories or protected IO. Literal annotations document supported requests, not runtime authority. Then development calls retain real-int limit1..1000 checks and frozen `max_events`; a wrapper cannot increase those limits. Existing unknown `receive_time_ns=None`, quarantine/report semantics and forward-disjoint binding stay unchanged. Accepted data, frozen declaration and development observations do not certify replay, clock accuracy or a research claim.

## Value and error contracts

`ValidationLimits` retains four positive real-int fields/defaults and its existing ValueError-derived validation on construction; bool is refused. Construction of this value occurs outside Client's exception translation. Result dataclasses retain exact existing fields/order/types: ImportReceipt(dataset_id, created, manifest, report); ProtocolReceipt(protocol_id, claim_revision_id, created, document); DevelopmentRead(protocol_id, dataset_id, observations, total_records, truncated). JSON fields remain schema-governed `dict[str, object]`; observations are a tuple of detached dictionaries. Values are shallow frozen, NOT recursively immutable. Mutating nested returned JSON cannot alter persisted evidence or later fresh results. `created` means Catalog/registry insertion, not a CAS write; inspect returnsfalse, explicit duplicate publication returnsfalse.

`SDKError(code: str, message: str, exit_code: int)` is a RuntimeError with stable `code`/`exit_code` attributes, normal message and original exception as `__cause__` for translated errors. `as_dict() -> dict[str, object]` returns a fresh `{"error":{"code":...,"message":...}}`, matching covered CLI error JSON; message wording is diagnostic, not a cross-version compatibility promise. Exact covered mapping:

| Error code | CLI-compatible exit | Scope |
| --- | ---: | --- |
| unsafe_input | 2 | Existing safe-input refusal |
| invalid_data | 2 | DataValidationError |
| invalid_protocol | 2 | ProtocolValidationError |
| confirmation_access_denied | 5 | Application admission before IO |
| dataset_not_found | 4 | DatasetNotFoundError |
| store_integrity_or_publication_failure | 3 | Other DatasetStoreError |
| protocol_not_found | 4 | ProtocolNotFoundError |
| protocol_integrity_or_publication_failure | 3 | Other ProtocolRegistryError |
| io_failure | 3 | Other OSError |
| invalid_sdk_argument | 2 | SDK-only identity framing above |

Specific not-found and confirmation errors precede their base classes. Do not catch arbitrary ValueError/Exception, fabricate success/empty observations or hide programming bugs. No automatic retries, research execution, admission/reservation or budget reset/refund. The five methods do not consume research attempts; bounded reads still obey the ORIGINAL frozen declaration budget. Existing5/8/11-slot histories/committed results/golden/PR94 remain untouched.

## Real consumer and acceptance

Ship a typed stdlib+SDK consumer in `examples/sdk/`. Copy the actual shipped file into an independent directory and execute it with `-I` under a separately installed core wheel, not editable/source imports; source profile uses actual sdist driver AND consumer. The consumer imports only public SDK plus stdlib and produces a deterministic downstream observation summary, not a mocked UI or profitability claim. Record executable/prefix/origin/version/py.typed, full source/SHA, invocation/cwd/stdout/stderr/exit and resulting persistent evidence.

Compare SDK and actual CLI first receipts on TWO initially equivalent fresh store/registry roots; then independently compare duplicate/inspect/read outputs, including createdtrue→false, every field/identity, unknown time and truncated observations. Tuple→JSON array and final CLI newline are ordinary encoding; no field is discarded to manufacture parity. Assert exact persistent dataset/strategy/protocol closure and explicit downstream summary. Negative/unknown/refused cases include invalid data before destination creation, unsafe path/symlink, bounded/frozen max_events refusal, valid-but-missing identity, corrupt object read refusal, returned-JSON mutation isolation, and confirmation denial with nonexistent roots. No protected IO may precede the latter refusal.

Run downstream `mypy --strict` against the actual installed typed wheel, with positive consumer and a negative fixture whose specific expected errors are asserted, not any failing type command. Preserve py.typed/export/signature/default/field compatibility evidence. Keep17 existing checks, original timeouts and four controls jobs. Append separate `sdk-consumer-PROFILE-CHECKOUT` payloads; original controls/retention/fault drivers, schemas and separate artifacts stay unchanged. Binary-hash all three original trees before/after SDK qualification; never open their live Dataset Catalogs or construct their stores. New qualification uses no native import/call or reservation, with actual guards and bounded child processes; failure preserves incomplete evidence and cannot report acceptedtrue.

Qualification admits at most32 children, each ordinary wait at most30seconds within an overall180second monotonic admission/wait budget. Exhaustion stops visibly without launching later work, retains finished evidence and reports incomplete, not acceptedtrue. These bounds do not certify physical kernel-IO/reap deadlines and are not a new research quota. Record actual counts/timing and distinguish normal subprocess transport in the harness from forbidden child research/native/network actions.

All project/Python/import/tests/lint/format/type/build/install/native execution stays REMOTE GitHub Actions CPU ONLY. Local work is static/Git/gh/hash/inert archive/closed readonly immutable DATA after sidecar preflight. Complete current CI, independent payload/source/package audit, exact publication readbacks and owner acceptance remain separate gates. Automated consumer qualification is not external-human activation or30-day reuse; those stay0/0/PENDING. HTTP remains conditional S14 or later, GPU deferred, no release/adoption/profit claim.
