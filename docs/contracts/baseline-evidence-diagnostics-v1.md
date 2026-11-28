# Baseline evidence missing-object diagnostics v1

Status: FROZEN before implementation, 2026-11-27. The contract and
[ADR0052](../adr/0052-baseline-evidence-missing-object-diagnostics.md) must be
committed, actually pushed and their remote revision read back before code
changes. This is S14-01a / #40, a first8h forecast within the original S14
32h. The remaining24h is uncommitted; MCP/HTTP remain DEFER because verified
task blockage and participant demand evidence remain UNKNOWN.

## Observed problem and boundaries

The baseline reader's `_tree_entries` reports the same generic missing-required-
entry error for a missing manifest and a missing manifest-declared CAS object.
The existing real-filesystem negative test deletes both kinds of entry, while
the CLI returns `research_store_integrity_or_io_failure`, exit3, without the
declared object's roles or SHA. Search evidence already has its own precise
missing-object diagnostic; its separate profile and code are unchanged.

This is maintainer-observed diagnostic friction, not an invented external-user
complaint. Improve only the existing baseline `verify-evidence` failure path.
Infrastructure reports bounded file facts; application verification retains
semantic/accounting authority; CLI projects the error. No domain aggregate,
SDK method, endpoint, repair API, persistent format or bundle schema changes.
Existing valid verification receipts remain identical.

## Narrow typed absence

Add `BundleMissingObjectError` as a subtype of existing `BundleError`, carrying
`role`, `roles` and `sha256` associated solely with the already validated v1
manifest. A missing root remains `BundleNotFoundError` / exit4. A missing or
invalid manifest, missing `objects`/`sha256` container, unreadable directory,
unsafe path or other IO/integrity failure stays the existing generic failure;
none supplies an invented declared-object identity.

Only classify an absent **declared object leaf** after valid manifest parsing
and safe directory opening. This includes a leaf absent from the bounded exact
object-tree scan and genuine `FileNotFoundError`/ENOENT from inspecting/opening
that declared leaf. Permission errors, ELOOP/ENOTDIR and other IO errors do not
become absence. Symlink/FIFO/nonregular/unknown extra entries, wrong sizes,
changed reads and hash mismatches retain integrity refusal. Do not follow a
link or block on a special file to improve a diagnostic. Keep the existing
generic `_tree_entries` behavior for other directories and callers.

Validate encountered tree entry names/types before reporting scan-observed
absence, so an unsafe extra or nonregular object is not accepted as a normal
tree with a missing member. Keep structural failures as structural failures.
This preserves the existing trusted-root/ancestor assumptions; it does not
authenticate an owner, provide hostile-path secrecy or establish a filesystem
transaction. A genuine observed disappearance is not a complete race history.
During enumeration, remember a known leaf's ENOENT and finish inspecting the
remaining entries before selecting a missing object; scan order cannot hide an
encountered structural fault. An open-time ENOENT after that completed scan may
report that leaf without a second transactional scan. It makes no claim about
other entries concurrently changed after the original inspection.

For multiple scan-observed missing objects, report the lexicographically first
SHA. For an open-time disappearance, report that leaf's SHA. Set `roles` to all
manifest roles that reference that SHA, sorted lexicographically; `role` is the
first alias. Deduplication must not omit aliases or manufacture one role per
physical file. This reports one observed defect, not an exhaustive audit or a
claim that other objects are valid. No semantic receipt or finding is issued.

## Additive CLI projection

Keep stderr JSON and the existing error code and exit status:

```json
{"error":{"code":"research_store_integrity_or_io_failure","message":"human-readable diagnostic","reason":"bundle_object_missing","role":"raw","roles":["raw"],"sha256":"64 lowercase hexadecimal characters"}}
```

The new machine-readable fields are present only for this typed absence.
`message` remains diagnostic text, not a parsing contract. The SHA comes from
the bounded validated manifest, not a caller-controlled filesystem path;
role names remain within the eight fixed v1 roles. Add no private root path,
host identity, ledger path, execution permission, success flag, automatic
recovery recommendation or speculative zero counters. Do not repurpose the
search profile's existing error code. Other baseline errors and successful
stdout remain unchanged.

The same typed diagnostic is available to direct baseline-reader callers;
existing callers catching `BundleError` remain compatible. It is not a bundle
format/schema version or a new persisted result kind.

## Recovery and authority

Preserve original bytes and raw failure. The diagnostic identifies what the
manifest declared; the caller may obtain separately authorized matching bytes
from its known source and verify a separate complete copy. No automatic write,
download, alternate-store discovery, source execution, native engine, SQLite
connection, reservation, replay, confirmation access or reconciliation is added.
Do not repair the caller's tree, recreate a missing root, reset a ledger, refund
a failed slot or repeat an already committed result. Any real rerun still needs
a new available slot of its same original frozen protocol.

M1 stays DISABLED, M2 unsupported, independent human security NOT_PERFORMED and
external-human reproduction0/0/PENDING. This change grants no AWS Start, new
qualification, original-host export/old ACK, listener, outreach or release.
Original reference24/current24+prior21=45 and600s/10s/2s windows stay unchanged.

## Remote acceptance

All project imports/checks/tests/builds run remotely. Static editing and inert
inspection do not substitute for the following actual current-head evidence:

1. A valid relocated baseline bundle returns its unchanged receipt in an
   installed core-only environment without native import or SQLite access.
2. Delete each declared object only from disposable synthetic copies; verify
   the exact deterministic role(s)/SHA and unchanged code/exit3, empty success
   stdout, original/copy byte inventory unchanged by the failed read.
3. Cover shared-object aliases and multiple missing objects, plus an observed
   leaf disappearing between enumeration and open. No false complete result.
4. Missing root remains exit4/no creation; missing/invalid manifest or absent
   containers stays generic/no fabricated roles. Permission errors, symlinks,
   FIFO, extra entries, changed sizes and corruption never become typed absence.
5. Preserve existing baseline/search/publication/semantic negative regressions;
   actual installed CLI output distinguishes only the allowed new case. No
   reference budget, existing user records or source tree is modified.

Record real source/CI checkout/tree and terminal outcomes. A passing test
summary without successful job exit, a startup refusal or an unexecuted scenario
does not become acceptance. No new test may run a project payload on the owner
workstation, invoke the consumed actual qualifier or rewrite a CLOSED audit.
