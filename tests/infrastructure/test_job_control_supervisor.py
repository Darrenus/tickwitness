"""Controlled processes and explicit offline native ports test control boundaries.

Native saved-result ports below do not qualify actual native computation. The
remote installed controls lifecycle separately supplies that evidence.
"""

import time
from threading import Thread

from test_job_supervisor import _command, _queued, _wait_for
from test_native_job_supervisor import native_job_root as native_job_root
from test_native_job_supervisor import queued, saved_worker
from test_reduction_execution import forbidden
from test_reduction_execution import reduction_case as reduction_case

from tickwitness.domain.evidence.run_records import canonical
from tickwitness.domain.jobs.control import build_job_control_policy
from tickwitness.infrastructure import job_reduction, job_supervisor
from tickwitness.infrastructure.job_controls import JobControlStore
from tickwitness.infrastructure.job_supervisor import run_job


def configure(store, row, **limits):
    controls = JobControlStore(store.root, row["job_id"])
    policy = build_job_control_policy(row["job_id"], **limits)
    with store.coordinator():
        controls.configure(policy)
    return controls, policy


def test_cancelled_queue_never_prepares_reserves_or_launches_and_same_terminal_is_stable(
    tmp_path, monkeypatch
):
    store, row = _queued(tmp_path)
    controls, _policy = configure(store, row)
    accepted = controls.request_cancel("cancel-once", now_ns=time.time_ns(), snapshot=row)
    assert accepted["status"] == "accepted"
    monkeypatch.setattr(job_supervisor.subprocess, "Popen", forbidden)
    terminal = run_job(store, row["job_id"])
    assert terminal["state"] == "FAILED"
    assert terminal["failure"]["code"] == "job_cancelled"
    assert terminal["failure"]["worker_exit_code"] is None
    proof = controls.result()
    assert proof["stop_confirmed"] and proof["cleanup_confirmed"]
    assert not proof["worker_started"] and proof["workspace_removed"]
    assert proof["catalog_state"] == "FAILED"
    assert not (controls.directory / "workspaces").exists()
    assert not (tmp_path / "research-runs").exists()
    before = canonical(terminal), store.events(row["job_id"]), canonical(proof)
    assert run_job(store, row["job_id"]) == terminal
    repeated = controls.request_cancel(
        "cancel-once", now_ns=time.time_ns(), snapshot=terminal
    )
    assert repeated["status"] == "already_requested"
    assert repeated["request"] == accepted["request"]
    assert (canonical(store.get(row["job_id"])), store.events(row["job_id"]),
            canonical(controls.result())) == before


def test_total_deadline_stops_genuine_heartbeats_and_cleans_owned_scratch(tmp_path):
    store, row = _queued(tmp_path, lease_ns=1_000_000_000)
    controls, policy = configure(store, row, max_wall_ns=3_000_000_000)
    command = _command(
        tmp_path,
        "for sequence in range(1, 501):\n"
        "    emit('job_heartbeat_v1', sequence)\n"
        "    time.sleep(0.05)\n",
    )
    started = time.monotonic_ns()
    terminal = run_job(store, row["job_id"], _worker_command=command)
    elapsed = time.monotonic_ns() - started
    assert terminal["state"] in {"FAILED", "LOST"}
    if terminal["state"] == "FAILED":
        assert terminal["failure"]["code"] == "job_deadline_exceeded"
    assert terminal["attempt"]["heartbeat_sequence"] >= 3
    proof = controls.result()
    assert proof["cause"] == "job_deadline_exceeded"
    assert proof["stop_confirmed"] and proof["worker_group_absent"]
    assert proof["workspace_removed"] and proof["cleanup_confirmed"]
    assert proof["timing_ns"]["elapsed"] >= policy.document["limits"]["max_wall_ns"]
    assert elapsed >= policy.document["limits"]["max_wall_ns"]
    assert store.result(row["job_id"]) is None
    assert controls.publication_admission() is None


def test_durable_cancel_from_another_controller_stops_live_owned_process(tmp_path):
    store, row = _queued(tmp_path)
    controls, _policy = configure(store, row, max_wall_ns=10_000_000_000)
    command = _command(
        tmp_path,
        "for sequence in range(1, 501):\n"
        "    emit('job_heartbeat_v1', sequence)\n"
        "    time.sleep(0.05)\n",
    )
    observations, failures = [], []

    def request():
        try:
            current = _wait_for(
                lambda: (value if (value := store.get(row["job_id"]))["attempt"]
                         and value["attempt"]["heartbeat_sequence"] >= 3 else None),
                timeout=5,
            )
            peer = JobControlStore(store.root, row["job_id"])
            observations.append(peer.request_cancel(
                "live-controller", now_ns=time.time_ns(), snapshot=current
            ))
        except Exception as error:
            failures.append(error)

    controller = Thread(target=request)
    controller.start()
    try:
        terminal = run_job(store, row["job_id"], _worker_command=command)
    finally:
        controller.join(timeout=6)
    assert not controller.is_alive() and not failures
    assert observations[0]["status"] == "accepted"
    assert terminal["state"] == "FAILED" and terminal["failure"]["code"] == "job_cancelled"
    proof = controls.result()
    assert proof["cause"] == "job_cancelled" and proof["stop_confirmed"]
    assert proof["worker_started"] and proof["worker_group_absent"]
    assert proof["timing_ns"]["request_observed"] is not None
    assert proof["timing_ns"]["worker_reaped"] is not None
    assert proof["timing_ns"]["cleanup_finished"] is not None


def test_cancel_before_irreversible_admission_keeps_consumed_native_slot_unfinalized(
    reduction_case, native_job_root, tmp_path, monkeypatch
):
    value = reduction_case
    spec, store, row = queued(value, native_job_root)
    controls, _policy = configure(store, row)
    monkeypatch.setattr(job_reduction, "require_native_runtime", lambda: None)

    def cancel_before_admission(current):
        observed = controls.request_cancel(
            "before-publication", now_ns=time.time_ns(), snapshot=current
        )
        assert observed["status"] == "accepted"

    monkeypatch.setattr(job_supervisor, "_before_control_publication", cancel_before_admission)
    terminal = run_job(store, spec.spec_id, _worker_command=saved_worker(value, tmp_path))
    assert terminal["state"] == "FAILED" and terminal["failure"]["code"] == "job_cancelled"
    slots = value.ledger.list_reservations(
        value.prepared.materialization.source.validation.protocol
    )
    assert len(slots) == 4
    assert value.ledger.get_outcome(slots[-1].attempt_id) is None
    assert store.result(spec.spec_id) is None
    assert controls.publication_admission() is None
    assert controls.result()["stop_confirmed"]


def test_publication_admission_wins_late_cancel_without_rewriting_success(
    reduction_case, native_job_root, tmp_path, monkeypatch
):
    value = reduction_case
    spec, store, row = queued(value, native_job_root)
    controls, _policy = configure(store, row)
    monkeypatch.setattr(job_reduction, "require_native_runtime", lambda: None)
    original = job_reduction.publish_reduction_execution
    observed = []

    def cancel_after_admission(*args, **kwargs):
        peer = JobControlStore(store.root, spec.spec_id)
        observed.append(peer.request_cancel(
            "after-publication", now_ns=time.time_ns(), snapshot=store.get(spec.spec_id)
        ))
        return original(*args, **kwargs)

    monkeypatch.setattr(job_reduction, "publish_reduction_execution", cancel_after_admission)
    terminal = run_job(store, spec.spec_id, _worker_command=saved_worker(value, tmp_path))
    assert terminal["state"] == "SUCCEEDED"
    assert observed[0]["status"] == "too_late"
    assert observed[0]["publication_admission"] is not None
    assert controls.cancel_request() is None
    proof = controls.result()
    assert proof["publication_admitted"] and not proof["stop_confirmed"]
    assert proof["cleanup_confirmed"] and proof["cause"] == "finished"
    before = canonical(terminal), store.result(spec.spec_id), canonical(proof)
    assert run_job(store, spec.spec_id) == terminal
    assert (canonical(store.get(spec.spec_id)), store.result(spec.spec_id),
            canonical(controls.result())) == before
