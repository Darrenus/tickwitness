# Security policy

TickWitness `v0.1.0a1` is a published GitHub technical preview; no PyPI package was published. It supports the bounded trusted-owner evidence workflow described in the [release record](docs/releases/0.1.0a1.md) and [support matrix](docs/support.md). The subsequent `0.2.0.dev0` branch is unreleased development, including read-only scenario-contract checks which do not approve execution. Preview availability does not provide production or hosted-service support.

The supported trust model is a trusted local owner using authorized data and the built-in strategy profile. Input and evidence IO reject unsafe paths, symlinks, special files and quota breaches within the documented boundary. Root ancestors and the host owner remain trusted configuration. The subprocess worker provides crash and timeout supervision; it is not a sandbox for malicious strategy code, credentials, network access or a hostile owner. Confirmation denial applies to application entry points and does not hide owner-controlled files from their owner.

Offline verification checks integrity, source bindings and the declared accounting profile. It does not authenticate an author, prove a native matching run occurred, certify real market fills, inspect confirmation observations or audit every historical trial. Arbitrary Python strategies, confirmation unsealing and hosted untrusted execution are unsupported. Planned controls must not be described as implemented protections.

Do not submit secrets, private market data, proprietary strategies, or exploit details in public issues. GitHub private vulnerability reporting was enabled and verified for this repository on 2026-10-25. Use the repository Security tab to report privately. If that channel is later unavailable, open a minimal issue asking the maintainer to establish a private channel, without technical exploit details or sensitive attachments.

Preview reports are handled by the maintainer on a best-effort basis. There is no 24×7 response SLA, guaranteed response/fix deadline or announced long-term maintenance window. Acknowledge and coordinate a private disclosure before sharing sensitive details publicly; keep reproducible reports limited to the affected version, environment, error and an authorized minimal synthetic case when possible.

The preview does not promise automatic migrations. Preserve original CAS objects, catalogs, protocols, attempt ledgers and bundles before upgrading; test new versions in separate environments. Unsupported formats must be rejected without overwriting originals. For rollback, retain the previous installation artifacts and a matching complete backup. See the [upgrade and rollback policy](docs/support.md#兼容升级与回退).

See the proposed [security and operations plan](docs/operations/security-and-operations.md) for trust boundaries and release gates.
