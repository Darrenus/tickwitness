#!/usr/bin/env python3
"""Qualify installed DatasetStore orphan retention without research execution.

The bytes in this fixture establish storage/reference behavior, not market-data
quality or a research verdict. Existing control/research records are only hashed.
"""

import argparse
import hashlib
import json
import shutil
import subprocess
import time
import tomllib
from contextlib import contextmanager, suppress
from pathlib import Path
from tempfile import TemporaryDirectory

_NO_NATIVE = """
import importlib.abc
from importlib import metadata
import hashlib,json,os,sys
from pathlib import Path
try:metadata.version('nautilus_trader')
except metadata.PackageNotFoundError:pass
else:raise AssertionError('Retention requires an independently installed core-only interpreter')
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith('nautilus_trader'):
            raise AssertionError('Retention qualification cannot import native')
sys.meta_path.insert(0,NoNative())
def document(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,
                      allow_nan=False).encode()
def digest(raw):return hashlib.sha256(raw).hexdigest()
"""

_IDENTITY = """
print(document({'executable':sys.executable,'prefix':sys.prefix,'base_prefix':sys.base_prefix,
    'native_distribution':None,'project_version':metadata.version('tickwitness')}).decode())
"""

_SETUP = """
import time
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore,DatasetStoreError
root=Path(sys.argv[1]);root.mkdir()
store=root/'store';mixed=root/'mixed'
owner=LocalDatasetStore(store)
first=owner.publish(b'shared retained raw fixture',b'first normalized storage fixture',
                    {'fixture':'storage only','version':1})
second=owner.publish(b'shared retained raw fixture',b'second normalized storage fixture',
                     {'fixture':'storage only','version':2})
connection=owner._connection
def fail_catalog(*args,**kwargs):
    raise OSError('Declared interruption after manifest and before Catalog visibility')
owner._connection=fail_catalog
try:
    try:owner.publish(b'unindexed raw fixture',b'unindexed normalized fixture',
                      {'fixture':'unindexed valid manifest'})
    except DatasetStoreError:pass
    else:raise AssertionError('Unindexed publication injection did not fail')
finally:owner._connection=connection
publish_file=owner._publish_file
def orphan(raw):
    expected=digest(raw)
    def interrupted(directory,name,data):
        publish_file(directory,name,data)
        if name==expected:raise OSError('Declared interruption after first durable CAS write')
    owner._publish_file=interrupted
    try:
        try:owner.publish(raw,b'never installed normalized fixture',{'fixture':'never installed'})
        except DatasetStoreError:pass
        else:raise AssertionError('First-CAS interruption injection did not fail')
    finally:owner._publish_file=publish_file
    assert (store/'objects'/'sha256'/expected).read_bytes()==raw
    return expected
orphans=[orphan(b'first interrupted orphan fixture'),orphan(b'second interrupted orphan fixture')]
future=orphan(b'future-dated orphan is retained')
future_ns=time.time_ns()+86400*1000000000
os.utime(store/'objects'/'sha256'/future,ns=(future_ns,future_ns))
manifests=sorted(path.stem for path in (store/'manifests').glob('*.json'))
catalog=sorted(record.dataset_id for record in owner.list_datasets())
assert catalog==sorted([first.dataset_id,second.dataset_id]) and len(manifests)==3
assert len(set(manifests)-set(catalog))==1
protected=sorted({reference['sha256'] for identity in manifests for reference in
    json.loads((store/'manifests'/(identity+'.json')).read_bytes())['objects'].values()})
assert len(protected)==8
mixed_record=LocalDatasetStore(mixed).publish(b'mixed raw',b'mixed normalized',
                                           {'fixture':'mixed namespace refusal'})
(mixed/'slots').mkdir()
(mixed/'slots'/'unrelated-owner.txt').write_bytes(b'Unknown ledger-like namespace must be retained')
print(document({'store':str(store),'catalog_datasets':catalog,'manifest_ids':manifests,
    'unindexed_manifest_id':next(iter(set(manifests)-set(catalog))),
    'protected_objects':protected,'orphans':sorted(orphans),'future_orphan':future,
    'mixed_store':str(mixed),'mixed_protected':sorted(reference['sha256'] for reference in
        mixed_record.manifest['objects'].values()),'fixture_only':True,
    'new_native_calls':0,'new_research_slots':0}).decode())
"""

_READ_BACK = """
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
root=Path(sys.argv[1]);expected=json.loads(sys.argv[2])
store=LocalDatasetStore(root,create=False)
catalog=sorted(record.dataset_id for record in store.list_datasets())
assert catalog==expected
records={identity:{role:digest(raw) for role,raw in store.read_artifacts(identity).items()}
         for identity in expected}
closure={}
for path in sorted((root/'manifests').glob('*.json')):
    raw=path.read_bytes();manifest=json.loads(raw)
    assert digest(raw)==path.stem and document(manifest)==raw
    closure[str(path.relative_to(root))]=digest(raw)
    for reference in manifest['objects'].values():
        name=reference['sha256'];data=(root/'objects'/'sha256'/name).read_bytes()
        assert digest(data)==name and len(data)==reference['size_bytes']
        closure['objects/sha256/'+name]=digest(data)
print(document({'catalog':catalog,'records':records,'all_manifest_closures':closure}).decode())
"""

_QUIESCE = """
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
root=Path(sys.argv[1])
before=[name for name in ('catalog.sqlite3-wal','catalog.sqlite3-shm','catalog.sqlite3-journal')
        if (root/name).exists()]
store=LocalDatasetStore(root)
record=store.publish(b'shared retained raw fixture',b'first normalized storage fixture',
                     {'fixture':'storage only','version':1})
assert record.created is False
after=[name for name in ('catalog.sqlite3-wal','catalog.sqlite3-shm','catalog.sqlite3-journal')
       if (root/name).exists()]
assert after==[]
print(document({'kind':'declared_fixture_quiescence_v1','dataset_id':record.dataset_id,
    'ordinary_validated_rw_initialization':True,'ordinary_idempotent_publication':True,
    'created':False,'sidecars_before':before,
    'sidecars_after':after,'new_native_calls':0,'new_research_slots':0}).decode())
"""

_ADD_ORPHAN = """
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore,DatasetStoreError
store=LocalDatasetStore(Path(sys.argv[1]),create=False)
raw=b'New orphan changes the frozen inventory';expected=digest(raw)
actual=store._publish_file
def interrupted(directory,name,data):
    actual(directory,name,data)
    if name==expected:raise OSError('Declared first-CAS interruption for inventory drift')
store._publish_file=interrupted
try:store.publish(raw,b'not installed',{'fixture':'not installed'})
except DatasetStoreError:pass
else:raise AssertionError('Inventory drift injection did not fail')
print(document({'orphan':expected,'new_native_calls':0,'new_research_slots':0}).decode())
"""

_WRITER = """
import time
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
root,controls=Path(sys.argv[1]),Path(sys.argv[2])
controls.mkdir()
store=LocalDatasetStore(root,create=False)
raw=b'Active publisher first CAS';expected=digest(raw);actual=store._publish_file
def paused(directory,name,data):
    actual(directory,name,data)
    if name==expected:
        (controls/'ready.pending').write_bytes(document({'pid':os.getpid(),'first_cas':expected,
            'phase':'after_first_cas_before_manifest_and_catalog'}))
        os.replace(controls/'ready.pending',controls/'ready.json')
        deadline=time.monotonic()+20
        while not (controls/'release').exists() and time.monotonic()<deadline:time.sleep(0.01)
        if not (controls/'release').exists():raise AssertionError('Publisher release timed out')
store._publish_file=paused
record=store.publish(raw,b'Active publisher normalized',{'fixture':'active publisher'})
print(document({'dataset_id':record.dataset_id,'pid':os.getpid(),
                'new_native_calls':0,'new_research_slots':0}).decode())
"""

_GC_CLI = """
import builtins,io,socket,sqlite3,stat,subprocess
from urllib.parse import parse_qs,unquote,urlsplit
from tickwitness.cli import main
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.bounded_replay import BoundedReplayAdapter
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter
target=Path(sys.argv.pop(1)).resolve()
rules=json.loads(sys.argv.pop(1));log=Path(sys.argv.pop(1))
command=sys.argv[1];applying=command=='apply-dataset-retention'
assert command in ('plan-dataset-retention','apply-dataset-retention')
protected=set(rules['protected']);allowed=set(rules['orphans']);intended=set(rules['intended'])
objects=target/'objects'/'sha256'
objects_stat=os.stat(objects) if objects.is_dir() else None
directories={}
for directory in (target,target/'objects',objects,target/'manifests'):
    if directory.is_dir():
        info=os.stat(directory);directories[(info.st_dev,info.st_ino)]=directory
events={'orphan_opens':[],'unlinked':[],'sqlite_uris':[],'sql':[],'fsync_directories':[],
        'retained_payload_reads':0,'metadata_write_attempts':0}
def forbidden(*args,**kwargs):
    raise AssertionError(
        'Retention cannot execute research, write metadata or read retained payloads')
LocalDatasetStore.__init__=forbidden
LocalDatasetStore.publish=forbidden
BoundedReplayAdapter.__init__=forbidden
SubprocessReplayAdapter.__init__=forbidden
for name in ('reserve','reserve_with_nonce','bind_intent','publish'):
    setattr(LocalAttemptLedger,name,forbidden)
socket.socket=forbidden;socket.create_connection=forbidden;subprocess.Popen=forbidden
actual_open=os.open;actual_io=io.open;actual_builtin=builtins.open
actual_unlink=os.unlink;actual_connect=sqlite3.connect;actual_fsync=os.fsync
def object_name(path,dir_fd=None):
    if isinstance(path,int):return None
    text=os.fsdecode(path)
    selected=Path(text)
    if dir_fd is not None:
        info=os.fstat(dir_fd)
        parent=directories.get((info.st_dev,info.st_ino))
        if parent is not None:selected=parent/selected
    if not selected.is_absolute():selected=Path.cwd()/selected
    if selected.parent.resolve()==objects:return selected.name
    return None
def check_read(path,dir_fd=None):
    name=object_name(path,dir_fd)
    if name in protected:
        events['retained_payload_reads']+=1;forbidden()
    if name is not None:
        if name not in allowed:forbidden()
        events['orphan_opens'].append(name)
def opened(path,flags,mode=0o777,*,dir_fd=None):
    if flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND|os.O_EXCL):
        events['metadata_write_attempts']+=1;forbidden()
    check_read(path,dir_fd)
    return actual_open(path,flags,mode,dir_fd=dir_fd)
def io_open(file,mode='r',*args,**kwargs):
    if any(value in mode for value in ('w','a','x','+')):
        events['metadata_write_attempts']+=1;forbidden()
    check_read(file)
    return actual_io(file,mode,*args,**kwargs)
def builtin_open(file,mode='r',*args,**kwargs):
    if any(value in mode for value in ('w','a','x','+')):
        events['metadata_write_attempts']+=1;forbidden()
    check_read(file)
    return actual_builtin(file,mode,*args,**kwargs)
def unlink(path,*,dir_fd=None):
    name=object_name(path,dir_fd)
    if not applying or name not in intended:forbidden()
    actual_unlink(path,dir_fd=dir_fd);events['unlinked'].append(name)
def fsync(descriptor):
    info=os.fstat(descriptor)
    if not stat.S_ISDIR(info.st_mode):forbidden()
    actual_fsync(descriptor)
    events['fsync_directories'].append({'device':info.st_dev,'inode':info.st_ino,
        'objects':objects_stat is not None and
                  (info.st_dev,info.st_ino)==(objects_stat.st_dev,objects_stat.st_ino)})
def connect(database,*args,**kwargs):
    locator=str(database);parsed=urlsplit(locator);query=parse_qs(parsed.query)
    if parsed.scheme!='file' or Path(unquote(parsed.path)).resolve()!=target/'catalog.sqlite3':
        forbidden()
    if query.get('mode')!=['ro'] or query.get('immutable')!=['1'] or not kwargs.get('uri'):
        forbidden()
    events['sqlite_uris'].append(locator)
    connection=actual_connect(database,*args,**kwargs)
    writes={sqlite3.SQLITE_INSERT,sqlite3.SQLITE_UPDATE,sqlite3.SQLITE_DELETE,
        sqlite3.SQLITE_CREATE_TABLE,sqlite3.SQLITE_CREATE_INDEX,sqlite3.SQLITE_CREATE_TRIGGER,
        sqlite3.SQLITE_CREATE_VIEW,sqlite3.SQLITE_DROP_TABLE,sqlite3.SQLITE_DROP_INDEX,
        sqlite3.SQLITE_DROP_TRIGGER,sqlite3.SQLITE_DROP_VIEW,sqlite3.SQLITE_ATTACH,
        sqlite3.SQLITE_DETACH,sqlite3.SQLITE_ALTER_TABLE,sqlite3.SQLITE_REINDEX,
        sqlite3.SQLITE_ANALYZE,sqlite3.SQLITE_CREATE_TEMP_TABLE,sqlite3.SQLITE_CREATE_TEMP_INDEX,
        sqlite3.SQLITE_CREATE_TEMP_TRIGGER,sqlite3.SQLITE_CREATE_TEMP_VIEW,
        sqlite3.SQLITE_DROP_TEMP_TABLE,sqlite3.SQLITE_DROP_TEMP_INDEX,
        sqlite3.SQLITE_DROP_TEMP_TRIGGER,sqlite3.SQLITE_DROP_TEMP_VIEW}
    def authorize(action,first,second,database,trigger):
        if action in writes:return sqlite3.SQLITE_DENY
        if action==sqlite3.SQLITE_PRAGMA and second is not None:
            if (first,second) not in (('trusted_schema','OFF'),('query_only','ON'),
                                      ('trusted_schema','0'),('query_only','1')):
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    connection.set_authorizer(authorize)
    connection.set_trace_callback(events['sql'].append)
    return connection
os.open=opened;io.open=io_open;builtins.open=builtin_open
if actual_open in os.supports_dir_fd:
    os.supports_dir_fd=os.supports_dir_fd|{opened}
os.unlink=unlink;os.remove=unlink;os.fsync=fsync;sqlite3.connect=connect
for name in ('mkdir','makedirs','rmdir','rename','replace','link','symlink','truncate',
             'chmod','fchmod','chown','fchown','utime'):
    setattr(os,name,forbidden)
result=main(sys.argv[1:])
assert events['retained_payload_reads']==0 and events['metadata_write_attempts']==0
with actual_io(log,'wb') as stream:stream.write(document(events))
raise SystemExit(result)
"""

_CONFIRMATION_CLI = """
import io,sqlite3
from tickwitness.cli import main
from tickwitness.infrastructure.dataset_retention import LocalDatasetMaintenance
def forbidden(*args,**kwargs):
    raise AssertionError('Confirmation must reject before ID, plan or store IO')
LocalDatasetMaintenance.__init__=forbidden
os.open=forbidden;sqlite3.connect=forbidden;io.open=forbidden
Path.open=forbidden;Path.read_bytes=forbidden;Path.stat=forbidden;Path.lstat=forbidden
raise SystemExit(main(sys.argv[1:]))
"""


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def tree(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise AssertionError("Qualification records cannot contain symlinks")
        if path.is_file():
            with path.open("rb") as stream:
                content_hash = hashlib.file_digest(stream, "sha256").hexdigest()
            result[str(path.relative_to(root))] = content_hash
    return result


@contextmanager
def workspace(records):
    with TemporaryDirectory(prefix="tickwitness-retention-") as temporary:
        root = Path(temporary)
        try:
            yield root
        except BaseException as error:
            with suppress(OSError, ValueError):
                if not records.exists():
                    shutil.copytree(root, records)
                (records / "qualification-failure.json").write_bytes(
                    canonical({"accepted": False, "message": str(error)[:4096]})
                )
                inventory = {
                    name: value
                    for name, value in tree(records).items()
                    if name != "artifact-files.json"
                }
                (records / "artifact-files.json").write_bytes(canonical(inventory))
            raise


def check_preview(value):
    assert set(value) == {"kind", "schema_version", "plan_id", "plan", "execution_authorized"}
    assert value["kind"] == "dataset_retention_preview_v1" and value["schema_version"] == 1
    assert value["execution_authorized"] is False
    plan = value["plan"]
    assert set(plan) == {
        "kind",
        "schema_version",
        "status",
        "policy",
        "observed_at_ns",
        "store",
        "reference_sha256",
        "files",
        "protected_objects",
        "candidates",
        "diagnostics",
    }
    assert plan["kind"] == "dataset_retention_plan_v1" and plan["schema_version"] == 1
    assert sha(canonical(plan)) == value["plan_id"]
    assert plan["candidates"] == sorted(set(plan["candidates"]))
    assert plan["status"] in {"READY", "BLOCKED"}
    if plan["status"] == "BLOCKED":
        assert not plan["candidates"] and plan["diagnostics"]
    return plan


def check_result(value, preview, *, status):
    assert set(value) == {
        "kind",
        "schema_version",
        "plan_id",
        "status",
        "intended",
        "unlinked",
        "already_absent",
        "removed_logical_bytes",
        "diagnostic",
    }
    assert value["kind"] == "dataset_retention_result_v1" and value["schema_version"] == 1
    assert value["plan_id"] == preview["plan_id"] and value["status"] == status
    assert value["intended"] == preview["plan"]["candidates"]
    assert value["unlinked"] == sorted(set(value["unlinked"]))
    if status == "APPLIED":
        assert value["diagnostic"] is None
        assert sorted(value["unlinked"] + value["already_absent"]) == value["intended"]
    else:
        assert value["diagnostic"] and not value["unlinked"]


def main():
    parser = argparse.ArgumentParser()
    for name in ("python", "report", "records-dir"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--source-records", type=Path)
    args = parser.parse_args()
    if (
        args.report.exists()
        or args.report.is_symlink()
        or args.records_dir.exists()
        or args.records_dir.is_symlink()
    ):
        raise FileExistsError("Retention qualification destinations must be new")
    if args.report.absolute().is_relative_to(args.records_dir.absolute()):
        raise ValueError("Retention outer report must be separate from records")
    if args.source_records is not None:
        source_root = args.source_records.resolve()
        if any(
            destination.resolve().is_relative_to(source_root)
            or source_root.is_relative_to(destination.resolve())
            for destination in (args.report, args.records_dir)
        ):
            raise ValueError("Retention destinations must be disjoint from original records")
    interpreter = str(args.python.absolute())
    source_before = None if args.source_records is None else tree(args.source_records)
    source_report = None
    if args.source_records is not None:
        source_report = json.loads(
            (args.source_records / "job-controls-smoke" / "report.json").read_bytes()
        )
        assert source_report["kind"] == "installed_job_controls_acceptance_v1"
        assert source_report["accepted"] is True
    project = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text())[
        "project"
    ]
    with workspace(args.records_dir) as root:
        cwd, transcripts, guards, plans, snapshots = (
            root / name for name in ("unrelated-cwd", "transcripts", "guards", "plans", "snapshots")
        )
        for directory in (cwd, transcripts, guards, plans, snapshots):
            directory.mkdir()
        calls = []

        def invoke(code, command=(), *, expected=0, stdout=True):
            completed = subprocess.run(
                [interpreter, "-I", "-B", "-c", _NO_NATIVE + code, *command],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
                timeout=45,
            )
            record = {
                "executable": interpreter,
                "entry": ["-c", _NO_NATIVE + code],
                "command": list(command),
                "exit_code": completed.returncode,
                "expected_exit_code": expected,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
            }
            calls.append(record)
            number = f"{len(calls):04d}"
            (transcripts / (number + ".json")).write_bytes(canonical(record))
            if completed.returncode != expected or (
                completed.stderr if stdout else completed.stdout
            ):
                raise RuntimeError(f"Installed retention invocation failed: {record}")
            payload = json.loads(completed.stdout if stdout else completed.stderr)
            return payload, number

        identity, _ = invoke(_IDENTITY)
        assert identity["executable"] == interpreter
        assert identity["project_version"] == project["version"]
        assert identity["native_distribution"] is None
        fixture, _ = invoke(_SETUP, (str(root / "fixture"),))
        store, mixed = Path(fixture["store"]), Path(fixture["mixed_store"])
        protected = fixture["protected_objects"]
        orphans = [*fixture["orphans"], fixture["future_orphan"]]
        before_read, _ = invoke(_READ_BACK, (str(store), json.dumps(fixture["catalog_datasets"])))
        quiescence, _ = invoke(_QUIESCE, (str(store),))
        quiescences = [quiescence]
        shutil.copytree(store, snapshots / "before")
        observations = []

        def gc(command, *, target=store, intended=(), expected=0):
            number = f"{len(calls) + 1:04d}"
            log = guards / (number + ".json")
            rules = {
                "protected": protected if target == store else fixture["mixed_protected"],
                "orphans": orphans if target == store else [],
                "intended": list(intended),
            }
            before = tree(target)
            payload, actual_number = invoke(
                _GC_CLI, (str(target), json.dumps(rules), str(log), *command), expected=expected
            )
            assert actual_number == number
            observation = {
                "transcript": number,
                "before": before,
                "after": tree(target),
                "response": payload,
                "guard": json.loads(log.read_bytes()),
            }
            observations.append(observation)
            assert observation["guard"]["retained_payload_reads"] == 0
            assert observation["guard"]["metadata_write_attempts"] == 0
            return payload, observation

        preview, planned = gc(
            ("plan-dataset-retention", "--store", str(store), "--min-age-seconds", "0")
        )
        plan = check_preview(preview)
        assert plan["status"] == "READY" and not plan["diagnostics"]
        assert plan["candidates"] == fixture["orphans"]
        assert plan["protected_objects"] == protected
        assert str(store) not in canonical(plan).decode()
        assert planned["before"] == planned["after"]
        assert sorted(set(planned["guard"]["orphan_opens"])) == sorted(orphans)
        assert not planned["guard"]["unlinked"]
        assert not planned["guard"]["fsync_directories"]
        assert all(
            row["content_verified"] is False
            for row in plan["files"]
            if row["path"].removeprefix("objects/sha256/") in protected
        )
        reference = {
            "catalog": [
                {"dataset_id": key, "manifest_sha256": key, "sealed": 1}
                for key in fixture["catalog_datasets"]
            ],
            "manifests": fixture["manifest_ids"],
        }
        assert plan["reference_sha256"] == sha(canonical(reference))
        plan_file = plans / "original.json"
        plan_file.write_text(calls[-1]["stdout"])
        command = (
            "apply-dataset-retention",
            "--store",
            str(store),
            "--plan",
            str(plan_file),
            "--expected-plan-id",
            preview["plan_id"],
        )
        applied, applied_observation = gc(command, intended=plan["candidates"])
        check_result(applied, preview, status="APPLIED")
        assert applied["unlinked"] == plan["candidates"] and not applied["already_absent"]
        assert sorted(applied_observation["guard"]["unlinked"]) == plan["candidates"]
        assert any(item["objects"] for item in applied_observation["guard"]["fsync_directories"])
        removed_paths = {"objects/sha256/" + key for key in plan["candidates"]}
        assert (
            set(applied_observation["before"]) - set(applied_observation["after"]) == removed_paths
        )
        assert {
            key: value
            for key, value in applied_observation["before"].items()
            if key not in removed_paths
        } == applied_observation["after"]
        expected_bytes = sum((snapshots / "before" / name).stat().st_size for name in removed_paths)
        assert applied["removed_logical_bytes"] == expected_bytes
        repeated, repeat_observation = gc(command, intended=plan["candidates"])
        check_result(repeated, preview, status="APPLIED")
        assert not repeated["unlinked"] and repeated["already_absent"] == plan["candidates"]
        assert repeated["removed_logical_bytes"] == 0
        assert repeat_observation["before"] == repeat_observation["after"]
        assert not repeat_observation["guard"]["unlinked"]
        assert any(item["objects"] for item in repeat_observation["guard"]["fsync_directories"])
        after_read, _ = invoke(_READ_BACK, (str(store), json.dumps(fixture["catalog_datasets"])))
        assert before_read == after_read
        quiescence, _ = invoke(_QUIESCE, (str(store),))
        quiescences.append(quiescence)
        shutil.copytree(store, snapshots / "after")
        mixed_preview, mixed_observation = gc(
            ("plan-dataset-retention", "--store", str(mixed), "--min-age-seconds", "0"),
            target=mixed,
        )
        mixed_plan = check_preview(mixed_preview)
        assert mixed_plan["status"] == "BLOCKED" and "unknown_entry" in mixed_plan["diagnostics"]
        assert mixed_observation["before"] == mixed_observation["after"]
        mixed_file = plans / "mixed.json"
        mixed_file.write_text(calls[-1]["stdout"])
        refused, refused_observation = gc(
            (
                "apply-dataset-retention",
                "--store",
                str(mixed),
                "--plan",
                str(mixed_file),
                "--expected-plan-id",
                mixed_preview["plan_id"],
            ),
            target=mixed,
            expected=9,
        )
        check_result(refused, mixed_preview, status="REFUSED")
        assert refused["diagnostic"] == "blocked_plan"
        assert refused_observation["before"] == refused_observation["after"]
        extra, _ = invoke(_ADD_ORPHAN, (str(store),))
        quiescence, _ = invoke(_QUIESCE, (str(store),))
        quiescences.append(quiescence)
        orphans.append(extra["orphan"])
        drifted, drift_observation = gc(command, intended=plan["candidates"], expected=9)
        check_result(drifted, preview, status="REFUSED")
        assert drifted["diagnostic"] == "snapshot_changed"
        assert drift_observation["before"] == drift_observation["after"]
        writer_controls = root / "writer-controls"
        writer = subprocess.Popen(
            [interpreter, "-I", "-B", "-c", _NO_NATIVE + _WRITER, str(store), str(writer_controls)],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            deadline = time.monotonic() + 20
            while not (writer_controls / "ready.json").exists() and time.monotonic() < deadline:
                if writer.poll() is not None:
                    raise RuntimeError("Publisher failed before its first-CAS gate")
                time.sleep(0.01)
            ready = json.loads((writer_controls / "ready.json").read_bytes())
            assert ready["pid"] == writer.pid
            busy, busy_observation = gc(
                ("plan-dataset-retention", "--store", str(store), "--min-age-seconds", "0")
            )
            busy_plan = check_preview(busy)
            assert busy_plan["status"] == "BLOCKED"
            assert "maintenance_busy" in busy_plan["diagnostics"]
            assert busy_observation["before"] == busy_observation["after"]
            assert not busy_observation["guard"]["orphan_opens"]
            assert not busy_observation["guard"]["sqlite_uris"]
        finally:
            writer_controls.mkdir(exist_ok=True)
            (writer_controls / "release").touch()
            try:
                writer_out, writer_err = writer.communicate(timeout=25)
            except subprocess.TimeoutExpired:
                writer.kill()
                writer.communicate(timeout=5)
                raise
        writer_transcript = {
            "executable": interpreter,
            "entry": ["-c", _NO_NATIVE + _WRITER],
            "command": [str(store), str(writer_controls)],
            "pid": writer.pid,
            "exit_code": writer.returncode,
            "expected_exit_code": 0,
            "stdout": writer_out,
            "stderr": writer_err,
        }
        (root / "writer-transcript.json").write_bytes(canonical(writer_transcript))
        assert writer.returncode == 0 and not writer_err
        published = json.loads(writer_out)
        assert published["pid"] == ready["pid"] == writer.pid
        (writer_controls / "finished.json").write_bytes(canonical(published))
        refusals = []
        missing = root / "never-created-store"
        for name in ("plan-dataset-retention", "apply-dataset-retention"):
            arguments = [name, "--store", str(missing), "--split", "confirmation"]
            if name == "apply-dataset-retention":
                arguments += ["--plan", str(root / "missing-plan"), "--expected-plan-id", "invalid"]
            error, _ = invoke(_CONFIRMATION_CLI, arguments, expected=5, stdout=False)
            assert error["error"]["code"] == "confirmation_access_denied"
            refusals.append({"command": name, "response": error})
        assert not missing.exists()
        source_after = None if args.source_records is None else tree(args.source_records)
        assert source_after == source_before
        report = {
            "kind": "installed_dataset_retention_acceptance_v1",
            "schema_version": 1,
            "accepted": True,
            "interpreter_identity": identity,
            "source_driver_sha256": sha(Path(__file__).read_bytes()),
            "fixture": fixture,
            "before_retained_read": before_read,
            "after_retained_read": after_read,
            "declared_fixture_sqlite_quiescence": quiescences,
            "preview": preview,
            "applied": applied,
            "repeated": repeated,
            "mixed_refusal": refused,
            "inventory_drift_refusal": drifted,
            "active_publisher": {
                "ready": ready,
                "blocked": busy,
                "finished": published,
                "transcript": "writer-transcript.json",
            },
            "confirmation_refusals": refusals,
            "observations": observations,
            "source_controls_core_only": None
            if source_report is None
            else source_report["core_only_profile"],
            "protected_source_before": source_before,
            "protected_source_after": source_after,
            "scope": {
                "dataset_store_orphans_only": True,
                "all_physical_manifests_retained": True,
                "retained_payload_reads_by_gc": False,
                "metadata_created_by_gc": False,
                "actual_publisher_gate_probe": True,
                "actual_reader_gate_probe": False,
                "partial_unlink_and_fsync_live_probes": False,
                "new_native_calls": 0,
                "new_research_slots": 0,
                "historical_missing_entry_credit": False,
                "physical_freed_bytes_measured": False,
                "external_human_attempts": 0,
                "external_human_gate": "PENDING",
            },
        }
        inner = root / "dataset-retention-smoke" / "report.json"
        inner.parent.mkdir()
        inner.write_bytes(canonical(report))
        shutil.copytree(root, args.records_dir)
        (args.records_dir / "artifact-files.json").write_bytes(canonical(tree(args.records_dir)))
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_bytes(canonical(report))


if __name__ == "__main__":
    main()
