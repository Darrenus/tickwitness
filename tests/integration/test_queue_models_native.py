"""Public native queue hooks are qualified only on fixed synthetic observations."""

import importlib.util
import json
from importlib import metadata
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "qualify_queue_models.py"
SPEC = importlib.util.spec_from_file_location("tickwitness_queue_qualification", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
qualification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualification)


def native_present() -> bool:
    try:
        return metadata.version("nautilus_trader") == "1.231.0"
    except metadata.PackageNotFoundError:
        return False


@pytest.mark.skipif(not native_present(), reason="optional pinned Nautilus extra absent")
@pytest.mark.parametrize("case_id", qualification.CASE_IDS)
def test_public_native_shadow_queue_extension(case_id: str) -> None:
    case = qualification.run_case(case_id)
    assert case["passed"] is True, json.dumps(
        {
            "case_id": case_id,
            "error": case.get("error"),
            "failed": [item for item in case["checks"] if not item["passed"]],
        }
    )
