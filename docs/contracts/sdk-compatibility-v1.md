# SDK compatibility and executable documentation v1

Frozen before S12-03 implementation, 2026-11-18 Asia/Singapore. Owner accepted PR111 at 2026-11-18T14:37:31Z, true merge `d7696ba01f92a58a3bb26f6b58e421a30698c93a`, accepting candidate `cfce0128b6247d239dc56975a9b4565f3af90b14`. Its actual CI checkout `06ff8c0aa2b809cff41e10c9d8d4be0d012658a9` and preacceptance archive remain separate. Original S12-03 capacity 8h / S12 total 34h (12+14+8), with unchanged ongoing quality capacity; no actual hours claimed.

## Scope and authority

This qualifies and documents the existing [SDK v1 subset](python-sdk-v1.md), not a new SDK or wire protocol. Keep SDK_CONTRACT_VERSION=1, five methods, seven exports, existing application services, result types, error codes, dependencies and production validation unchanged. Do not add a receipt JSON decoder, ignore-unknown wrapper, CLI subprocess SDK, new DTO, generic compatibility framework or second validator. Domain schemas remain owned by their existing bounded contexts.

The current gap is adapter regression and the connection between instructions and actual installed execution. A behavior defect, if found, must retain its observed failure and receive an explicit scoped correction; do not silently change a domain rule to make a compatibility case pass.

## Unknown does not mean ignored

| Boundary | Existing behavior to preserve and qualify |
| --- | --- |
| Normalized event schema/fields | Unsupported versions, missing fields and unknown fields refuse as invalid_data / 2; never strip fields and accept. Invalid event validation precedes the target store factory. |
| Declaration request, claim, configuration and budget objects | Exact-key schemas refuse unknown/missing keys as invalid_protocol / 2. No registry creation or protocol publication; existing input/data evidence stays unchanged. Do not promise all protected IO is avoided: the SDK can construct the existing DatasetStore(create=False) before application request validation. |
| Declaration parameters | Deliberately open bounded scalar map. Valid custom names/values are preserved in the frozen document and protocol identity; object/list values refuse. A parameter named execution_ready does not change top-level execution_ready=false, the frozen budget or authority. Claim identity remains governed by the claim alone. |
| Python keyword/signature misuse | Native TypeError, distinct from SDKError; no blanket exception translation or hidden argument dropping. |
| Returned values | Existing dataclass fields/order/defaults and detached nested JSON remain SDK v1. No public receipt-JSON ingest exists; do not invent future-receipt compatibility by discarding fields. |
| Stored dataset report | Inspect verifies the existing hash/canonical storage closure and preserves its JSON fields; this alone does not certify normalized research semantics. Binding/reading accepted research data independently normalizes and compares the complete report, refusing mismatches, including extra fields. |
| Unknown receive time | None remains unknown; it is not an extension key, zero, event time or permission to replay. |

Use real SDK/CLI entry regressions over valid inputs with a changed field, not duplicate validators. Cover exact errors/exits and publication boundaries; cover an open scalar parameter as a positive case, object/list parameters as refusals, and unknown observation time without coercion. A stored-report test may reuse existing real storage fixtures to distinguish preserved inspection from refused binding. Keep confirmation denial and malformed identity's existing stronger admission-before-IO guarantees.

## One executed documentation recipe and the real consumer

The current SDK guide has one explicitly named Python fence, `sdk-example:import-and-inspect:v1`. It defines `import_and_inspect(input: str, *, input_root: Path, store: Path, registry: Path) -> ImportReceipt` using public SDK plus stdlib, with caller-supplied paths and the existing services. Return the inspected receipt; document that inspect.created=false does not describe whether the preceding import inserted data. SDKError propagates; do not hide failures. No new tutorial program or executable SDK feature is introduced.

The existing smoke driver reads the actual guide bytes, extracts exactly that named Python block, saves the full source/hash, copies it into an independent owned directory and actually executes/calls it using the separately installed core wheel. Record real arguments, cwd, outputs, exit, returned receipt and persistent bytes. Reject a missing/duplicate/wrong-language block. This is an explicit trusted repository example allowlist, not an arbitrary Markdown/shell executor. SOURCE uses the actual sdist's driver, guide and examples.

Keep the existing complete development_consumer.py workflow. Give its README invocation one explicit named template, `sdk-consumer-invocation:v1`; parse only its declared placeholders/flags and bind the substituted logical consumer arguments to the actual guarded invocation. The harness still uses its -I/-B guarded wrapper/runpy; do not claim the placeholder shell text was executed verbatim. Save full README/template bytes/hash and actual argv. No source PYTHONPATH, editable import, native/network/subprocess/research authority is allowed inside the consumer guard. If the recipe joins the existing positive installed type command, reuse that same command/admission; retain the exact three intentional negative diagnostics and never execute the negative fixture.

## Original shared qualification budget

Reuse smoke_sdk.py, check_sdk_typing.py, the four existing controls profiles/artifact families and original supervisor. Planned functional invocations are the original 24 plus one documentation child and two representative CLI refusals (unknown event field and unknown budget field): 27. Put the SDK unknown-field matrix and isolated open-parameter case in the existing negative batch, not new hidden child processes. Keep functional maximum 28, reserve four typing admissions, total maximum 32, single wait at most 30 seconds and the SAME original 180-second monotonic deadline. Planned combined count is 31, not a new allowance. All actual counts, remaining budget and deadline inheritance must be recorded; exhaustion stops without launching later work and retains incomplete evidence, never accepted=true.

Keep existing qualification kind/schema and fields; add explicit documentation/compatibility observations under this contract. This qualification payload is not a new product input schema or SDK receipt format. Preserve real transcripts, source identities, fresh owned output roots, publication refusals and full new dataset/protocol closure. Extra owned declaration fixtures have no executable authority. All three old controls/retention/fault trees are only binary-hashed before/after; do not open their Catalogs or initialize their stores. New native calls/research slots remain zero; historical 5/8/11-slot research, golden and PR94 are unchanged. Actual research retries still use the SAME original protocol ledger, with no reset/refund or repeat execution of committed results.

## Versioned support and self-service

Keep published 0.1 quickstart/tag/artifact facts intact and route current 0.2.0.dev0 SDK users explicitly. Distinguish declared Python 3.12–3.14 support and six core source-regression environments (Ubuntu 24.04/macOS 15) from actual installed SDK consumer/strict-type qualification: four existing profiles, all Python 3.12, including macOS 26 and Ubuntu source-wheel. Native qualification is separate and fixed to its existing profile/engine. No untested Windows, musl, remote filesystem or arbitrary strategy/crypto support follows from py3-none-any or a green source test.

Self-service instructions map SDKError codes to the existing supported diagnosis/recovery paths, retain original errors and unconfirmed publication state, and distinguish programming errors. No automatic retry, root deletion/reinitialization, clock substitution, confirmation bypass or refund is a recovery recipe. Job/maintenance capabilities are linked to their CLI contracts, not mislabeled as SDK methods.

Record HTTP/MCP planning interest separately from a verified blocked task, case, alternative, evidence/source, consent and decision. An empty verified demand record means UNKNOWN/insufficient evidence, not proved no demand. Keep the existing conditional S14-or-later entrance gate; no HTTP/MCP implementation in this story.

## Qualification and remaining gates

All project/Python/import/tests/lint/format/type/build/install/native execution is REMOTE GitHub Actions CPU only. Keep the original 17 checks and timeouts. Require actual current-head success, real executed documentation, installed unknown-field refusals, preserved open parameters/unknown time, and four new SDK functional/type payload audits bound to actual source/wheel/records and the common budget. Preserve old three-tree guards; do not relabel their green jobs as 16 new FULL DATA audits. Do not inherit prior green or manufacture tests that only assert a template exists.

Owner acceptance, CI/AI review and real-user evidence are separate. #36 stays OPEN until owner accepts this slice. External-human reproduction remains 0/0/PENDING (#24 OPEN), actual own-case registry empty; activation/value/30-day reuse are not supplied by automated examples. No release, GA, profitability, outreach, GPU or automatic merge is authorized here.
