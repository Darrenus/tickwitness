# ADR 0033: Recover committed reduction facts before authorizing retries

Date: 2026-11-06 (Asia/Singapore). Status: implementation under review, S10-02a.

## Context

S10-01's first Job worker is deliberately read-only. Existing synchronous reduction execution owns reservation, intent binding, native execution and publication together. Moving that whole function into a Job worker would grant a stale worker authority to write the research ledger. In addition, SQLite Job completion and file-ledger outcome publication do not form a shared atomic transaction.

An uncertain producer response can occur after an immutable outcome was already committed. The first recovery step must establish what the original attempt actually contains before deciding whether a fresh execution is needed. A successful process exit or an absent Job acknowledgment cannot settle that question.

## Decision

Split S10-02 into independently reviewable slices, retaining the original 14h story estimate and keeping the story open. This slice adds a strictly read-only `inspect-reduction-attempt` operation. It uses the original live reservation, frozen source/preparation pins and existing independent receipt verification to distinguish unbound, unfinished, committed failure and committed result observations.

The existing `reduction_run_receipt_v1` is the final research manifest. Recovery returns its exact verified document; it does not publish another terminal, rewrite a Job, refund a slot or execute an engine. No intent or outcome observed is explicitly a point-in-read observation, not global absence. An unbound reservation cannot certify the requested preparation belongs to it.

Current adapters do not export complete checkpoints. Recovery advertises only `frozen_origin_new_attempt_only_v1`, with execution authorization and checkpoint support both false. A later real rerun must consume a new original protocol slot. Previously consumed incomplete attempts remain consumed.

## Consequences and remaining work

Operators can recover an already committed final manifest after acknowledgment loss without another native invocation. Malformed or conflicting evidence fails closed. The API works in the installed core runtime and creates no ledger or Catalog.

Managed native execution, persistent dispatch/nonce correlation, explicit idempotent retry, stale-owner fencing of research publication and recovery of the Job acknowledgment remain later S10-02 work. A native worker must return a result without ledger write authority; the current coordinator must verify its lease and independently build/publish the original outcome. Existing per-attempt native wall limits remain mandatory. Strong cancellation and complete orphan/resource policy remain S10-03.

This slice does not qualify crash durability, prove global history authenticity or implement a transaction across both stores. CI and AI review remain automation; owner acceptance and external human reproduction are separate gates.
