# ADR0038: Reclaim only proven DatasetStore CAS orphans

Date2026-11-12 Asia/Singapore. Status: frozen before S11-02 implementation; owner107 accepted this slice at06:27:24Z, true mergefd440659790a52b153daad3237f516d90ba9dd26. The earlier preacceptance qualification archive remains unchanged.

Dataset publication installs CAS and manifest before Catalog commit. Dataset and research-ledger roots also use the same CAS path shape. A Catalog-only scan or an age-based recursive delete can destroy in-flight or unrelated evidence. Restrict v1 to an exclusive DatasetStore root, retain all valid physical manifests including unindexed ones, and refuse unknown/mixed namespaces.

Coordinate all new DatasetStore readers/publishers with a shared root-inode gate; maintenance uses the same exclusive nonblocking gate and a closed immutable read snapshot only after rejecting sidecars. No new lockfile or cleanup authority is added to research ledgers/Jobs. Read manifest references and file metadata, not retained research payloads. Hash only orphan candidates within explicit limits.

Freeze exact graph, inventory, identities and policy before apply. Revalidate all facts before unlink, permit missing original candidates only as honest already-absent observations, and report partial/unconfirmed IO explicitly. Never refund or reset research budget. The [retention contract](../contracts/dataset-retention-v1.md) specifies complete formats and remote qualification. Original12h/S11total33h and external-human0/PENDING remain unchanged.
