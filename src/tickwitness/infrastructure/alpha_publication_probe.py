"""Actual controlled kit publication faults, isolated to a fresh scratch root.

No process-global IO functions are replaced. Failure publications never return
a success receipt; the complete postcommit artifact is retained for inspection.
"""

from __future__ import annotations

import os
from contextlib import ExitStack
from pathlib import Path

from tickwitness.application.alpha_scorecard import AlphaKit, BoundaryProbeResult
from tickwitness.infrastructure import evidence_bundles as _io
from tickwitness.infrastructure.alpha_reproduction_kits import (
    AlphaKitDestinationExistsError,
    AlphaKitDurabilityError,
    AlphaKitError,
    AlphaReproductionKit,
    _publish_alpha_kit,
    publish_alpha_kit,
    read_alpha_kit,
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AlphaKitError("Alpha publication probe failed: " + message)


class LocalAlphaPublicationProbe:
    def __init__(self, root: Path) -> None:
        self._root = Path(root).absolute()

    def _new_root(self) -> None:
        _io._posix()
        if not self._root.name or self._root.name in {".", ".."}:
            raise AlphaKitError("Publication probe must name a new scratch directory")
        try:
            with ExitStack() as stack:
                parent = os.open(
                    self._root.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                )
                stack.callback(os.close, parent)
                try:
                    os.mkdir(self._root.name, 0o700, dir_fd=parent)
                except FileExistsError as error:
                    raise AlphaKitDestinationExistsError(
                        "Alpha probe root already exists"
                    ) from error
                directory = _io._directory(parent, self._root.name)
                stack.callback(os.close, directory)
                os.fsync(directory)
                os.fsync(parent)
        except AlphaKitError:
            raise
        except (OSError, ValueError) as error:
            raise AlphaKitError("Cannot create fresh alpha probe root: " + str(error)) from error

    def run(self, kit: AlphaKit) -> BoundaryProbeResult:
        # Snapshot only immutable contents, never a kit-supplied fault result.
        try:
            checked = AlphaReproductionKit(kit.manifest_bytes, tuple(sorted(kit.files.items())))
            _require(checked.kit_id == kit.kit_id, "supplied kit identity differs")
        except (AttributeError, TypeError, ValueError) as error:
            if isinstance(error, AlphaKitError):
                raise
            raise AlphaKitError("Invalid alpha probe kit: " + str(error)) from error
        self._new_root()
        normal_path = self._root / "normal"
        published = publish_alpha_kit(normal_path, checked)
        before = read_alpha_kit(normal_path, expected_kit_id=checked.kit_id)
        _require(published == before == checked, "normal publication changed content")
        try:
            publish_alpha_kit(normal_path, checked)
        except AlphaKitDestinationExistsError as error:
            existing_type = type(error).__name__
        else:
            raise AlphaKitError("Alpha existing-destination probe unexpectedly returned success")
        unchanged = read_alpha_kit(normal_path, expected_kit_id=checked.kit_id) == before
        _require(unchanged, "existing destination changed")

        precommit_path = self._root / "precommit"
        prefault = False

        def precommit_sync(directory: int, phase: str) -> None:
            nonlocal prefault
            if phase == "stage":
                prefault = True
                raise OSError("Controlled alpha precommit directory sync failure")
            os.fsync(directory)

        try:
            _publish_alpha_kit(precommit_path, checked, sync=precommit_sync)
        except AlphaKitError as error:
            _require(type(error) is AlphaKitError and prefault, "wrong precommit failure")
            precommit_type = type(error).__name__
        else:
            raise AlphaKitError("Alpha precommit fault unexpectedly returned success")
        precommit_exists = os.path.lexists(precommit_path)
        with os.scandir(self._root) as children:
            remaining = sum(child.name.startswith(".tickwitness-alpha-kit-") for child in children)
        _require(not precommit_exists and remaining == 0, "precommit staging was not removed")

        postcommit_path = self._root / "postcommit"
        postfault = False

        def postcommit_sync(directory: int, phase: str) -> None:
            nonlocal postfault
            if phase == "parent":
                postfault = True
                raise OSError("Controlled alpha postcommit parent sync failure")
            os.fsync(directory)

        try:
            _publish_alpha_kit(postcommit_path, checked, sync=postcommit_sync)
        except AlphaKitDurabilityError as error:
            _require(postfault, "postcommit fault did not execute")
            postcommit_type = type(error).__name__
        else:
            raise AlphaKitError("Alpha postcommit fault unexpectedly returned success")
        postcommit_exists = os.path.lexists(postcommit_path)
        _require(postcommit_exists, "postcommit artifact was removed")
        retained = read_alpha_kit(postcommit_path, expected_kit_id=checked.kit_id)
        _require(retained == checked, "postcommit artifact differs from supplied content")
        document: dict[str, object] = {
            "kind": "alpha_kit_publication_probe_v1",
            "schema_version": 1,
            "profile": "alpha_kit_precommit_sync_postcommit_parent_sync_v1",
            "kit_id": checked.kit_id,
            "normal_publication": {
                "published_kit_id": published.kit_id,
                "readback_kit_id": before.kit_id,
                "success_returned": True,
            },
            "existing_destination": {
                "exception_type": existing_type,
                "success_returned": False,
                "original_tree_unchanged": unchanged,
            },
            "precommit_sync_failure": {
                "fault_injected": prefault,
                "exception_type": precommit_type,
                "success_returned": False,
                "target_exists": precommit_exists,
                "staging_entries_remaining": remaining,
            },
            "postcommit_parent_sync_failure": {
                "fault_injected": postfault,
                "exception_type": postcommit_type,
                "success_returned": False,
                "target_exists": postcommit_exists,
                "retained_kit_id": retained.kit_id,
            },
        }
        return BoundaryProbeResult(document=document, postcommit_kit=retained)
