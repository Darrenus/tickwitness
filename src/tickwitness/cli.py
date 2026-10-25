"""Command-line adapter for implemented application use cases."""

import argparse
import json
import re
import sys
from dataclasses import asdict
from importlib.metadata import version
from pathlib import Path

from tickwitness.application.datasets import import_events, inspect_dataset
from tickwitness.application.experiments import ProtocolRunError
from tickwitness.application.replay import compare_replays, replay_dataset
from tickwitness.application.research import (
    ConfirmationAccessDenied,
    freeze_protocol,
    inspect_protocol,
    read_protocol_data,
)
from tickwitness.cli_experiments import COMMANDS as EXPERIMENT_COMMANDS
from tickwitness.cli_experiments import add_commands as add_experiment_commands
from tickwitness.cli_experiments import execute as execute_experiment_command
from tickwitness.domain.data_evidence.events import DataValidationError, ValidationLimits
from tickwitness.domain.evidence.evaluation import EvaluationValidationError
from tickwitness.domain.evidence.run_records import EvidenceValidationError
from tickwitness.domain.replay.specs import ReplayValidationError
from tickwitness.domain.research_contracts.protocols import ProtocolValidationError
from tickwitness.infrastructure.attempt_ledger import (
    AttemptBudgetExceededError,
    AttemptLedgerError,
    AttemptNotFoundError,
)
from tickwitness.infrastructure.evidence_bundles import (
    BundleDestinationExistsError,
    BundleDurabilityError,
    BundleError,
    BundleNotFoundError,
)
from tickwitness.infrastructure.executable_registry import (
    ExecutableProtocolNotFoundError,
    ExecutableRegistryError,
)
from tickwitness.infrastructure.local_dataset_store import (
    DatasetNotFoundError,
    DatasetStoreError,
    LocalDatasetStore,
)
from tickwitness.infrastructure.local_protocol_registry import (
    LocalProtocolRegistry,
    ProtocolNotFoundError,
    ProtocolRegistryError,
)
from tickwitness.infrastructure.safe_input import InputReadError, read_jsonl, read_regular_file
from tickwitness.infrastructure.subprocess_replay import ReplayProcessError, SubprocessReplayAdapter


def _positive_integer(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("Limit must be a positive integer")
    return number


def _dataset_identity(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise argparse.ArgumentTypeError("dataset_id must be a lowercase SHA-256 digest")
    return value


def _protocol_identity(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise argparse.ArgumentTypeError("protocol_id must be a lowercase SHA-256 digest")
    return value


def _write_error(code: str, error: Exception, exit_code: int) -> int:
    print(json.dumps({"error": {"code": code, "message": str(error)}}), file=sys.stderr)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    """Import, freeze, execute a scoped baseline and verify portable accounting evidence."""
    parser = argparse.ArgumentParser(
        prog="tickwitness",
        description=(
            "TickWitness scoped protocol execution and portable accounting evidence. "
            "Arbitrary strategy execution and search verdicts remain unsupported."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('tickwitness')}")
    commands = parser.add_subparsers(dest="command")
    importer = commands.add_parser(
        "import-events", help="Validate and seal normalized JSONL events"
    )
    importer.add_argument("input", help="Relative .jsonl path under --input-root")
    importer.add_argument("--input-root", required=True, type=Path)
    importer.add_argument("--store", required=True, type=Path)
    importer.add_argument("--id-only", action="store_true", help="Print only the sealed dataset ID")
    importer.add_argument("--max-bytes", type=_positive_integer, default=8 * 1024 * 1024)
    importer.add_argument("--max-records", type=_positive_integer, default=100_000)
    inspector = commands.add_parser("inspect-dataset", help="Verify and inspect a sealed dataset")
    inspector.add_argument("dataset_id", type=_dataset_identity)
    inspector.add_argument("--store", required=True, type=Path)
    freezer = commands.add_parser(
        "freeze-protocol", help="Seal a declaration and verified bindings"
    )
    freezer.add_argument("input", help="Relative request .json path under --input-root")
    freezer.add_argument("--input-root", required=True, type=Path)
    freezer.add_argument("--strategy-source", required=True, help="Relative Python source .py path")
    freezer.add_argument("--development-dataset", required=True, type=_dataset_identity)
    freezer.add_argument("--confirmation-dataset", required=True, type=_dataset_identity)
    freezer.add_argument("--store", required=True, type=Path)
    freezer.add_argument("--registry", required=True, type=Path)
    freezer.add_argument("--id-only", action="store_true")
    protocol_inspector = commands.add_parser(
        "inspect-protocol", help="Verify a frozen declaration, source and data references"
    )
    protocol_reader = commands.add_parser(
        "read-protocol-data", help="Read only the development split bound to a frozen protocol"
    )
    for command in (protocol_inspector, protocol_reader):
        command.add_argument("protocol_id", type=_protocol_identity)
        command.add_argument("--store", required=True, type=Path)
        command.add_argument("--registry", required=True, type=Path)
    protocol_reader.add_argument(
        "--split", choices=("development", "confirmation"), default="development"
    )
    protocol_reader.add_argument("--limit", type=_positive_integer, default=100)
    replay = commands.add_parser(
        "replay-dataset", help="Qualify sealed data with a bounded built-in L2 strategy"
    )
    replay.add_argument("dataset_id", type=_dataset_identity)
    replay.add_argument("input", help="Relative replay spec .json path under --input-root")
    replay.add_argument("--input-root", required=True, type=Path)
    replay.add_argument("--store", required=True, type=Path)
    replay.add_argument("--timeout-seconds", type=_positive_integer, default=60)
    replay.add_argument(
        "--engine-python",
        type=Path,
        help="Trusted Python environment with TickWitness and its nautilus extra installed",
    )
    comparison = commands.add_parser(
        "compare-replays", help="Compare validated replay conditions and traces"
    )
    comparison.add_argument("left", help="Relative left result .json path")
    comparison.add_argument("right", help="Relative right result .json path")
    comparison.add_argument("--input-root", required=True, type=Path)
    add_experiment_commands(commands)
    arguments = parser.parse_args(argv)
    if arguments.command is None:
        parser.print_help()
        return 0

    try:
        if arguments.command in EXPERIMENT_COMMANDS:
            output, identity = execute_experiment_command(arguments)
        elif arguments.command == "import-events":
            limits = ValidationLimits(
                max_bytes=arguments.max_bytes, max_records=arguments.max_records
            )
            raw = read_jsonl(arguments.input_root, arguments.input, max_bytes=limits.max_bytes)
            imported = import_events(raw, lambda: LocalDatasetStore(arguments.store), limits=limits)
            output = asdict(imported)
            identity = imported.dataset_id
        elif arguments.command == "inspect-dataset":
            inspected = inspect_dataset(
                arguments.dataset_id, LocalDatasetStore(arguments.store, create=False)
            )
            output = asdict(inspected)
            identity = inspected.dataset_id
        elif arguments.command == "freeze-protocol":
            request = read_regular_file(
                arguments.input_root,
                arguments.input,
                max_bytes=64 * 1024,
                allowed_suffixes=frozenset({".json"}),
            )
            source = read_regular_file(
                arguments.input_root,
                arguments.strategy_source,
                max_bytes=256 * 1024,
                allowed_suffixes=frozenset({".py"}),
            )
            frozen = freeze_protocol(
                request,
                development_dataset_id=arguments.development_dataset,
                confirmation_dataset_id=arguments.confirmation_dataset,
                strategy_source=source,
                datasets=LocalDatasetStore(arguments.store, create=False),
                registry_factory=lambda: LocalProtocolRegistry(arguments.registry),
            )
            output = asdict(frozen)
            identity = frozen.protocol_id
        elif arguments.command == "inspect-protocol":
            protocol = inspect_protocol(
                arguments.protocol_id,
                LocalProtocolRegistry(arguments.registry, create=False),
                LocalDatasetStore(arguments.store, create=False),
            )
            output = asdict(protocol)
            identity = protocol.protocol_id
        elif arguments.command == "read-protocol-data":
            observations = read_protocol_data(
                arguments.protocol_id,
                split=arguments.split,
                limit=arguments.limit,
                registry_factory=lambda: LocalProtocolRegistry(arguments.registry, create=False),
                datasets_factory=lambda: LocalDatasetStore(arguments.store, create=False),
            )
            output = asdict(observations)
            identity = observations.protocol_id
        elif arguments.command == "replay-dataset":
            request = read_regular_file(
                arguments.input_root,
                arguments.input,
                max_bytes=64 * 1024,
                allowed_suffixes=frozenset({".json"}),
            )
            # Validate supervisor configuration before opening a dataset.
            supervisor = SubprocessReplayAdapter(
                timeout_seconds=arguments.timeout_seconds, python_executable=arguments.engine_python
            )
            replayed = replay_dataset(
                arguments.dataset_id,
                request,
                datasets_factory=lambda: LocalDatasetStore(arguments.store, create=False),
                engine_factory=lambda: supervisor,
            )
            output = replayed.document
            identity = arguments.dataset_id
        else:
            result_files = [
                read_regular_file(
                    arguments.input_root,
                    name,
                    max_bytes=16 * 1024 * 1024 + 1,
                    allowed_suffixes=frozenset({".json"}),
                )
                for name in (arguments.left, arguments.right)
            ]
            output = compare_replays(*result_files).document
            identity = ""
    except ConfirmationAccessDenied as error:
        return _write_error("confirmation_access_denied", error, 5)
    except InputReadError as error:
        return _write_error("unsafe_input", error, 2)
    except DataValidationError as error:
        return _write_error("invalid_data", error, 2)
    except ProtocolValidationError as error:
        return _write_error("invalid_protocol", error, 2)
    except ReplayValidationError as error:
        return _write_error("invalid_replay", error, 2)
    except ReplayProcessError as error:
        return _write_error(error.code, error, error.exit_code)
    except ProtocolRunError as error:
        print(
            json.dumps(
                {
                    "error": {
                        "code": error.code,
                        "message": str(error),
                        "attempt_id": error.attempt_id,
                        "budget_consumed": True,
                    }
                }
            ),
            file=sys.stderr,
        )
        return error.exit_code
    except (EvaluationValidationError, EvidenceValidationError) as error:
        return _write_error("invalid_research_evidence", error, 2)
    except AttemptBudgetExceededError as error:
        return _write_error("attempt_budget_exhausted", error, 8)
    except (AttemptNotFoundError, ExecutableProtocolNotFoundError, BundleNotFoundError) as error:
        return _write_error("research_evidence_not_found", error, 4)
    except BundleDestinationExistsError as error:
        return _write_error("bundle_destination_exists", error, 3)
    except BundleDurabilityError as error:
        return _write_error("bundle_durability_unconfirmed", error, 3)
    except (AttemptLedgerError, ExecutableRegistryError, BundleError) as error:
        return _write_error("research_store_integrity_or_io_failure", error, 3)
    except DatasetNotFoundError as error:
        return _write_error("dataset_not_found", error, 4)
    except DatasetStoreError as error:
        return _write_error("store_integrity_or_publication_failure", error, 3)
    except ProtocolNotFoundError as error:
        return _write_error("protocol_not_found", error, 4)
    except ProtocolRegistryError as error:
        return _write_error("protocol_integrity_or_publication_failure", error, 3)
    except OSError as error:
        return _write_error("io_failure", error, 3)

    if getattr(arguments, "id_only", False):
        print(identity)
        return 0
    print(
        json.dumps(
            output, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
    )
    return 0
