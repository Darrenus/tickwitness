#!/usr/bin/env python3
"""Capture release metadata and installed-source hashes without network access."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
from pathlib import Path

import hftbacktest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pypi-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.pypi_json.read_bytes()
    release = json.loads(raw)
    dist = importlib.metadata.distribution("hftbacktest")
    package_root = Path(hftbacktest.__file__).parent
    source_hashes = {}
    for name in ("__init__.py", "binding.py", "types.py", "order.py", "state.py", "recorder.py"):
        source_hashes[name] = hashlib.sha256((package_root / name).read_bytes()).hexdigest()
    binary = next(package_root.glob("_hftbacktest*.so"))
    source_hashes[binary.name] = hashlib.sha256(binary.read_bytes()).hexdigest()
    wheels = [item for item in release["urls"] if item["filename"].endswith(".whl")]
    summary = {
        "observed_client_date": "2026-10-25",
        "source_url": "https://pypi.org/pypi/hftbacktest/2.4.4/json",
        "source_json_sha256": hashlib.sha256(raw).hexdigest(),
        "release_version": release["info"]["version"],
        "requires_python": release["info"]["requires_python"],
        "requires_dist": release["info"]["requires_dist"],
        "license_classifiers": [s for s in release["info"]["classifiers"] if s.startswith("License")],
        "wheel_files": [
            {
                "filename": item["filename"],
                "sha256": item["digests"]["sha256"],
                "upload_time": item["upload_time_iso_8601"],
            }
            for item in sorted(wheels, key=lambda item: item["filename"])
        ],
        "installed_version": dist.version,
        "installed_source_sha256": source_hashes,
        "python": sys.version,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "backtest_asset_public_methods": sorted(name for name in dir(hftbacktest.BacktestAsset()) if not name.startswith("_")),
        "limits": [
            "Wheel availability does not establish successful installation on every listed platform.",
            "Only macOS arm64 / CPython 3.12.14 was executed in this spike.",
            "No complete checkpoint restore or complete per-fill event sink was verified.",
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({"version": dist.version, "wheel_count": len(wheels), "output": str(args.output)}))


if __name__ == "__main__":
    main()
