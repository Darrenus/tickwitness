# Python SDK development consumer

`development_consumer.py` is a real downstream program using only the public
`tickwitness.sdk` contract and Python's standard library. With an installed core
wheel and new owned output roots, run it from an independent directory:

<!-- sdk-consumer-invocation:v1 -->
```sh
/path/to/venv/bin/python -I /absolute/path/development_consumer.py \
  --input-root /absolute/path/to/copied-sdk-example \
  --store /absolute/path/to/new-owned-store \
  --registry /absolute/path/to/new-owned-registry
```
<!-- /sdk-consumer-invocation:v1 -->

This is the single named invocation template. The installed qualification reads
these exact README/template bytes, checks the interpreter placeholder and
substitutes only the declared absolute consumer/input/output paths. It binds
the logical arguments to the actual guarded consumer call. Its outer
invocation uses `-I -B -c` and `runpy`; the placeholder
shell text is not claimed to run verbatim. Real argv, source hashes, output and
exit status belong to the candidate's qualification records.

The copied SDK example directory must contain `development.jsonl`,
`confirmation.jsonl`, `request.json` and `strategy.py`. Keep output roots outside
the source/example tree. Use a hash-verified core wheel and matching sdist; a
wheel does not install these examples. Package Python support is 3.12–3.14;
source regression runs on Ubuntu 24.04/macOS 15 across those versions. The four
installed-consumer/strict-type profiles are currently **all Python 3.12**,
using independent core wheels on Ubuntu 24.04 or macOS 26; source-wheel uses
the actual sdist driver, guide and consumer. See the [versioned matrix](../../docs/support.md#按任务划分的环境矩阵).
The native extra is unnecessary and no additional platform follows from the
wheel tag. Maintainer project execution stays on remote GitHub Actions CPU.

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

The [SDK guide](../../docs/python-sdk.md#在调用方使用) also contains one named
`import_and_inspect` recipe executed against the installed wheel. Its returned
receipt is from inspection, so `created=false` does not describe whether the
preceding import inserted data. `SDKError` propagates; neither recipe adds an
automatic retry, execution bridge, confirmation exposure or budget reset.

Closed event/declaration schemas reject unknown fields, while the declaration's
bounded scalar `parameters` map deliberately preserves valid custom keys.
Unknown receive time stays `None`. Stored-report inspection preserves its
hash-bound JSON; research binding independently normalizes and compares the
complete report. Details and supported recovery are in the [SDK guide](../../docs/python-sdk.md#未知字段参数与存储检查).
No recipe repairs evidence by discarding fields, deleting roots or refunding
the original ledger.

This automated consumer qualification is not an external-human attempt or
activation. External real-user reproduction and subsequent reuse remain PENDING.
The documentation/compatibility qualification requires complete evidence from
the current candidate; this description does not itself record a passing run.
