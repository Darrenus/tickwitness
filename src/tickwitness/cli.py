"""Minimal installable entry point, without simulated research functionality."""

import argparse
from importlib.metadata import version


def main() -> int:
    """Expose package identity and help while the research commands are developed."""
    parser = argparse.ArgumentParser(
        prog="tickwitness",
        description=(
            "TickWitness development foundation. "
            "Import, replay, search, and evidence commands are not implemented yet."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {version('tickwitness')}")
    parser.parse_args()
    parser.print_help()
    return 0
