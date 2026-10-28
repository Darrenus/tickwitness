#!/usr/bin/env python3
"""Qualify installed one-shot confirmation access using genuine synthetic records."""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

_SCOPE = {
    "observation_release_only": True,
    "engine_execution_authorized": False,
    "source_claim_evaluated": False,
    "confirmation_finding_issued": False,
    "historical_unseen_certified": False,
    "author_signature_verified": False,
}
_GUARD = """
import importlib.abc
from importlib import metadata
import json
from pathlib import Path
import socket
import subprocess
import sys
try:
    metadata.version('nautilus_trader')
except metadata.PackageNotFoundError:
    pass
else:
    raise AssertionError('Confirmation acceptance requires installed core-only Python')
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('nautilus_trader'):
            raise AssertionError('Confirmation access cannot import native')
sys.meta_path.insert(0, NoNative())
from tickwitness import cli, cli_scenarios, cli_search
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.bounded_replay import BoundedReplayAdapter
from tickwitness.infrastructure.campaign_budget_store import LocalCampaignBudgetStore
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_confirmation import (
    LocalConfirmationRegistry, LocalConfirmationExposureLedger,
)
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.local_protocol_registry import LocalProtocolRegistry
from tickwitness.infrastructure.search_campaign_store import LocalSearchCampaignStore
from tickwitness.infrastructure.search_plan_registry import LocalSearchPlanRegistry
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter
def forbidden(*args, **kwargs):
    raise AssertionError('Confirmation access cannot execute, reserve, spend or use network')
mode, command = sys.argv[1:3]
socket.socket = forbidden
socket.create_connection = forbidden
subprocess.Popen = forbidden
for repository in (LocalAttemptLedger, LocalCampaignBudgetStore, LocalSearchCampaignStore):
    repository.__init__ = forbidden
for name in ('reserve', 'reserve_with_nonce', 'bind_intent', 'publish'):
    setattr(LocalAttemptLedger, name, forbidden)
for name in ('start', 'write_allocation', 'write_stop'):
    setattr(LocalCampaignBudgetStore, name, forbidden)
BoundedReplayAdapter.__init__ = forbidden
SubprocessReplayAdapter.__init__ = forbidden
if command != 'import-events':
    LocalDatasetStore.publish = forbidden
if command != 'freeze-protocol':
    LocalProtocolRegistry.seal = forbidden
if command != 'freeze-experiment':
    LocalExecutableProtocolRegistry.seal = forbidden
if mode == 'no-data':
    for name in ('get', 'read_normalized', 'read_artifacts'):
        setattr(LocalDatasetStore, name, forbidden)
if mode == 'pre-io':
    for repository in (LocalDatasetStore, LocalProtocolRegistry,
                       LocalExecutableProtocolRegistry, LocalConfirmationRegistry,
                       LocalConfirmationExposureLedger, LocalSearchPlanRegistry):
        repository.__init__ = forbidden
    for module in (cli, cli_scenarios, cli_search):
        module.read_regular_file = forbidden
if mode == 'audit-ledger':
    entries = LocalConfirmationExposureLedger(Path(command), create=False).entries()
    print(json.dumps({'exposure_ids': sorted(entry.exposure_id for entry in entries),
                      'exposures': [entry.document for entry in entries]}, sort_keys=True))
else:
    raise SystemExit(cli.main(sys.argv[2:]))
"""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _tree(root: Path, *, exclude_state: bool = False) -> dict[str, str]:
    return {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
        and not (
            exclude_state
            and path.relative_to(root).parts[0]
            in {"confirmation-state", ".confirmation-state-initialized"}
        )
    }


def _snapshot(capture: int, sequence: int, *, price: int = 199) -> dict:
    return {
        "schema_version": 1,
        "type": "snapshot",
        "source": "synthetic",
        "instrument": "TEST-USD",
        "session": "confirmation-installed-v1",
        "capture_seq": capture,
        "event_time_ns": capture * 100,
        "receive_time_ns": capture * 100 + 10,
        "last_sequence": sequence,
        "bids": [[price, 5]],
        "asks": [[price + 2, 5]],
    }


def _delta(capture: int, first: int, last: int, *, price: int = 199) -> dict:
    event = _snapshot(capture, last, price=price)
    event.update(type="delta", first_sequence=first)
    return event


def _trade(capture: int, identity: str, *, price: int = 199) -> dict:
    event = {
        key: value
        for key, value in _snapshot(capture, 0).items()
        if key not in ("last_sequence", "bids", "asks")
    }
    event.update(
        type="trade", trade_id=identity, price_ticks=price, quantity_lots=1, aggressor_side="sell"
    )
    return event


def _request(title: str, *, max_events: int = 1000) -> dict:
    return {
        "schema_version": 1,
        "claim": {
            "title": title,
            "hypothesis": "A declared synthetic hypothesis without an evaluated result.",
            "metric": "net_marked_pnl_v1",
            "comparator": "gt",
            "threshold": "0",
            "unit": "synthetic_quote_units",
        },
        "strategy_name": "must_not_execute",
        "parameters": {"size_lots": 1},
        "configuration": {
            "fee_model_id": "declared_fees_v1",
            "execution_model_id": "declared_execution_v1",
            "clock_policy_id": "capture_order_unbound_v1",
        },
        "budget": {"max_scenarios": 10, "max_wall_seconds": 60, "max_events": max_events},
        "seed": 7,
    }


def _check_protocol(receipt: dict, *, exposed: bool, related: list[str]) -> None:
    assert receipt["kind"] == "confirmation_protocol_receipt_v1"
    assert receipt["schema_version"] == 1
    assert _digest(receipt["document"]) == receipt["protocol_id"]
    assert receipt["document"]["kind"] == "confirmation_protocol_v1"
    assert receipt["scope"] == receipt["document"]["scope"] == _SCOPE
    assert receipt["exposure_status"] == (
        "ALREADY_EXPOSED_IN_LEDGER" if exposed else "NO_MATCHING_EXPOSURE_IN_LEDGER"
    )
    assert receipt["related_exposure_ids"] == sorted(related)
    assert "observations" not in receipt and "evaluation" not in receipt


def _check_release(receipt: dict, protocol: dict, observations: list[dict]) -> None:
    assert receipt["kind"] == "confirmation_observation_release_v1"
    assert receipt["schema_version"] == 1
    assert receipt["protocol_id"] == protocol["protocol_id"]
    assert receipt["dataset_id"] == protocol["document"]["bindings"]["confirmation_dataset_id"]
    assert receipt["observations"] == observations
    assert receipt["total_records"] == len(observations) and receipt["truncated"] is False
    bindings = protocol["document"]["bindings"]
    normalized = b"".join(_canonical(row) + b"\n" for row in observations)
    assert hashlib.sha256(normalized).hexdigest() == bindings["confirmation_normalized_sha256"]
    assert bindings["confirmation_event_count"] == len(observations)
    assert receipt["scope"] == _SCOPE
    exposure = receipt["exposure"]
    assert _digest(exposure) == receipt["exposure_id"]
    assert exposure["kind"] == "confirmation_exposure_v1" and exposure["state"] == "EXPOSED"
    assert exposure["confirmation_protocol_id"] == protocol["protocol_id"]
    assert exposure["policy"] == "irreversible_origin_overlap_before_release_v1"
    assert exposure["origin_footprint"] == protocol["document"]["origin_footprint"]
    for key in (
        "source_protocol_id",
        "confirmation_dataset_id",
        "confirmation_normalized_sha256",
        "origin_footprint_id",
    ):
        assert exposure[key] == protocol["document"]["bindings"][key]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--records-dir", required=True, type=Path)
    arguments = parser.parse_args()
    interpreter = str(arguments.python.absolute())
    examples = Path(__file__).resolve().parents[1] / "examples"
    with TemporaryDirectory(prefix="tickwitness-confirmation-wheel-") as temporary:
        directory = Path(temporary)
        inputs, data, registry = (directory / name for name in ("inputs", "data", "registry"))
        inputs.mkdir()
        strategy = inputs / "strategy.py"
        strategy.write_text("raise AssertionError('confirmation must not execute strategy')\n")
        cases = []

        def run(*command: str, expected: int = 0, mode: str = "normal") -> dict:
            result = subprocess.run(
                [interpreter, "-I", "-c", _GUARD, mode, *command],
                cwd=directory,
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            if result.returncode != expected or (result.stderr if expected == 0 else result.stdout):
                raise RuntimeError(
                    f"Installed confirmation CLI exited {result.returncode}: "
                    f"{result.stdout}\n{result.stderr}"
                )
            return json.loads(result.stdout if expected == 0 else result.stderr)

        def write(name: str, value: dict) -> str:
            filename = name + ".json"
            (inputs / filename).write_bytes(_canonical(value))
            return filename

        def ingest(name: str, records: list[dict], *, repack: bool = False) -> str:
            filename = name + ".jsonl"
            raw = b"".join(
                (json.dumps(row, sort_keys=True).encode() if repack else _canonical(row)) + b"\n"
                for row in records
            )
            (inputs / filename).write_bytes(raw)
            receipt = run(
                "import-events", filename, "--input-root", str(inputs), "--store", str(data)
            )
            assert receipt["report"]["quality_status"] == "accepted"
            return receipt["dataset_id"]

        development = ingest("development", [_snapshot(1, 10), _delta(2, 11, 11)])
        originals = [
            _snapshot(10, 20),
            _delta(11, 21, 24),
            _trade(12, "confirmation-trade"),
        ]
        primary_dataset = ingest("confirmation", originals)

        def source(name: str, dataset: str, *, target: Path = registry, cap: int = 1000) -> str:
            receipt = run(
                "freeze-protocol",
                write("source-" + name, _request(name, max_events=cap)),
                "--input-root",
                str(inputs),
                "--strategy-source",
                "strategy.py",
                "--development-dataset",
                development,
                "--confirmation-dataset",
                dataset,
                "--store",
                str(data),
                "--registry",
                str(target),
            )
            assert receipt["document"]["read_policy"] == "development_only_v1"
            assert receipt["document"]["execution_ready"] is False
            return receipt["protocol_id"]

        subject = source("original", primary_dataset)
        cross_protocol = source("different-claim", primary_dataset)
        alternate_registry = directory / "alternate-registry"
        assert source("original", primary_dataset, target=alternate_registry) == subject
        variants = {
            "raw-repack": originals,
            "book-subset": [_snapshot(30, 23)],
            "book-superset": [_snapshot(40, 19), _delta(41, 20, 26)],
            "book-resegmented": [_snapshot(50, 20), _delta(51, 21, 22), _delta(52, 23, 24)],
            "metadata-and-payload": [
                _snapshot(60, 20, price=299),
                _delta(61, 21, 24, price=299),
                _trade(62, "confirmation-trade", price=299),
            ],
            "trade-id-only": [_snapshot(70, 30), _trade(71, "confirmation-trade", price=399)],
        }
        variant_sources = {}
        for name, records in variants.items():
            dataset = ingest(name, records, repack=name == "raw-repack")
            assert dataset != primary_dataset
            variant_sources[name] = source(name, dataset)
        independent_records = [_snapshot(80, 40), _delta(81, 41, 41)]
        independent_source = source("independent", ingest("independent", independent_records))
        boundary_records = [_snapshot(1000 + index, 1000 + index) for index in range(1000)]
        boundary_source = source("boundary-1000", ingest("boundary-1000", boundary_records))
        too_many = [_snapshot(3000 + index, 3000 + index) for index in range(1001)]
        oversized_source = source("too-many", ingest("too-many", too_many), cap=2000)
        low_budget_source = source("source-cap-two", primary_dataset, cap=2)
        for filename in (
            "replay-partials.jsonl",
            "replay-confirmation.jsonl",
            "experiment-request.json",
        ):
            shutil.copyfile(examples / filename, inputs / filename)
        replay_ids = [
            run("import-events", filename, "--input-root", str(inputs), "--store", str(data))[
                "dataset_id"
            ]
            for filename in ("replay-partials.jsonl", "replay-confirmation.jsonl")
        ]
        executable_registry = directory / "executable-registry"
        executable = run(
            "freeze-experiment",
            "experiment-request.json",
            "--input-root",
            str(inputs),
            "--development-dataset",
            replay_ids[0],
            "--confirmation-dataset",
            replay_ids[1],
            "--store",
            str(data),
            "--registry",
            str(executable_registry),
        )
        readonly_before = (
            _tree(data, exclude_state=True),
            _tree(registry),
            _tree(alternate_registry),
            _tree(executable_registry),
        )

        def freeze(
            name: str,
            source_id: str,
            *,
            target: Path = registry,
            cap: int = 1000,
            expected: int = 0,
        ) -> dict:
            return run(
                "freeze-confirmation-protocol",
                source_id,
                write(
                    name,
                    {
                        "kind": "confirmation_request_v1",
                        "schema_version": 1,
                        "title": name,
                        "max_events": cap,
                    },
                ),
                "--input-root",
                str(inputs),
                "--store",
                str(data),
                "--registry",
                str(target),
                expected=expected,
            )

        def opening(
            protocol: dict,
            *,
            target: Path = registry,
            store: Path = data,
            expected: int = 0,
            mode: str = "normal",
        ) -> dict:
            return run(
                "open-confirmation-protocol",
                protocol["protocol_id"],
                "--store",
                str(store),
                "--registry",
                str(target),
                expected=expected,
                mode=mode,
            )

        def inspect(protocol: dict, *, target: Path = registry) -> dict:
            return run(
                "inspect-confirmation-protocol",
                protocol["protocol_id"],
                "--store",
                str(data),
                "--registry",
                str(target),
            )

        primary = freeze("first-full-window", subject)
        _check_protocol(primary, exposed=False, related=[])
        assert primary["document"]["origin_footprint"]["streams"] == [
            {
                "source": "synthetic",
                "instrument": "TEST-USD",
                "session": "confirmation-installed-v1",
                "trade_ids": ["confirmation-trade"],
                "book_intervals": [[20, 24]],
            }
        ]
        assert primary["created"] is True
        repeated = freeze("first-full-window", subject)
        _check_protocol(repeated, exposed=False, related=[])
        assert repeated["created"] is False and repeated["protocol_id"] == primary["protocol_id"]
        _check_protocol(inspect(primary), exposed=False, related=[])
        stale_subset = freeze("subset-frozen-before-open", variant_sources["book-subset"])
        _check_protocol(stale_subset, exposed=False, related=[])
        for name, identity, cap in (
            ("request-cap-two", subject, 2),
            ("source-cap-two", low_budget_source, 1000),
            ("whole-window-1001", oversized_source, 1000),
        ):
            before = _tree(data / "confirmation-state")
            failure = freeze(name, identity, cap=cap, expected=2)
            assert failure["error"]["code"] == "invalid_confirmation_protocol"
            assert before == _tree(data / "confirmation-state")
            cases.append({"name": name, "error": failure, "state_unchanged": True})

        released = opening(primary)
        _check_release(released, primary, originals)
        related = [released["exposure_id"]]
        inspected = inspect(primary)
        _check_protocol(inspected, exposed=True, related=related)
        cases.append(
            {
                "name": "first-full-window",
                "protocol": primary,
                "release": released,
                "after": inspected,
                "full_window_returned": True,
            }
        )

        def denied(name: str, protocol: dict, *, target: Path = registry) -> None:
            before = _tree(data / "confirmation-state")
            refusal = opening(protocol, target=target, expected=5, mode="no-data")
            assert refusal["error"]["code"] == "confirmation_already_exposed"
            assert refusal["error"]["related_exposure_ids"] == related
            assert before == _tree(data / "confirmation-state")
            after = inspect(protocol, target=target)
            _check_protocol(after, exposed=True, related=related)
            cases.append(
                {
                    "name": name,
                    "protocol": protocol,
                    "error": refusal,
                    "after": after,
                    "denied_before_data_read": True,
                    "state_unchanged": True,
                }
            )

        denied("repeat-open", primary)
        denied("subset-frozen-before-open", stale_subset)
        for name, identity, target in (
            ("renamed", subject, registry),
            ("different-source-protocol", cross_protocol, registry),
            ("different-source-registry", subject, alternate_registry),
            *((name, identity, registry) for name, identity in variant_sources.items()),
        ):
            protocol = freeze(name, identity, target=target)
            assert protocol["protocol_id"] != primary["protocol_id"]
            _check_protocol(protocol, exposed=True, related=related)
            denied(name, protocol, target=target)
        repeated_after = freeze("first-full-window", subject)
        _check_protocol(repeated_after, exposed=True, related=related)
        assert repeated_after["created"] is False

        successful = [(primary, released)]
        executable_records = [
            json.loads(line)
            for line in (inputs / "replay-confirmation.jsonl").read_bytes().splitlines()
        ]
        for name, identity, records, target in (
            ("independent-window", independent_source, independent_records, registry),
            ("whole-window-1000", boundary_source, boundary_records, registry),
            (
                "executable-v2-window",
                executable["protocol_id"],
                executable_records,
                executable_registry,
            ),
        ):
            protocol = freeze(name, identity, target=target)
            _check_protocol(protocol, exposed=False, related=[])
            receipt = opening(protocol, target=target)
            _check_release(receipt, protocol, records)
            _check_protocol(
                inspect(protocol, target=target), exposed=True, related=[receipt["exposure_id"]]
            )
            successful.append((protocol, receipt))
            cases.append(
                {
                    "name": name,
                    "protocol": protocol,
                    "release": receipt,
                    "full_window_returned": True,
                }
            )

        before_audit = _tree(data / "confirmation-state")
        audit = run(str(data), mode="audit-ledger")
        assert audit["exposure_ids"] == sorted(receipt["exposure_id"] for _, receipt in successful)
        assert sorted(_digest(exposure) for exposure in audit["exposures"]) == audit["exposure_ids"]
        assert before_audit == _tree(data / "confirmation-state")

        corrupt_cases = []
        for name in ("invalid-log", "missing-log"):
            broken = directory / name
            shutil.copytree(data, broken)
            log = broken / "confirmation-state" / "exposures.json"
            if name == "invalid-log":
                log.write_bytes(b'{"kind":"forged_empty_log"}')
            else:
                log.unlink()
            before = _tree(broken)
            failure = opening(primary, store=broken, expected=3, mode="no-data")
            assert failure["error"]["code"] == "confirmation_store_integrity_or_io_failure"
            assert before == _tree(broken)
            corrupt_cases.append(
                {"name": name, "error": failure, "fail_closed": True, "state_unchanged": True}
            )

        missing = directory / "must-remain-absent"
        pre_io = []
        common = ("--store", str(missing / "data"), "--registry", str(missing / "registry"))
        for command in (
            ("read-protocol-data", subject, *common),
            ("replay-protocol", subject, *common, "--runs", str(missing / "runs")),
            (
                "run-scenario",
                subject,
                "absent-assumption.json",
                "absent-scenario.json",
                "--input-root",
                str(missing / "inputs"),
                *common,
                "--runs",
                str(missing / "runs"),
            ),
            (
                "freeze-search-plan",
                subject,
                "absent-assumption.json",
                "absent-search.json",
                "--input-root",
                str(missing / "inputs"),
                *common,
                "--plans",
                str(missing / "plans"),
            ),
        ):
            failure = run(*command, "--split", "confirmation", expected=5, mode="pre-io")
            assert failure["error"]["code"] == "confirmation_access_denied"
            assert not missing.exists()
            pre_io.append({"command": command[0], "error": failure})

        assert readonly_before == (
            _tree(data, exclude_state=True),
            _tree(registry),
            _tree(alternate_registry),
            _tree(executable_registry),
        )
        owner_observations = [
            json.loads(line) for line in (inputs / "confirmation.jsonl").read_bytes().splitlines()
        ]
        assert owner_observations == originals
        report = {
            "kind": "installed_confirmation_exposure_acceptance_v1",
            "accepted": True,
            "synthetic_data": True,
            "core_only_guard": True,
            "cases": cases,
            "corrupt_store_cases": corrupt_cases,
            "exploration_pre_io": pre_io,
            "exposure_ledger": audit,
            "freeze_repetitions": [repeated, repeated_after],
            "successful_exposure_ids": [receipt["exposure_id"] for _, receipt in successful],
            "idempotent_freeze": True,
            "source_records_unchanged": True,
            "repeated_open_denied_before_data_read": True,
            "origin_overlap_inherited": True,
            "whole_window_limits_enforced": True,
            "confirmation_state_fixed_to_dataset_root": True,
            "host_owner_direct_file_read_possible": True,
            "host_owner_confidentiality_claimed": False,
            "historical_unseen_certified": False,
            "new_native_calls": False,
            "new_attempts_reserved": False,
            "old_budget_mutations": False,
            "scope": _SCOPE,
        }
        arguments.report.parent.mkdir(parents=True, exist_ok=True)
        arguments.report.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
        shutil.copytree(directory, arguments.records_dir)
        (arguments.records_dir / "artifact-files.json").write_bytes(
            _canonical(_tree(arguments.records_dir))
        )
        print(f"Installed confirmation acceptance: {len(cases)} cases, {len(successful)} exposures")


if __name__ == "__main__":
    main()
