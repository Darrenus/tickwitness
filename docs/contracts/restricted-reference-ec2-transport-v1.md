# Existing EC2 evidence transport and recovery v1

Status: ACCEPTED and frozen before implementation (2026-11-27).

This is an operational transport contract, not a fifth qualification authority.
It supplements [the frozen v3 contract](restricted-reference-ec2-recovery-v3.md)
and [ADR0050](../adr/0050-one-use-detached-ec2-qualification.md). It must not
change any of the qualified source closure, original three operation scripts,
existing lifecycle files, admission clocks, committed results or budgets.

## The existing result remains immutable

The selected qualification source is
`908d56db32439f38686346687a5b43239b1b7264`, run
`ec201aab11254e8bb7cd1573a96a0004`, original boot
`352c3c3d-d057-4ce8-838d-2f46738624bf`, original unit invocation
`4c261176550240faba960a772ebc1048`. Its observed qualifier result is0 and all24
controls passed. Current24 plus prior21 is45; research reservations and replay
invocations are0. The successful report SHA is
`d9d7d7df17b49314d2eaae989947462b83d5a22344a2883169a06d2cb152e12d`.

The original428942-byte archive SHA is
`2b4421e622e0d3a17f0ad3b71495b2285389b6bfaa9fc0879e54e6ebe47230a9`.
It contains553 inventoried regular files and the inventory itself. The complete
historical snapshot has352 entries;187 is the frozen preflight stat/hash subset.
The original604-file local audit is CLOSED, index
`db1f359f6b9d2a83307388630cdb4b4e9014ef83f4f6b741d344f66074c34a73`.
Neither it nor an earlier sealed scope may receive another file or rewrite.

The live handoff started at monotonic370629590641 and ended at490629590641.
Local complete verification finished after this original120s window; the sole
ACK SSH attempt timed out before authentication. No accepted ACK or final
controller reason was observed. A later operation cannot manufacture either,
move the old deadline, mark an old ACK successful, or reinterpret missing bytes
as an empty successful record. The existing qualifier/exporter/ACK are never
repeated to repair this history.

## Separate reader and receiver

Add standalone stdlib operational scripts, separately pinned to their reviewed
Git revision. They do not enter the ten-file qualification closure and import
no old qualification/provider/operation module. In particular, historical
retrieval must not instantiate Ec2Run, call `_live` or `qualification_receipt`,
prepare a plan/policy, reserve a slot, invoke a replay engine, launch a controller,
or run the old helper in any mode.

The reader has only fixed read modes: snapshot, archive, post-records,
capture-env, inventory and three original-journal queries. There is no arbitrary
path/command, repair, export, ACK or qualification entry point. Internal tests
may inject file roots, trusted UID, process observations and clocks into the
production classes; the deployed CLI exposes no test mode or alternate root.

The receiver has two explicit modes:

- `live-receive`: receive an already published archive under its original live
  v3 authority and, only after full verification, invoke its one existing ACK.
- `historical-retrieve`: read existing records only. Its code path has no ACK,
  qualifier, exporter, new authority or deadline-reset operation.

Unknown/missing/duplicate JSON fields, non-JSON constants, bool-as-int and wrong
source/run/boot/schema are refusals, not coercions. Compare JSON objects by
canonical field semantics, without rewriting the retained original bytes.
Nanosecond stat integers must remain exact; no floating-point JSON round trip.
Retain each original producer's encoding gate: v3 authority/operation records
still require canonical JSON plus LF; the original IID may be pretty JSON and
the preload document has its original no-LF encoding. Qualification stdout is
the original noncanonical summary: extract and strictly associate its receipt
fields, without rewriting that stream or weakening other raw-canonical gates.

## Reader file and stream boundary

The actual host remains only `i-0d79530ca78320939`, account010057564982,
ap-southeast-1, m7i.2xlarge, AMIami-09289bc217ad5e9e7, Ubuntu24.04/x86_64.
The reader uses root-owned safe ancestry, O_RDONLY/O_NOFOLLOW descriptors,
regular single-link files, bounded sizes and matching descriptor/path stat
before and after reads. Unsafe ancestors, links, replacements, permission errors,
read failures, partial streams and changed seals never become ABSENT.
Only genuine ENOENT establishes absence. Empty existing files stay PRESENT_EMPTY.
Malformed retained JSON stays retained malformed evidence, not a missing record.

Paths are restricted to the fixed reference ROOT/run/source trees, original
operation directory, selected ten source paths, original lifecycle files and
the single shared last-test-result.env. A private pin set may narrow these paths
but cannot expand the allowlist. Pin data has its own hash and bounded schema;
embedding it in a reviewed private stdin reader changes data only at one literal
marker and is separately sealed. It adds no executable caller content.

The decoded pin set is at most1MiB and has exactly these fields: kind
(`ec2_transport_pin_set_v1`), schema_version (1), observation_id, source_revision,
run_id, original_boot_id, original_invocation_id, original_archive_sha256,
original_archive_bytes, original_ready_sha256, origin_audit_index_sha256, files
and source_files. These identifiers and hashes bind the original values above.
Each files row has exactly path, sha256, bytes and stat; each source_files row
has exactly path, sha256 and bytes. Stat has exactly device, inode, mode, uid,
gid, nlink, size, mtime_ns and ctime_ns, represented as unsigned decimal strings
without leading zeros (except0). Bytes is a nonnegative bounded integer, never
bool. Unknown/missing/duplicate fields or duplicate paths refuse the pin set.
Derive nanosecond strings losslessly from retained original raw JSON or stat
output; never parse them through a floating-point number first.

Stat uses the original nine stable fields, excluding atime. The553 original
inventory entries plus original ready/archive have persisted remote stat pins.
Before and after recovery, require their original bytes/hash/stat to match.
The three retained operation copies also have original source-check stat seals.
The ten /opt source files have original path/bytes/hash closure evidence, but
not a persisted complete set of original inodes: require original bytes/hash and
current before/after inode stability, and label original inode NOT_RECORDED.
Never substitute an extracted local inode for a remote original inode.

An original archive is read as existing bytes only, never regenerated or appended.
Compressed archive maximum is16MiB. Closed regular-member names/types,
uniqueness, bounded decompression, at most10000 source files and64MiB source
payload remain enforced; inventory and tar overhead have a separately bounded
allowance. Inventory hashes/lengths must cover every source member exactly once.
The64KiB per-file cap applies to emitted operational post-records, capture-env
and snapshot content, not all protected pin files. Protected source files are
at most1MiB each, raw cases at most2MiB each and history logs at most1MiB each,
within the64MiB aggregate source-payload bound. Verify these protected files by
hash without embedding their contents in post-record frames. Every read command has a
fixed timeout; record/journal streams are bounded to16MiB and25s plus2s stop
grace. Reaching a bound, nonzero producer status, timeout or truncation is
INCOMPLETE. EOF or an empty stdout alone proves no completeness or absence.

## Live receive within the original window

Prepare, load and qualify the receiver, validators, pins, local destination and
independent authenticated SSH channels before ready can be published. This
contract never authorizes the receiver to launch a qualification. A source
regression or a same-host read is not an independent AWS download.

The first authenticated snapshot binds observed boot, server_now_ns, original
ready bytes/hash/stat, existing archive nine-field stat/SHA and actual current
guard/master observations. Validate its exact source/run/boot/nonce/argv,
unit InvocationID/MainPID, master PID/start ticks and current membership.
The remote monotonic origin is not the receiver's monotonic or UTC origin.

Record local request-start before the RPC. Derive a conservative local bound
from that start plus `min(ready.deadline_ns, ready.outer_deadline_ns)-server_now_ns`.
All subsequent snapshots can only tighten it. Charge the whole RPC/transport,
download, verification, fsync and any read-only reconnect to this same bound.
There is no `now+120s`, renewed waiter, clock-origin assumption or wall-clock
substitution. Require at least15s conservative remaining before beginning ACK;
the existing server-side final live/deadline gate remains authoritative.

Download only the already published archive over independent pinned SSH.
Match stable before/after remote stat/SHA, original ready/archive binding,
exact local bytes/hash and safe archive contents. Validate all24 current raw
cases/tickets/nonces/outcomes/source/run/boot/manifest/clocks/stop/cleanup,
48 stdout/stderr byte hashes, original report/durable terminal SHA/live-boot
receipt,24/45 accounting, zero pending/unconfirmed/poison and retained history.
Retain exact original bytes and fsync local files and their parent before ACK.
An incomplete or inconsistent qualified result is never promoted to success.

Before ACK, open an independent authenticated post-record channel. Its optional
wait-existing-terminal mode is read-only, same original boot/ready/guard-bound
and bounded by the original ready/outer deadline, never a caller future deadline.
It must not delay original Stop or require membership in the service cgroup.
It distinguishes not-yet-published, partial, refused and observed absent records;
only complete stable raw bytes count as retrieved. This channel reduces the
post-ACK shutdown race; it cannot guarantee a record whose producer never commits.
It binds the exact original identity before waiting and never follows a new
InvocationID or reused PID. After normal termination, the original master's
absence is expected and must not discard already bound final bytes. An expired
result can be written after the original deadline: absence at that boundary is
only OBSERVED_ABSENT_AS_OF_DEADLINE, not proof it was never committed.

After all verification and final conservative remaining/identity checks,
exclusively create and fsync a local ACK-intent and its parent BEFORE exec.
Any existing/partial/uncertain intent is USED. Submit one exact ACK to the
original separately pinned908 operation helper. Once submission starts,
connection255, timeout, signal, crash or missing reply permits no retransmission,
new intent, fallback ACK, export or qualification. Recovery is read-only.

ACK command0 alone is not final master acknowledgement, qualification success or
cloud Stop. Retain later original ACK/controller-result/export stdout/stderr
separately from the earlier archive. Whole live transport success requires the
actual matching acknowledged controller result and receipt association, followed
by independent cloud Stop observation and positively observed matching original
manager-exit evidence. Missing exit/fsync-completion evidence remains UNKNOWN.
Seeing complete JSON or a stable stat does not itself prove producer
fsync succeeded. A partial result, fsync uncertainty or exit-code contradiction
keeps closure UNKNOWN; a reader never fsyncs or repairs a producer's old record.
Otherwise preserve the scoped qualification result and explicit transport
uncertainty. Never synthesize an observed code74 from an expected expired branch.

## Fixed historical readback for run0004

The observation ID is `ec2-readback-20261127-run0004-01`. It is not a domain
schema, research attempt, v4 permission, refund or new quota. Use a fresh local
scope linked to the CLOSED604-file audit. No existing evidence is overwritten.

Prepare the complete reviewed/sealed reader/pin/operator packet and remote
regressions BEFORE a necessary Start. Follow the established manual-Start and
access procedure, with the original SSH host fingerprint and current address.
Do not work around an approval rejection through another API or CloudShell.
Never upload the owner's private key to CI, create credentials/IAM, broaden SSH
ingress or create another instance for this recovery.

The retrieval boot must differ from all five known qualification/retrieval boots:
122c5232-f007-4fe1-b555-6797ee475eba,
503b0e3e-0efe-4d7c-99b3-e282176c4c29,
5fc1dec3-13e7-4d43-b584-314aedc95e6b,
5e83ad22-d623-4ddd-87f8-41a27a599f2d and
352c3c3d-d057-4ce8-838d-2f46738624bf.

Before launching a guard, capture and verify the original shared
last-test-result.env bytes/stat/SHA, or its explicit genuine absence. Read it,
never source it. The original lifecycle hook replaces this file after a guard;
replacement guard output must never masquerade as the old qualification result.

Then launch once through the unchanged original lifecycle wrapper with only
`/usr/bin/sleep 300`. Positively record the new retrieval boot, exact sleep300
command, UID, MainPID/start ticks, InvocationID and cgroup. No renewal, longer
window, new service/drop-in or second guard is allowed. The original four-hour
timer and four lifecycle hashes remain unchanged. The short guard and original
ExecStopPost own automatic Stop after disconnect/expiry.

First collect existing controller-result.json, handoff-ack.json, export.stdout,
export.stderr and original ready/archive; also collect controller-start,
qualifier-exit, export-call/consumption/cancel if present, and original qualification
stdout/stderr. For every fixed record retain original bytes, before/after seals,
hashes and a genuine PRESENT/EMPTY/ABSENT/error classification. No original
operation directory, archive, ACK, state, consumption or report is written.

Read three bounded original journal streams: original boot, original unit on that
boot, and original invocation. Use exact `_BOOT_ID=352c3c3dd0574ce8838d2f46738624bf`
and the original invocation above; never current boot, a relative boot index,
hyphenated journal ID or a tail as completeness. Systemd Stop entries may lack
the invocation field, so its subset does not replace boot/unit evidence.

Reconcile the existing13-field controller result and11-field ACK, if present,
against the original ready/source/run/boot/qualifier/report. ACK absence or a
historical expired/74 result closes a failure with evidence; it is not converted
to acknowledged success. Preserve malformed or unavailable records as such.

Recheck all fixed pins and the exact same current retrieval guard before an
early identity-bound `systemctl stop tickwitness-test-session.service`.
If its identity differs, never stop an unrelated same-name unit. If its state is
already inactive, observe cloud Stop. Never renew the guard for more analysis.
At completion, failure or cancellation independently refresh the same AWS
instance and require Stopped/no publicIPv4/DNS. SSH loss is not Stop evidence.

All remote read exits, raw streams, classifications, unchanged24/45 authority,
current guard observations and cloud Stop belong to the fresh recovery audit.
Close writers, seal its file index and independently verify it outside the scope.
It links to rather than edits the original audit. The original failed handoff
remains failed/unknown according to its recovered bytes; successful readback has
its own verified transfer receipt and does not backdate an ACK.

## Execution surface, regression and product boundaries

All project execution/import/tests/syntax/lint/build run remotely. The owner's
desktop performs only authorized native SSH/file transport, static work and inert
fs/hash/JSON/archive evidence inspection. A new production Python receiver must
run on an independent remote execution surface with pre-existing authorized SSH
access; do not silently run it on the desktop or expose the owner's key to obtain
one. This deployment prerequisite does not block native historical readback.
Remote synthetic receiver/reader qualification does not count as a new AWS run.

Remote tests exercise the production reader/receiver and actual existing
Controller/Store; reuse real Ec2Run durable fixtures rather than a shadow ledger.
Test canonical key order and duplicate/type/schema failures, raw stream/tar/hash
attacks, real descriptor/inode/ancestor faults, cross-clock origins/RTT,
deadline/fsync exhaustion, preauthenticated channels and the shutdown race,
permanent ACK intent/unknown reply, no retransmission, historical zero ACK,
actual raw absence/partial/malformed records, original-budget conservation,
independent subprocess/supervisor termination and guard expiry/cancellation.
Temporary CI-only loopback SSH keys/sshd may qualify real transport; never use
the owner's key or treat CI Stop as actual AWS Stop.

M1 stays DISABLED, PR115 Draft/#38 incomplete, human security NOT_PERFORMED and
external-human reproduction0/0/PENDING. Neither automated audit nor owner merge
satisfies those human gates. No listener, hosted mode, strategy execution, GPU,
merge, release or automatic fifth qualification is authorized by this contract.
