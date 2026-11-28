# ADR0056: Diagnose a missing leaf in the fixed tagged-pair profile

Date:2026-11-28. Status: accepted design for S14-03/F04/#42; implementation,
own remote acceptance and owner acceptance remain pending.

## Context

The existing tagged-pair reader and real deletion regression collapse missing
manifest/container and missing declared CAS leaf into generic BundleError.
Existing offline CLI/installed consumers have a twelve-role manifest but cannot
identify the missing role(s)/SHA. Baseline already has narrower typed diagnostics,
while finding and search are separate profiles with different boundaries.

## Decision

Freeze and actually push/read back the [contract](../contracts/tagged-pair-missing-object-diagnostics-v1.md)
before implementation. Add a tagged-specific BundleError subtype from validated
twelve-role manifest facts. Reuse only a small private completed-scan fact helper
and existing safe read primitive. Keep baseline error wording/behavior, generic
tree checks and search code unchanged. Only real stat/open ENOENT for a declared
leaf qualifies; post-open and structural/other IO failures stay generic.

Project reason/role/aliases/SHA only for verify-tagged-queue-pair, retaining its
old code3. Other callers, notably issue-tagged-findings reading a twelve-role
source, retain generic {code,message}; their diagnostic text may reflect the new
precise reader fact. Keep fourteen-role finding, wrong-profile refusals, successful
receipts, app semantics, SDK and stored formats unchanged. A missing leaf never
issues a finding, repairs data or grants research execution/retry authority.

Use real IO/races and semantic golden payloads remotely. One bounded installed
matrix reuses an existing standard-gt relocated bundle after the profile loop;
do not multiply it by each2/4 profile or rerun native/research to manufacture
diagnostic state. Pre-import guards and unified child/inventory evidence support
actual current-source acceptance, with the complete original17-job gate.

## Consequences and alternatives

Reusing the baseline exception would incorrectly say baseline and risk global
CLI projection on an indirect caller. Copying the scanner duplicates a subtle
structural-priority rule; a single private file-fact helper preserves both wrappers.
A global error/profile framework or SDK extension lacks need and exceeds scope.
The diagnostic is one observed defect; absent context never certifies valid,
complete, authenticated or retryable input. M1/human gates stay closed/pending.

Forecast8h from parent03's original8h is20accepted+8selected+4uncommitted of32h;
not actual hours or new research budget. Parent01 remainder and optional transport
are not parallel work. All prior CLOSED failures and unknown fields remain.
