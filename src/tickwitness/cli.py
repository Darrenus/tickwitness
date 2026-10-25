"""Command-line adapter for implemented application use cases."""

import argparse
import json
import re
import sys
from importlib.metadata import version
from pathlib import Path

from tickwitness.application.datasets import import_events, inspect_dataset
from tickwitness.domain.data_evidence.events import DataValidationError, ValidationLimits
from tickwitness.infrastructure.local_dataset_store import (
    DatasetNotFoundError,
    DatasetStoreError,
    LocalDatasetStore,
)
from tickwitness.infrastructure.safe_input import InputReadError, read_jsonl


def _positive_integer(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("Limit must be a positive integer")
    return number


def _dataset_identity(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise argparse.ArgumentTypeError("dataset_id must be a lowercase SHA-256 digest")
    return value


def _write_error(code: str, error: Exception, exit_code: int) -> int:
    print(json.dumps({"error": {"code": code, "message": str(error)}}), file=sys.stderr)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    """Import or inspect evidence; replay and search remain future use cases."""
    parser = argparse.ArgumentParser(
        prog="tickwitness",
        description=(
            "TickWitness data-evidence foundation. "
            "Replay, search, and research verdicts are not implemented yet."
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
    arguments = parser.parse_args(argv)
    if arguments.command is None:
        parser.print_help()
        return 0

    try:
        if arguments.command == "import-events":
            limits = ValidationLimits(
                max_bytes=arguments.max_bytes, max_records=arguments.max_records
            )
            raw = read_jsonl(arguments.input_root, arguments.input, max_bytes=limits.max_bytes)
            result = import_events(raw, lambda: LocalDatasetStore(arguments.store), limits=limits)
        else:
            result = inspect_dataset(
                arguments.dataset_id, LocalDatasetStore(arguments.store, create=False)
            )
    except InputReadError as error:
        return _write_error("unsafe_input", error, 2)
    except DataValidationError as error:
        return _write_error("invalid_data", error, 2)
    except DatasetNotFoundError as error:
        return _write_error("dataset_not_found", error, 4)
    except DatasetStoreError as error:
        return _write_error("store_integrity_or_publication_failure", error, 3)
    except OSError as error:
        return _write_error("io_failure", error, 3)

    if arguments.command == "import-events" and arguments.id_only:
        print(result.dataset_id)
        return 0
    print(
        json.dumps(
            {
                "dataset_id": result.dataset_id,
                "created": result.created,
                "manifest": result.manifest,
                "report": result.report,
            },
            sort_keys=True,
            allow_nan=False,
        )
    )
    return 0
