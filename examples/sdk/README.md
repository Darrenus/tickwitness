# Python SDK development consumer

`development_consumer.py` is a real downstream program using only the public
`tickwitness.sdk` contract and Python's standard library. With an installed core
wheel and new owned output roots, run it from an independent directory:

```sh
/path/to/venv/bin/python -I /absolute/path/development_consumer.py \
  --input-root /absolute/path/to/copied-sdk-example \
  --store /absolute/path/to/new-owned-store \
  --registry /absolute/path/to/new-owned-registry
```

The copied SDK example directory must contain `development.jsonl`,
`confirmation.jsonl`, `request.json` and `strategy.py`. Keep output roots outside
the source/example tree. Package Python support is 3.12–3.14 on the existing
supported local POSIX environment; the native extra is unnecessary.

The program imports data, freezes a declaration and produces a bounded
development capture summary. Its first observation deliberately has an unknown
receive timestamp, which stays unknown. The source strategy deliberately raises
if executed: freezing parses and hashes it but never executes it. The final
duplicate import is an explicit ordinary idempotent operation, not a hidden
research retry or a garbage-collection operation.

Receipts and observations describe data/declaration integrity. They do not
evaluate the declared claim, certify replay or measure profitability. Repeated
execution reports existing data/protocols with `created=false`; the installed
qualification compares first and repeated SDK/CLI operations on separate fresh
roots. New research/native executions are zero and the declaration's original
`max_events=2` remains enforced. Confirmation reads are refused before store IO.

`typing_valid.py` and `typing_invalid.py` are static-only type fixtures, never
runtime examples. The latter intentionally has exactly three expected mypy
errors, marked by line and error code. Remote CI checks these against the actual
installed typed wheel rather than an editable checkout.

This automated consumer qualification is not an external-human attempt or
activation. External real-user reproduction and subsequent reuse remain PENDING.
