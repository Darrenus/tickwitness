# Unlinked open Job journal read conflict v1

Status: FROZEN before the companion fix, 2026-11-28, PR118 quality maintenance.
Commit, actually push and read back this contract, [ADR0054](../adr/0054-unlinked-open-journal-read-conflict.md)
and the linked [Job lifecycle correction](job-lifecycle-v1.md) before product changes.
This is one companion defect within unchanged ongoing quality capacity, not an
extra S14 feature allocation: original32h remains8accepted+8selected+16uncommitted.
No actual-effort or new research-budget claim is made.

## Actual failure and limits of attribution

PR118 source4ce1c2fd525dcbba559793874d05af1063f68161, Engineering46106859048,
macos-15/Python3.14 job140861567990 actually failed
infrastructure/test_job_control_supervisor.py::test_durable_cancel_from_another_controller_stops_live_owned_process[True-True].
The controller caught JobStoreError('Job catalog files must be unaliased regular files');
pytest recorded1failed/5679passed/150skipped,736.53s and make exit2. The inner
exception traceback, filename and inode were not recorded, so this is not proof
of a particular failed file or syscall race. Preserve the genuine failure; do not
call it a timeout, automatic cancellation, passed test or confirmed root cause.

Native source comparison shows the failing old Job adapter and supervisor test
were unchanged by F02. Existing journal-race tests cover disappearance before open
or final restat but not a real COMMIT after successful open and before first fstat.
A normal rollback-journal unlink can leave that regular open inode at nlink0,
which currently produces the observed strict error instead of a bounded conflict.
This mechanism must first be reproduced remotely against unchanged code, rather
than assumed from the error string. Fix the concrete gap without claiming to
recover the missing original inner trace or certify every possible cause.

## Narrow classification

Preserve the generic regular-file, no-follow, alias, header, schema and identity
checks. Add an internal flag only for the existing fixed optional
catalog.sqlite3-journal preflight, enabled by the enclosing _connection(write=False).
The journal descriptor's own O_RDONLY mode is insufficient: writer preflight also
reads journal metadata and must never gain this conflict route.

Only when all of these are true may the existing read-conflict route apply:

1. The internal flag is enabled, the exact fixed journal name is being checked,
   the descriptor was opened read-only, and its first actual fstat says regular
   file with st_nlink exactly0.
2. A fresh named os.stat with the same root descriptor and follow_symlinks=False
   actually raises FileNotFoundError with errnoENOENT. Propagate that original
   exception into the existing scoped optional-journal read handler.
3. Close the open descriptor, yield no descriptor or SQLite connection and return
   the existing JobConflictError / job_conflict / exit9, with real ENOENT cause.

This only refuses the current observation. It does not authenticate a normal
writer, certify the entire history or automatically retry. The caller may retry
only a read, revalidating everything within its already existing finite interval.
No Job restart, new attempt, reservation, completion or research permission follows.

If the named path exists again, including any replacement/relink, retain strict
JobStoreError/exit3 even if it appears regular or shares an identity. Nonregular
first fstat, nlink>1, symlink/FIFO/directory, other IO/permission errors, mandatory
Catalog/lock files and all writer paths retain their previous strict handling.
Do not catch a generic JobStoreError or parse its message into a conflict. Do not
allow the zero-link descriptor to pass ordinary alias checks or become a SQLite
input. Do not ignore or delete a journal, perform read-only recovery, reset a store,
relax deadlines or expand the original controller cancellation window.

## Remote red/green acceptance

All project code/tests/imports/lint/builds run remotely. Add deterministic real
SQLite transaction tests that open an actual regular nlink1 journal descriptor,
perform a real COMMIT/unlink before returning it to product fstat, observe that
same descriptor as regular/nlink0 and named ENOENT, and let real OS calls run.
No mocked fstat result, sleeps, generic-message match or blind workflow retry
substitutes for this controlled boundary.

First run those new expected-conflict tests against the unchanged implementation
and retain the actual strict-error regression failure and JUnit/logs. Then apply
the frozen tiny fix and require those same tests to pass on the corrected source.
The failing baseline and succeeding fix are distinct pinned revisions, not a
relabelled result. Existing open/restat cases must continue to pass.

Cover get/events/result: conflict9, exact real cause, no SQLite connect/yield,
closed FD, no observer mutation relative to the real writer's postcommit tree,
and later explicit successful reads of unchanged Job/history. Retain write3,
mandatory Catalog/lock3, current-path-present/replacement3, unsafe aliases/types3,
and EACCES/EIO3. Include a zero-link nonregular observation without treating it as
absence. Persistent unsafe paths and replacements are preserved, never repaired.

Run the existing cancellation-controller matrix and SIGKILL/recovery regressions
within their original windows. Capture new-source focused JUnit, full required
Engineering terminal outcomes, source/CI checkout/tree and installed consumers.
Do not weaken or skip the original failing test, add retry-until-green, broaden
exception catches or accept pytest text when its enclosing job failed.

The isolated defect may change the internal Job adapter, lifecycle documentation
and tests as a separately recorded companion; F02's own CLI change does not expand
infra APIs, domains, SDK exports or execution authority. Keep the two scopes and
all earlier real failure/supersession evidence visible in the final PR description.
M1DISABLED, M2unsupported, human securityNOT_PERFORMED/reviewerUNASSIGNED,
external-human0/0/PENDING/#24OPEN remain. Original5/8/11,golden,PR94,actual24+21=45
and600/10/2 windows are unchanged. No AWS/new qualification/original-host export/
oldACK, protocol reset/refund, committed-result rerun, outreach, listener or release.
