# ADR0039: Qualify bounded DatasetStore failures and explicit recovery

Date2026-11-12 Asia/Singapore. Status: frozen before S11-03 implementation. Owner107 accepted S11-02 at06:27:24Z, true mergefd440659790a52b153daad3237f516d90ba9dd26. Originalstory33=10h/S11total33h unchanged; externalhumans0/PENDING.

Keep fault exercises in operational qualification, not a new research aggregate, public repair API or retry framework. Freeze eight cases and bounded child/time budgets in [Dataset fault budget v1](../contracts/dataset-fault-budget-v1.md). Separate actual non-root kernel permission denial and another process's root-inode lock from injected ENOSPC/short-write/unlink/fsync faults. Product failure and successful observation of that failure are different outcomes.

A publication currently revalidates content before Catalog visibility, but ignoring a short stream.write return can install a bad immutable CAS that ordinary retry cannot heal. Refuse an incomplete count BEFORE link using existing DatasetStoreError/OSError(EIO), without silent retry or schema change. Verify pending cleanup, no new publication and unchanged baseline, then explicit normal retry. Corrupt/missing published evidence remains failed in the original store; verified-source reimport into a new owned store is an explicit operator recovery, preserving history.

Promote partial unlink and uncertain fsync from narrow unit evidence into installed fault exercises with exact original-plan repeats and per-call logical credit. Keep metadata-only GC's protected payloads stat-only, preserve all manifest closures and original budgets. Reuse four installed controls jobs with separate new fault artifacts; retain original reports,17checks and timeouts. Owner acceptance and external-human gates stay independent.
