"""Native qualification separates shared observations, shadow values and claim truth."""

import importlib.util
import json
from importlib import metadata
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "qualify_queue_semantics.py"
SPEC = importlib.util.spec_from_file_location("tickwitness_queue_semantics_qualification", SCRIPT)
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
def test_actual_persistent_pair_semantics_has_independent_positive_and_negative_oracles(case_id):
    case = qualification.run_case(case_id)
    assert case["passed"] is True, json.dumps(
        {
            "case_id": case_id,
            "error": case.get("error"),
            "failed": [item for item in case["checks"] if not item["passed"]],
        }
    )
    assert [item["policy_id"] for item in case["native_calls"]] == list(qualification.POLICIES)
    assert len({item["attempt_id"] for item in case["native_calls"]}) == 2
    assert case["stages"] == [
        "qualification_predicates_frozen",
        "source_and_shared_budget_family_frozen",
        "persistent_native_dual_execution_completed",
        "read_only_projection_and_predicate_diagnostics_completed",
    ]
    pair = case["production_pair_qualification"]
    assert pair["observation_compatibility"]["status"] == "not_established"
    assert pair["predicate"]["truth_divergence"] is None and pair["findings"] == []
    if case_id == "higher_mark_gt_zero":
        diagnostic = case["diagnostic_predicates"][0]
        assert [item["value"] for item in diagnostic["observations"]] == ["1", "0"]
        assert [item["satisfied"] for item in diagnostic["observations"]] == [True, False]
        assert diagnostic["comparison"]["diagnostic_status"] == "DIAGNOSTIC_PREDICATE_DISAGREEMENT"
        assert pair["models"][0]["single_counted_insertion"]["status"] == "contradiction"
    elif case_id == "standard_gt_zero":
        diagnostic = case["diagnostic_predicates"][0]
        assert [item["value"] for item in diagnostic["observations"]] == ["-1", "0"]
        assert [item["satisfied"] for item in diagnostic["observations"]] == [False, False]
    elif case_id == "flat_zero_comparator_boundaries":
        assert [row["observations"][0]["satisfied"] for row in case["diagnostic_predicates"]] == [
            False,
            True,
            False,
            True,
        ]


def test_qualifier_rejects_arbitrary_case_before_fixtures_storage_or_native(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Unknown cases cannot read fixtures or construct storage")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(qualification, "TemporaryDirectory", forbidden)
    with pytest.raises(ValueError, match="fixed original"):
        qualification.run_case("arbitrary-user-observations")
