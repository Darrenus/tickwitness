"""Remote native clock hypotheses; an absent optional engine is an explicit skip."""

import importlib.util
import json
from importlib import metadata
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "qualify_scenario_clocks.py"
SPEC = importlib.util.spec_from_file_location("tickwitness_clock_qualification", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
qualification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(qualification)


def native_present() -> bool:
    try:
        metadata.version("nautilus_trader")
    except metadata.PackageNotFoundError:
        return False
    return True


@pytest.mark.skipif(not native_present(), reason="optional Nautilus extra absent")
@pytest.mark.parametrize("case_id", qualification.CASE_IDS)
def test_native_step_coupled_clock_hypothesis(case_id: str) -> None:
    case = qualification.run_case(case_id)
    failed = [check for check in case["checks"] if not check["passed"]]
    assert case["passed"] is True, json.dumps(
        {"case_id": case_id, "error": case.get("error"), "failed": failed}
    )
