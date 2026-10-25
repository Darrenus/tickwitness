"""Narrow JSON IPC worker. No paths, pickle, plugins or user source are accepted."""

import json
import sys
from typing import Never

from tickwitness.domain.replay.contracts import ReplayInput
from tickwitness.domain.replay.preflight import preflight_replay
from tickwitness.domain.replay.specs import ReplayValidationError, load_replay_spec
from tickwitness.infrastructure.subprocess_replay import MAX_REQUEST_BYTES, MAX_RESULT_BYTES


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReplayValidationError("Duplicate worker field")
        result[key] = value
    return result


def _reject(_value: str) -> Never:
    raise ReplayValidationError("Unsupported worker JSON number")


def _request(raw: bytes) -> ReplayInput:
    if not raw or len(raw) > MAX_REQUEST_BYTES:
        raise ReplayValidationError("Worker request exceeds its byte bound")
    try:
        value: object = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_unique,
            parse_float=_reject,
            parse_constant=_reject,
        )
    except (ValueError, UnicodeError, RecursionError) as error:
        raise ReplayValidationError("Worker request is invalid JSON") from error
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "dataset_id",
        "normalized",
        "spec",
    }:
        raise ReplayValidationError("Worker request has missing or unknown fields")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ReplayValidationError("Unsupported worker schema")
    if not all(isinstance(value[key], str) for key in ("dataset_id", "normalized", "spec")):
        raise ReplayValidationError("Worker artifacts must be strings")
    try:
        spec = load_replay_spec(value["spec"].encode("utf-8"))
        result = ReplayInput(value["dataset_id"], value["normalized"].encode("utf-8"), spec)
    except UnicodeError as error:
        raise ReplayValidationError("Worker artifacts must be UTF-8") from error
    preflight_replay(result)
    return result


def main() -> int:
    try:
        import resource

        # Stdout/stderr are private regular files supervised by the parent.
        resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_RESULT_BYTES, MAX_RESULT_BYTES))
        replay_input = _request(sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1))
        # Optional native dependency is reached only after complete preflight.
        from tickwitness.infrastructure.nautilus_replay import (
            NautilusReplayAdapter,
            ReplayDependencyError,
            ReplayEngineError,
        )

        try:
            result = NautilusReplayAdapter().run(replay_input)
        except ReplayDependencyError as error:
            return _error("engine_unavailable", str(error), 6)
        except ReplayEngineError as error:
            return _error("engine_failure", str(error), 7)
        sys.stdout.buffer.write(result.canonical_bytes)
        return 0
    except ReplayValidationError as error:
        return _error("invalid_replay", str(error), 2)
    except Exception as error:
        return _error("engine_failure", f"Replay worker failed: {type(error).__name__}", 7)


def _error(code: str, message: str, exit_code: int) -> int:
    print(json.dumps({"error": {"code": code, "message": message[:2048]}}), file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
