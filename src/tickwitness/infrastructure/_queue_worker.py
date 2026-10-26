"""Strict JSON-only queue worker; optional native imports follow full input validation."""

import json
import sys

from tickwitness.domain.replay._validation import ReplayValidationError, exact, integer, parse
from tickwitness.domain.replay.queue_contracts import QueueReplayInput
from tickwitness.domain.research_contracts.queue_family import load_queue_family_protocol
from tickwitness.infrastructure.subprocess_replay import MAX_REQUEST_BYTES, MAX_RESULT_BYTES


def _request(raw: bytes) -> QueueReplayInput:
    value = exact(
        parse(raw, MAX_REQUEST_BYTES),
        {"kind", "schema_version", "family", "normalized", "policy_id"},
        "queue worker request",
    )
    if value["kind"] != "queue_replay_worker_request_v1":
        raise ReplayValidationError("Unsupported queue worker request kind")
    integer(value["schema_version"], "schema_version", 1, 1)
    if not all(isinstance(value[key], str) for key in ("family", "normalized", "policy_id")):
        raise ReplayValidationError("Queue worker artifacts must be strings")
    family, normalized, policy = value["family"], value["normalized"], value["policy_id"]
    assert isinstance(family, str) and isinstance(normalized, str) and isinstance(policy, str)
    try:
        return QueueReplayInput(
            load_queue_family_protocol(family.encode("utf-8")), normalized.encode("utf-8"), policy
        )
    except UnicodeError as error:
        raise ReplayValidationError("Queue worker artifacts must use valid UTF-8") from error


def _error(code: str, message: str, exit_code: int) -> int:
    print(json.dumps({"error": {"code": code, "message": message[:2048]}}), file=sys.stderr)
    return exit_code


def main() -> int:
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_RESULT_BYTES, MAX_RESULT_BYTES))
        replay_input = _request(sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1))
        from tickwitness.infrastructure.nautilus_replay import (
            ReplayDependencyError,
            ReplayEngineError,
        )
        from tickwitness.infrastructure.queue_replay import NautilusQueueReplayAdapter

        try:
            result = NautilusQueueReplayAdapter().run(replay_input)
        except ReplayDependencyError as error:
            return _error("engine_unavailable", str(error), 6)
        except ReplayEngineError as error:
            return _error("engine_failure", str(error), 7)
        sys.stdout.buffer.write(result.canonical_bytes)
        return 0
    except ReplayValidationError as error:
        return _error("invalid_replay", str(error), 2)
    except Exception as error:
        return _error("engine_failure", f"Queue worker failed: {type(error).__name__}", 7)


if __name__ == "__main__":
    raise SystemExit(main())
