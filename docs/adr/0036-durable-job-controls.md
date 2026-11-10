# ADR0036: Separate durable control intent from Job and research outcomes

Date: 2026-11-10 (Asia/Singapore). Status: frozen before S10-03 implementation; owner acceptance pending.

An interrupted local Job needs explicit cancellation, a nonrenewable admission deadline, worker resource ceilings and reclaimable scratch. Existing schema1 has immutable one-attempt terminal rules and research slots that cannot be refunded. Adding cancellation to a heartbeat or overwriting a committed result would confuse intent, execution and research evidence.

Freeze an immutable per-Job policy and bounded control journal beside the Catalog. A controller can record intent without acquiring the active coordinator's Catalog or original-family lock. One control gate orders cancellation against short reservation/start admission and the first irreversible success admission. Native research publication and Catalog completion share that admitted section. An admission marker is uncertainty, not a committed receipt; later cancellation is explicitly too late. Scope is this Catalog/attempt, not a global research or cross-Catalog cancel.

Preserve old descriptors, schema and terminal validators. A separate receipt binds actual process/group stop, workspace cleanup and final Catalog facts. Lease-valid stop can become FAILED; expired lease remains LOST. Never fabricate post-stop heartbeats. Configure policies before claim; unsupported OS enforcement refuses before research reservation. Unconfigured Jobs retain historical behavior, and older coordinators must be quiesced before controls are enabled.

Use a fixed live monotonic admission deadline across preparation, execution and verification. Worker default OS termination uses the earlier original or total deadline; heartbeats cannot enlarge either. Kernel/fsync and synchronous verification preclude a universal real-time completion claim. Enforce worker CPU, individual-file size and descriptor limits before project imports; do not call sampled RSS/aggregate scratch hard ceilings.

Temporary ownership uses no-follow seals and inherited lifetime locks. Signal only a current unreaped owned child group, then reap and verify group absence. Retain ambiguous or busy scratch. Explicit reclamation verifies the current Catalog and exact workspace identity without signalling old PIDs or traversing research/input roots.

The [Job controls contract](../contracts/job-controls-v1.md) defines these semantics. Installed qualification must observe both race orders, actual native stop/deadline/resource cases, measured cancellation latency, unchanged original slots and real scratch cleanup in core/Ubuntu/macOS/actual-source-wheel profiles. CI and AI are not external-human acceptance; external humans remain0/PENDING.
