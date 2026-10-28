"""Assemble transferable alpha evidence and explicitly rerun its technical checks."""

from __future__ import annotations

import argparse
import re
from importlib.metadata import version
from pathlib import Path

from tickwitness.application.alpha_scorecard import (
    MAX_ALPHA_RECEIPT_BYTES,
    evaluate_alpha_kit,
    prepare_alpha_suite,
    verify_alpha_scorecard,
)
from tickwitness.domain.evidence.alpha_scorecard import AlphaValidationError
from tickwitness.domain.evidence.run_records import identity
from tickwitness.infrastructure.alpha_publication_probe import LocalAlphaPublicationProbe
from tickwitness.infrastructure.alpha_reproduction_kits import export_alpha_kit, read_alpha_kit
from tickwitness.infrastructure.safe_input import read_regular_file
from tickwitness.infrastructure.search_evidence_bundles import read_search_evidence_bundle

COMMANDS = frozenset({"export-alpha-kit", "qualify-alpha-kit", "verify-alpha-scorecard"})


def _identity(value: str) -> str:
    try:
        return identity(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def _revision(value: str) -> str:
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise argparse.ArgumentTypeError("source revision must be 40 lowercase hexadecimal digits")
    return value


def _file(path: Path, maximum: int, suffix: str) -> bytes:
    absolute = path.absolute()
    return read_regular_file(
        absolute.parent,
        absolute.name,
        max_bytes=maximum,
        allowed_suffixes=frozenset({suffix}),
    )


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    export = commands.add_parser(
        "export-alpha-kit", help="Publish a pinned, transferable core-only reproduction kit"
    )
    for option in ("counterexample", "clean-control", "wheel", "guide", "runner", "output"):
        export.add_argument("--" + option, type=Path, required=True)
    export.add_argument("--source-revision", type=_revision, required=True)
    qualify = commands.add_parser(
        "qualify-alpha-kit", help="Re-audit both cases and execute fresh publication boundary checks"
    )
    verify = commands.add_parser(
        "verify-alpha-scorecard", help="Recompute a saved technical scorecard using a fresh probe"
    )
    verify.add_argument("saved", help="Relative saved receipt .json under --input-root")
    verify.add_argument("--input-root", type=Path, required=True)
    for command in (qualify, verify):
        command.add_argument("kit", type=Path)
        command.add_argument("--expected-kit-id", type=_identity, required=True)
        command.add_argument("--probe-root", type=Path, required=True)


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.command == "export-alpha-kit":
        output = arguments.output.resolve()
        for source in (arguments.counterexample, arguments.clean_control):
            if output.is_relative_to(source.resolve()):
                raise AlphaValidationError("Alpha kit output must be outside original case roots")
        counterexample = read_search_evidence_bundle(arguments.counterexample)
        clean = read_search_evidence_bundle(arguments.clean_control)
        suite = prepare_alpha_suite(counterexample, clean)
        kit = export_alpha_kit(
            arguments.output,
            suite_bytes=suite.canonical_bytes,
            wheel_name=arguments.wheel.name,
            wheel_bytes=_file(arguments.wheel, 4 * 1024 * 1024, ".whl"),
            guide_bytes=_file(arguments.guide, 64 * 1024, ".md"),
            runner_bytes=_file(arguments.runner, 64 * 1024, ".py"),
            counterexample=counterexample,
            clean_control=clean,
            producer_version=version("tickwitness"),
            source_revision=arguments.source_revision,
        )
        reread = read_alpha_kit(arguments.output, expected_kit_id=kit.kit_id)
        if reread.manifest_bytes != kit.manifest_bytes or reread.files != kit.files:
            raise AlphaValidationError("Published alpha kit changed before readback")
        checked = prepare_alpha_suite(reread.case("counterexample"), reread.case("clean_control"))
        if checked.canonical_bytes != suite.canonical_bytes:
            raise AlphaValidationError("Published alpha suite changed during readback")
        return {
            "kind": "alpha_kit_export_receipt_v1",
            "schema_version": 1,
            "kit_id": kit.kit_id,
            "suite_id": suite.suite_id,
            "source_revision": arguments.source_revision,
            "technical_qualification_performed": False,
            "external_attempts": 0,
            "release_authorized": False,
        }
    if arguments.probe_root.resolve().is_relative_to(arguments.kit.resolve()):
        raise AlphaValidationError("Publication probe root must be outside the original kit")
    kit = read_alpha_kit(arguments.kit, expected_kit_id=arguments.expected_kit_id)
    if arguments.command == "qualify-alpha-kit":
        return evaluate_alpha_kit(
            kit,
            expected_kit_id=arguments.expected_kit_id,
            publication_probe_factory=lambda: LocalAlphaPublicationProbe(arguments.probe_root),
        )
    saved = read_regular_file(
        arguments.input_root,
        arguments.saved,
        max_bytes=MAX_ALPHA_RECEIPT_BYTES,
        allowed_suffixes=frozenset({".json"}),
    ).removesuffix(b"\n")
    return verify_alpha_scorecard(
        kit,
        saved,
        expected_kit_id=arguments.expected_kit_id,
        publication_probe_factory=lambda: LocalAlphaPublicationProbe(arguments.probe_root),
    )
