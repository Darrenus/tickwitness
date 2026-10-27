"""Frozen finding authority, explicit issuance and independent final-content verification."""

from __future__ import annotations

import argparse
from pathlib import Path

from tickwitness.application.research import ConfirmationAccessDenied
from tickwitness.application.tagged_findings import (
    freeze_finding_protocol,
    inspect_finding_protocol,
    issue_tagged_findings,
    verify_finding_package,
)
from tickwitness.domain.evidence.run_records import identity
from tickwitness.infrastructure.safe_input import read_regular_file
from tickwitness.infrastructure.tagged_evidence_bundles import read_tagged_pair_bundle
from tickwitness.infrastructure.tagged_finding_bundles import (
    TaggedFindingArtifactBundle,
    export_tagged_finding_bundle,
    read_tagged_finding_bundle,
)
from tickwitness.infrastructure.tagged_finding_registry import LocalTaggedFindingRegistry
from tickwitness.infrastructure.tagged_queue_registry import LocalTaggedQueueRegistry

COMMANDS = frozenset(
    {
        "freeze-tagged-finding-protocol",
        "inspect-tagged-finding-protocol",
        "issue-tagged-findings",
        "verify-tagged-findings",
    }
)


def add_commands(commands: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    freeze = commands.add_parser(
        "freeze-tagged-finding-protocol", help="Freeze separate conditional report authority"
    )
    freeze.add_argument("subject_protocol_id")
    freeze.add_argument("request")
    freeze.add_argument("--input-root", required=True, type=Path)
    freeze.add_argument("--registry", required=True, type=Path)
    inspect = commands.add_parser(
        "inspect-tagged-finding-protocol", help="Read the exact frozen reporting authority"
    )
    inspect.add_argument("finding_protocol_id")
    inspect.add_argument("--registry", required=True, type=Path)
    issue = commands.add_parser(
        "issue-tagged-findings", help="Publish conditional findings from pinned sealed evidence"
    )
    issue.add_argument("finding_protocol_id")
    issue.add_argument("directory", type=Path)
    issue.add_argument("--expected-bundle-id", required=True)
    issue.add_argument("--registry", required=True, type=Path)
    issue.add_argument("--output", required=True, type=Path)
    verify = commands.add_parser(
        "verify-tagged-findings", help="Recompute sealed findings without registry or native"
    )
    verify.add_argument("directory", type=Path)
    verify.add_argument("--expected-bundle-id")
    for command in (freeze, inspect, issue, verify):
        command.add_argument(
            "--split", choices=("development", "confirmation"), default="development"
        )


def execute(arguments: argparse.Namespace) -> dict[str, object]:
    if arguments.split != "development":
        raise ConfirmationAccessDenied("Tagged findings permit development evidence only")
    if arguments.command == "freeze-tagged-finding-protocol":
        identity(arguments.subject_protocol_id)
        request = read_regular_file(
            arguments.input_root,
            arguments.request,
            max_bytes=16 * 1024,
            allowed_suffixes=frozenset({".json"}),
        )
        return freeze_finding_protocol(
            arguments.subject_protocol_id,
            request,
            split=arguments.split,
            subjects_factory=lambda: LocalTaggedQueueRegistry(arguments.registry, create=False),
            findings_factory=lambda: LocalTaggedFindingRegistry(arguments.registry, create=True),
        ).document
    if arguments.command == "inspect-tagged-finding-protocol":
        return inspect_finding_protocol(
            arguments.finding_protocol_id,
            split=arguments.split,
            findings_factory=lambda: LocalTaggedFindingRegistry(arguments.registry, create=False),
        )
    if arguments.expected_bundle_id is not None:
        identity(arguments.expected_bundle_id)
    if arguments.command == "verify-tagged-findings":
        return verify_finding_package(
            read_tagged_finding_bundle(arguments.directory),
            expected_bundle_id=arguments.expected_bundle_id,
        )

    def publish(artifacts: dict[str, bytes]) -> TaggedFindingArtifactBundle:
        export_tagged_finding_bundle(arguments.output, artifacts)
        return read_tagged_finding_bundle(arguments.output)

    return issue_tagged_findings(
        arguments.finding_protocol_id,
        expected_source_bundle_id=arguments.expected_bundle_id,
        split=arguments.split,
        findings_factory=lambda: LocalTaggedFindingRegistry(arguments.registry, create=False),
        source_factory=lambda: read_tagged_pair_bundle(arguments.directory),
        publisher=publish,
    )
