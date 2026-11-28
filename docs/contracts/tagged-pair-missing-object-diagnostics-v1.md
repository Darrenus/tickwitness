# Tagged-pair missing-object diagnostics v1

Status: FROZEN before implementation, 2026-11-28. S14-03 / F04 / #42.
This contract and [ADR0056](../adr/0056-tagged-pair-missing-object-diagnostics.md)
must be docs-only committed, actually pushed and exact remote revision read back
before implementation. Forecast8h = contract2 + implementation3 + remote
acceptance2 + documentation1, selected once from parent03's original8h.
Original S14 remains32h =20accepted +8selected +4uncommitted (parent01 remainder).
Stable72 parent stories and12/12/8h caps stay; forecasts are not actual effort.

## Observed problem and fixed profile

The existing twelve-role `read_tagged_pair_bundle` uses generic tree validation
for its objects. The real manifest/object deletion test distinguishes neither
missing manifest nor missing declared leaf beyond BundleError. Its installed
`verify-tagged-queue-pair` consumer therefore cannot associate an absent raw,
front receipt or assessment object with the validated manifest's role(s)/SHA.
This is maintainer-observed diagnostic friction, not an external-user claim.

Only this existing twelve-role profile gets a new file-fact error. Its markers,
canonical manifest, quotas, semantic verification and successful receipt remain.
No new schema, domain verdict, SDK method/export, publisher, discovery/repair or
execution authority. Baseline eight-role, finding fourteen-role and search
profiles retain their independent behavior; wrong-profile input remains generic.

## Typed file fact and shared IO primitive

Add `TaggedPairMissingObjectError(BundleError)`, separate from the baseline-only
BundleMissingObjectError and its unchanged baseline wording. The new error has
fixed reason=tagged_pair_object_missing, role, sorted tuple roles and sha256.
Construct it only from the fully validated twelve-role manifest after root and
objects/sha256 containers are safely opened. Alias roles must include every
manifest role referencing that exact digest; role is the first sorted alias.

A small private shared helper may extract the existing completed object-tree
scan into a fact returning the first missing name or None. Keep the baseline
wrapper, error class/message and behavior identical. Generic `_tree_entries`
and search scanning are unchanged. The existing private `_read_file`
missing_object annotation may widen to BundleError so each profile supplies its
own typed error; its transformation stays exclusively around actual os.open
FileNotFoundError with errno ENOENT. Do not build a pluggable diagnostic framework.

During object enumeration validate all encountered names/types without following
links. Remember a declared leaf's actual stat ENOENT and continue scanning so a
later encountered structural fault is not hidden by missing-object selection.
After a completed valid scan, choose the lexicographically smallest missing SHA.
An open-time disappearance after that scan reports its own declared SHA without
an additional transactional scan. Multiple aliases are not duplicate files.

Missing root keeps BundleNotFoundError/exit4. Missing/invalid manifest, missing
objects/sha256 container, unreadable directory, unknown extra entry, symlink,
FIFO/directory/nonregular leaf, permission/EIO/ELOOP/ENOTDIR, size/hash mismatch
and changed read keep generic integrity/IO refusal. Unknown-entry disappearance
is not declared-leaf absence. FileNotFoundError after open, including fstat/read
failure, stays generic. Preserve no-follow/nonblocking opens, bounded reads,
descriptor cleanup, hash/size checks, exact root/container shape and all quotas.
This observes one defect, not a complete missing list, filesystem transaction,
verified remaining objects, authenticated author or semantic finding.

## Command-scoped CLI projection and other callers

Only `verify-tagged-queue-pair` projects these additive fields with its existing
research_store_integrity_or_io_failure/exit3 and empty success stdout:

```json
{"error":{"code":"research_store_integrity_or_io_failure","message":"tagged-pair human diagnostic","reason":"tagged_pair_object_missing","role":"raw","roles":["raw"],"sha256":"64 lowercase hexadecimal characters"}}
```

Message is diagnostic text, not a parsing contract. No source path, host,
signature, repair/retry recommendation, budget, receipt or success field is added.
Keep existing identity-pin priority: malformed expected_bundle_id is rejected
before bundle IO; a well-formed pin is compared only after the original full
read. Missing-leaf context does not assert that this later pin check succeeded.
CLI catches the tagged subtype separately from baseline and only projects its
facts for the target command. It does not classify errors by their text.

`issue-tagged-findings` also consumes a twelve-role source through this reader.
It retains its generic code3 and exact {code,message} error envelope, with no new
reason/role/SHA fields or publisher call on failure. Shared reader human text
may become more precise for this real leaf error; this is explicit, not a promise
to preserve every old human message. Direct callers catching BundleError remain
compatible and can inspect the new subtype. No app service catches/rewrites it.
The fourteen-role finding reader and its CLI, baseline reader and search code/
container semantics remain unchanged. Cover profile isolation in both directions.

## Remote acceptance and bounded installed consumer

All project execution is remote. Prepare disposable synthetic bundles using
existing opaque role fixtures for IO facts, and recorded real callback golden
payloads for semantic success. Do not call an opaque alias fixture a semantic
verification success or run a new native experiment for a diagnostic case.

1. Positive: the real relocated twelve-role golden bundle yields its existing
   canonical receipt byte-for-byte, preserving limitations on author signature,
   historical calibration, source claim and complete-ledger authentication.
2. Negative: delete every unique declared object, full sorted aliases, multiple
   missing objects, a real unlink during stat and a real unlink before open.
   Inventory source and each failed copy around reads; no mutation or success.
3. Unknown: root/manifest/container absence, invalid/canonical/limit/marker
   failures, unsafe/extra entries, IO/permission, altered size/hash/read and
   post-open ENOENT stay original generic refusals. Stat disappearance followed
   by a later structural fault must refuse structurally regardless of scan order.
4. Preserve baseline/search diagnostics and semantic/rehash negatives. Exercise
   the actual issue-tagged-findings twelve-source path with valid existing
   authority and forbidden publisher, not only a mocked top-level CLI error.
5. Add an isolated installed diagnostic helper invoked ONCE after each existing
   smoke_tagged_evidence profile loop, using standard-gt/relocated already made
   by that loop. Work only on disposable copies. Keep all existing2/4 profile
   executions, their frozen research budgets and original calls unchanged.
   The new matrix uses at most24 verify calls, shared90s/perchild15s. No extra
   freeze/reserve/replay/Job/native execution is permitted for these diagnostics.
6. Before CLI import, deny SQLite (both connect aliases), native import, network
   and worker construction with annotation-compatible class guards; forbid
   research repository construction/publication/reservation. Report swallowed
   guard attempts. This is trusted test instrumentation, not a hostile sandbox.
   Inventory all relative names/types/regular size+SHA, with explicit scanning
   errors and no sidecar exceptions. Capture child exit/streams/timeout and both
   source/copy observations before a unified verdict, retaining bounded actual
   differences and transcript hashes so an inventory failure cannot mask child
   evidence. Directory clocks/atime are not immutability promises.
7. Save current source/actual CI checkout/tree, focused JUnit, enclosing job
   outcomes and installed observations. Require this source's complete17-job
   Engineering matrix and actual archive/wheel consumption, not inherited green
   checks, a pytest summary, startup refusal or an unexecuted scenario.

MCP/HTTP DEFER/demandUNKNOWN; parent01's4h stays uncommitted, no parallel feature.
M1 DISABLED/not integrated, M2 unsupported; securityreviewNOT_PERFORMED/
reviewerUNASSIGNED and external-human0/0/PENDING remain. Original5/8/11, golden,
PR94, actual24+prior21=45 and600/10/2 windows are unchanged. No AWS Start/new
qualification/original24 rerun, original-host export/oldACK, reset/refund,
committed-result rerun, outreach, listener or release. CLOSED evidence is immutable.
