#!/usr/bin/env python3
"""Qualify the installed public SDK using an independent downstream consumer.

Only fresh owned data/declaration fixtures are exercised. Previous operational
and research evidence is binary-hashed, never opened as a store or executed.
"""

import argparse
import hashlib
import json
import os
import shlex
import shutil
import stat
import subprocess
import time
import tomllib
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory

_BASE = r"""
import atexit,hashlib,importlib.abc,json,os,runpy,socket,subprocess,sys
from dataclasses import asdict
from importlib import metadata
from pathlib import Path
from unittest.mock import patch
guard_path=Path(sys.argv.pop(1))
def document(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,
                      allow_nan=False).encode()
def digest(raw):return hashlib.sha256(raw).hexdigest()
try:metadata.version('nautilus_trader')
except metadata.PackageNotFoundError:pass
else:raise AssertionError('SDK qualification requires an independently installed core wheel')
guard={'forbidden_attempts':[],'native_import_attempts':[]}
native_prefixes=('nautilus_trader','tickwitness.infrastructure._nautilus_native',
    'tickwitness.infrastructure._queue_native','tickwitness.infrastructure._tagged_queue_native')
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if any(fullname==name or fullname.startswith(name+'.') for name in native_prefixes):
            guard['native_import_attempts'].append(fullname)
            raise AssertionError('The SDK consumer cannot import native code')
sys.meta_path.insert(0,NoNative())
# Load CLI annotations before replacing Popen; exercises occur after all guards.
from tickwitness.cli import main as cli_main
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.bounded_replay import BoundedReplayAdapter
from tickwitness.infrastructure.campaign_budget_store import LocalCampaignBudgetStore
from tickwitness.infrastructure.executable_registry import LocalExecutableProtocolRegistry
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore
from tickwitness.infrastructure.local_protocol_registry import LocalProtocolRegistry
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter
def blocked(name):
    def refuse(*args,**kwargs):
        guard['forbidden_attempts'].append(name)
        raise AssertionError('SDK qualification forbids '+name)
    return refuse
socket.socket=blocked('network.socket')
socket.create_connection=blocked('network.connection')
subprocess.Popen=blocked('child.subprocess')
for adapter in (BoundedReplayAdapter,SubprocessReplayAdapter):
    adapter.__init__=blocked('engine.'+adapter.__name__)
for repository in (LocalAttemptLedger,LocalCampaignBudgetStore,LocalExecutableProtocolRegistry):
    repository.__init__=blocked('research_repository.'+repository.__name__)
for name in ('reserve','reserve_with_nonce','bind_intent','publish'):
    setattr(LocalAttemptLedger,name,blocked('ledger.'+name))
from tickwitness import sdk
from tickwitness.sdk import Client,SDKError
origin=Path(sdk.__file__).absolute()
typed=origin.parent/'py.typed'
assert origin.is_relative_to(Path(sys.prefix).absolute())
assert sys.prefix!=sys.base_prefix and typed.is_file()
assert sdk.SDK_CONTRACT_VERSION==1
assert set(sdk.__all__)=={'SDK_CONTRACT_VERSION','Client','SDKError','ValidationLimits',
                         'ImportReceipt','ProtocolReceipt','DevelopmentRead'}
runtime={'executable':sys.executable,'prefix':sys.prefix,'base_prefix':sys.base_prefix,
    'cwd':os.getcwd(),'sys_path':sys.path,'sdk_origin':str(origin),
    'sdk_sha256':digest(origin.read_bytes()),'py_typed':str(typed),
    'py_typed_sha256':digest(typed.read_bytes()),'native_distribution':None,
    'project_version':metadata.version('tickwitness'),'sdk_contract_version':1}
def save_guard():
    guard_path.write_bytes(document({'runtime':runtime,'guard':guard,
        'native_modules':[name for name in sys.modules if any(
            name==prefix or name.startswith(prefix+'.') for prefix in native_prefixes)],
        'guarded_before_sdk_import':True,'new_native_calls':0,'new_research_slots':0}))
atexit.register(save_guard)
"""

_IDENTITY = "print(document(runtime).decode())\n"

_CONSUMER = r"""
entry=Path(sys.argv.pop(1))
sys.argv=[str(entry),*sys.argv[1:]]
runpy.run_path(str(entry),run_name='__main__')
"""

_DOCUMENTATION = r"""
entry,inputs,store,registry=map(Path,sys.argv[1:])
assert not store.exists() and not registry.exists()
namespace=runpy.run_path(str(entry),run_name='sdk_documentation_example')
recipe=namespace['import_and_inspect']
first=recipe('development.jsonl',input_root=inputs,store=store,registry=registry)
repeated=recipe('development.jsonl',input_root=inputs,store=store,registry=registry)
assert isinstance(first,sdk.ImportReceipt) and isinstance(repeated,sdk.ImportReceipt)
assert first.created is False and repeated.created is False
assert asdict(first)==asdict(repeated)
client=Client(store=store,registry=registry)
persisted=client.inspect_dataset(first.dataset_id)
assert asdict(persisted)==asdict(first)
# Explicit ordinary duplicate import closes this example's owned SQLite sidecars.
quiescence=client.import_events('development.jsonl',input_root=inputs)
assert quiescence.created is False and not registry.exists()
assert not any((store/name).exists() for name in (
    'catalog.sqlite3-wal','catalog.sqlite3-shm','catalog.sqlite3-journal'))
print(document({'receipt':asdict(first),'repeated_receipt':asdict(repeated),
    'persisted_receipt':asdict(persisted),'explicit_quiescence':asdict(quiescence),
    'input':'development.jsonl','input_root':str(inputs),'store':str(store),
    'registry':str(registry),'registry_created':False,'sidecars_after':[],
    'source_sha256':digest(entry.read_bytes()),
    'input_sha256':digest((inputs/'development.jsonl').read_bytes())}).decode())
"""

_CLI = "raise SystemExit(cli_main(sys.argv[1:]))\n"

_NEGATIVES = r"""
import shutil
root,inputs=Path(sys.argv[1]),Path(sys.argv[2])
healthy=json.loads(Path(sys.argv[3]).read_bytes())
negatives=root/'negatives';negatives.mkdir()
images=root/'images';images.mkdir()
client=Client(store=root/'sdk-store',registry=root/'sdk-registry')
dataset_id=healthy['dataset_first']['dataset_id']
confirmation_id=healthy['confirmation_first']['dataset_id']
protocol_id=healthy['protocol_first']['protocol_id']
def json_value(value):return json.loads(document(asdict(value)))
def sidecars(store):
    return [name for name in ('catalog.sqlite3-wal','catalog.sqlite3-shm',
                              'catalog.sqlite3-journal') if (store/name).exists()]
assert sidecars(root/'sdk-store')==[]
shutil.copytree(root/'sdk-store',images/'sdk-before')
shutil.copytree(root/'sdk-registry',images/'registry-before')
outcomes={}
def refuse(name,action,code,exit_code,*,translated=True):
    try:action()
    except SDKError as error:
        assert error.code==code and error.exit_code==exit_code
        assert (error.__cause__ is not None) is translated
        envelope=error.as_dict()
        assert envelope=={'error':{'code':code,'message':str(error)}}
        alternate=error.as_dict();alternate['error']['code']='caller mutation'
        assert error.as_dict()==envelope
        outcomes[name]={'response':envelope,'exit_code':error.exit_code,
            'cause':None if error.__cause__ is None else type(error.__cause__).__name__}
    else:raise AssertionError('SDK accepted refused case '+name)
invalid_store=negatives/'sdk-invalid-store'
invalid=Client(store=invalid_store,registry=negatives/'unused-registry')
(inputs/'invalid.jsonl').write_bytes(b'{}'+bytes([10]))
(inputs/'invalid_strategy.py').write_bytes(b'x ='+bytes([10]))
refuse('invalid_data',lambda:invalid.import_events('invalid.jsonl',input_root=inputs),
       'invalid_data',2)
assert not invalid_store.exists()
invalid_registry=negatives/'sdk-invalid-registry'
refuse('invalid_strategy',lambda:Client(store=root/'sdk-store',registry=invalid_registry)
    .freeze_protocol('request.json',input_root=inputs,strategy_source='invalid_strategy.py',
    development_dataset_id=dataset_id,confirmation_dataset_id=confirmation_id),
    'invalid_protocol',2)
assert not invalid_registry.exists()
schema_cases={}
event_rows=[json.loads(line) for line in (inputs/'development.jsonl').read_bytes().splitlines()]
event_rows[0]['execution_ready']=True
event_input=inputs/'unknown-event.jsonl'
event_input.write_bytes(b''.join(document(row)+bytes([10]) for row in event_rows))
with patch.object(sdk,'_LocalDatasetStore',blocked('unknown_event.target_store_constructor')):
    refuse('unknown_event',lambda:invalid.import_events('unknown-event.jsonl',input_root=inputs),
           'invalid_data',2)
assert not invalid_store.exists()
schema_cases['unknown_event']={'input':str(event_input),
    'input_sha256':digest(event_input.read_bytes()),'destination':str(invalid_store),
    'destination_created':False,'refusal_before_target_store_factory':True}
def freeze_request(filename,registry):
    return Client(store=root/'sdk-store',registry=registry).freeze_protocol(filename,
        input_root=inputs,strategy_source='strategy.py',development_dataset_id=dataset_id,
        confirmation_dataset_id=confirmation_id)
request=json.loads((inputs/'request.json').read_bytes())
for location in ('request','claim','configuration','budget'):
    changed=json.loads(document(request))
    target=changed if location=='request' else changed[location]
    target['execution_ready']=True
    name='unknown_'+location
    filename='unknown-'+location+'.json'
    (inputs/filename).write_bytes(document(changed))
    rejected_registry=negatives/('sdk-'+name+'-registry')
    refuse(name,lambda filename=filename,registry=rejected_registry:
        freeze_request(filename,registry),'invalid_protocol',2)
    assert not rejected_registry.exists()
    schema_cases[name]={'input':str(inputs/filename),
        'input_sha256':digest((inputs/filename).read_bytes()),
        'destination':str(rejected_registry),'destination_created':False,
        'all_protected_io_avoided':False}
for shape,value in (('object',{'nested':1}),('list',[1])):
    changed=json.loads(document(request))
    changed['parameters']['unsupported_nested']=value
    name='nested_parameter_'+shape
    filename='nested-parameter-'+shape+'.json'
    (inputs/filename).write_bytes(document(changed))
    rejected_registry=negatives/('sdk-'+name+'-registry')
    refuse(name,lambda filename=filename,registry=rejected_registry:
        freeze_request(filename,registry),'invalid_protocol',2)
    assert not rejected_registry.exists()
    schema_cases[name]={'input':str(inputs/filename),
        'input_sha256':digest((inputs/filename).read_bytes()),
        'destination':str(rejected_registry),'destination_created':False}
open_source_quiescence=client.import_events('development.jsonl',input_root=inputs)
assert open_source_quiescence.created is False and sidecars(root/'sdk-store')==[]
assert json_value(open_source_quiescence)==healthy['quiescence']
open_root=root/'open-parameters';open_root.mkdir()
shutil.copytree(root/'sdk-store',open_root/'store')
open_client=Client(store=open_root/'store',registry=open_root/'registry')
def open_freeze(filename):
    return open_client.freeze_protocol(filename,input_root=inputs,strategy_source='strategy.py',
        development_dataset_id=dataset_id,confirmation_dataset_id=confirmation_id)
open_baseline=open_freeze('request.json')
assert open_baseline.protocol_id==protocol_id
custom=json.loads(document(request))
custom['parameters'].update({'execution_ready':True,'custom_scalar_count':7,
    'custom_scalar_label':'first','custom_scalar_optional':None})
(inputs/'open-parameters.json').write_bytes(document(custom))
open_custom=open_freeze('open-parameters.json')
changed=json.loads(document(custom));changed['parameters']['custom_scalar_label']='second'
(inputs/'changed-parameters.json').write_bytes(document(changed))
open_changed=open_freeze('changed-parameters.json')
assert len({open_baseline.protocol_id,open_custom.protocol_id,open_changed.protocol_id})==3
for receipt,expected in ((open_baseline,request),(open_custom,custom),(open_changed,changed)):
    assert receipt.created is True
    assert receipt.document['parameters']==expected['parameters']
    assert receipt.claim_revision_id==healthy['protocol_inspected']['claim_revision_id']
    assert receipt.document['execution_ready'] is False
    for field in ('budget','datasets','strategy','configuration','read_policy'):
        assert receipt.document[field]==healthy['protocol_inspected']['document'][field]
open_inspected=open_client.inspect_protocol(open_custom.protocol_id)
assert open_inspected.created is False and open_inspected.document==open_custom.document
open_read=open_client.read_protocol_data(open_custom.protocol_id,limit=1)
assert open_read.protocol_id==open_custom.protocol_id and open_read.dataset_id==dataset_id
assert open_read.observations[0]['receive_time_ns'] is None
refuse('open_parameter_frozen_limit',lambda:open_client.read_protocol_data(
    open_custom.protocol_id,limit=3),'invalid_protocol',2)
open_quiescence=open_client.import_events('development.jsonl',input_root=inputs)
assert open_quiescence.created is False and sidecars(open_root/'store')==[]
open_parameters={'root':str(open_root),'store':str(open_root/'store'),
    'registry':str(open_root/'registry'),'baseline_first':json_value(open_baseline),
    'custom_first':json_value(open_custom),'changed_first':json_value(open_changed),
    'custom_inspected':json_value(open_inspected),'development':json_value(open_read),
    'source_explicit_quiescence':json_value(open_source_quiescence),
    'explicit_quiescence':json_value(open_quiescence),
    'custom_input':str(inputs/'open-parameters.json'),
    'custom_input_sha256':digest((inputs/'open-parameters.json').read_bytes()),
    'changed_input':str(inputs/'changed-parameters.json'),
    'changed_input_sha256':digest((inputs/'changed-parameters.json').read_bytes()),
    'parameters_identity_bound':True,'claim_identity_unchanged':True,
    'executable_authority_added':False,'frozen_budget_unchanged':True,'sidecars_after':[]}
absent=root/'must-remain-absent'
denied=Client(store=absent/'store',registry=absent/'registry')
with patch.object(LocalDatasetStore,'__init__',blocked('confirmation.dataset_constructor')), \
     patch.object(LocalProtocolRegistry,'__init__',blocked('confirmation.registry_constructor')):
    refuse('confirmation',lambda:denied.read_protocol_data(protocol_id,
        split='confirmation',limit=1),'confirmation_access_denied',5)
    refuse('confirmation_preflight',lambda:denied.read_protocol_data('invalid-identity',
        split='unsupported',limit=-1),'confirmation_access_denied',5)
assert not absent.exists()
refuse('frozen_limit',lambda:client.read_protocol_data(protocol_id,limit=3),'invalid_protocol',2)
refuse('missing_dataset',lambda:client.inspect_dataset('0'*64),'dataset_not_found',4)
refuse('missing_protocol',lambda:client.inspect_protocol('0'*64),'protocol_not_found',4)
link=inputs/'linked.jsonl';link.symlink_to(inputs/'development.jsonl')
link_facts={'path':str(link),'target':os.readlink(link),'mode':link.lstat().st_mode,
    'target_sha256':digest((inputs/'development.jsonl').read_bytes())}
(root/'owned-symlink.json').write_bytes(document(link_facts))
refuse('symlink',lambda:invalid.import_events('linked.jsonl',input_root=inputs),
       'unsafe_input',2)
refuse('traversal',lambda:invalid.import_events('../development.jsonl',input_root=inputs),
       'unsafe_input',2)
assert not invalid_store.exists()
refuse('malformed_identity',lambda:client.inspect_dataset('not-an-identity'),
       'invalid_sdk_argument',2,translated=False)
record=client.inspect_dataset(dataset_id)
record.manifest['objects']['raw']['ref']='caller changed reference'
record.report['replay_certified']=True
declaration=client.inspect_protocol(protocol_id)
declaration.document['budget']['max_events']=999999
observations=client.read_protocol_data(protocol_id,limit=1)
observations.observations[0]['receive_time_ns']=123456
assert json_value(client.inspect_dataset(dataset_id))==healthy['dataset_inspected']
assert json_value(client.inspect_protocol(protocol_id))==healthy['protocol_inspected']
assert json_value(client.read_protocol_data(protocol_id,limit=1))==healthy['development']
refuse('frozen_limit_after_mutation',lambda:client.read_protocol_data(protocol_id,limit=3),
       'invalid_protocol',2)
quiescence=client.import_events('development.jsonl',input_root=inputs)
assert quiescence.created is False and sidecars(root/'sdk-store')==[]
shutil.copytree(root/'sdk-store',images/'sdk-after')
shutil.copytree(root/'sdk-registry',images/'registry-after')
corrupt=negatives/'corrupt-store'
shutil.copytree(root/'sdk-store',corrupt)
shutil.copytree(corrupt,images/'corrupt-before')
relative=healthy['dataset_first']['manifest']['objects']['raw']['ref']
target=corrupt/relative;original=target.read_bytes()
damaged=bytes([original[0]^1])+original[1:];target.write_bytes(damaged)
corrupted=Client(store=corrupt,registry=root/'sdk-registry')
refuse('corrupt_object',lambda:corrupted.inspect_dataset(dataset_id),
       'store_integrity_or_publication_failure',3)
prepared=corrupted.import_events('confirmation.jsonl',input_root=inputs)
assert prepared.created is False and sidecars(corrupt)==[]
assert target.read_bytes()==damaged
shutil.copytree(corrupt,images/'corrupt-sdk-failed')
print(document({'outcomes':outcomes,'confirmation_precedes_constructors_identity_limit':True,
    'invalid_destinations_remain_absent':True,'nested_mutations_do_not_persist':True,
    'schema_cases':schema_cases,'open_parameters':open_parameters,
    'explicit_quiescence':json_value(quiescence),
    'corrupt_quiescence':json_value(prepared),'sidecars_after':[],
    'corrupt_store':str(corrupt),'corruption':{'path':relative,'same_size':True,
    'xor_first_byte':1,'size_bytes':len(original),'before_sha256':digest(original),
    'after_sha256':digest(damaged)},'owned_symlink':link_facts}).decode())
"""


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def tree(root):
    result = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("SDK evidence must contain only regular files and directories")
        raw = path.read_bytes()
        result[str(path.relative_to(root))] = {"sha256": digest(raw), "size_bytes": len(raw)}
    return result


def named_block(raw, marker, language):
    """Extract one explicitly allowlisted trusted-repository fenced recipe."""
    opening = ("<!-- " + marker + " -->").encode()
    closing = ("<!-- /" + marker + " -->").encode()
    if raw.count(opening) != 1 or raw.count(closing) != 1:
        raise ValueError("Documentation recipe requires exactly one pair of named markers")
    start, end = raw.index(opening) + len(opening), raw.index(closing)
    if start >= end:
        raise ValueError("Documentation recipe markers are out of order")
    section = raw[start:end].strip(b" \t\r\n")
    prefix = ("```" + language + "\n").encode()
    if not section.startswith(prefix) or not section.endswith(b"```"):
        raise ValueError("Documentation recipe must contain exactly its declared language fence")
    source = section[len(prefix) : -3]
    if not source.strip() or not source.endswith(b"\n") or b"```" in source:
        raise ValueError("Documentation recipe must be one nonempty complete fenced block")
    source.decode("utf-8", errors="strict")
    return source


def consumer_arguments(template, *, interpreter, consumer, inputs, store, registry):
    """Bind only the frozen README placeholders; never evaluate shell text."""
    expected = [
        "/path/to/venv/bin/python",
        "-I",
        "/absolute/path/development_consumer.py",
        "--input-root",
        "/absolute/path/to/copied-sdk-example",
        "--store",
        "/absolute/path/to/new-owned-store",
        "--registry",
        "/absolute/path/to/new-owned-registry",
    ]
    parsed = shlex.split(template.decode("utf-8").replace("\\\n", ""))
    if parsed != expected:
        raise ValueError("README consumer invocation has unsupported placeholders or flags")
    replacements = {
        expected[0]: interpreter,
        expected[2]: str(consumer),
        expected[4]: str(inputs),
        expected[6]: str(store),
        expected[8]: str(registry),
    }
    return parsed, [replacements.get(token, token) for token in parsed]


class Supervisor:
    def __init__(self, interpreter, root):
        self.interpreter, self.root = interpreter, root
        self.started, self.calls = time.monotonic(), 0
        self.cwd = root / "unrelated-cwd"
        self.cwd.mkdir()
        self.transcripts, self.guards = root / "transcripts", root / "guards"
        self.transcripts.mkdir()
        self.guards.mkdir()

    def remaining(self):
        return 180 - (time.monotonic() - self.started)

    def invoke(self, body, arguments=(), *, expected=0, error_stream=False, parse_json=True):
        remaining = self.remaining()
        # Leave four admissions for downstream typing on the SAME host deadline.
        if self.calls >= 28 or remaining <= 0:
            raise TimeoutError("Frozen SDK qualification admission budget exhausted")
        self.calls += 1
        number = f"{self.calls:04d}"
        guard_path = self.guards / (number + ".json")
        allowance = min(30, remaining)
        admitted = time.monotonic()
        code = _BASE + body
        argv = [self.interpreter, "-I", "-B", "-c", code, str(guard_path), *arguments]
        process = subprocess.Popen(
            argv, cwd=self.cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        record = {
            "executable": self.interpreter,
            "argv": argv,
            "entry": ["-c", code],
            "command": list(arguments),
            "cwd": str(self.cwd),
            "pid": process.pid,
            "expected_exit_code": expected,
            "allowance_seconds": allowance,
            "admitted_monotonic_seconds": admitted,
            "wait_deadline_monotonic_seconds": min(admitted + 30, self.started + 180),
            "error_stream": error_stream,
            "parse_json": parse_json,
        }
        cleanup_started = None
        timed_out = False
        timeout = min(allowance - (time.monotonic() - admitted), self.remaining())
        record["wait_timeout_seconds"] = max(0, timeout)
        try:
            if timeout <= 0:
                raise subprocess.TimeoutExpired(argv, max(0, timeout))
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out, cleanup_started = True, time.monotonic()
            with suppress(ProcessLookupError):
                process.kill()
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired as error:
                stdout = error.stdout or b""
                stderr = error.stderr or b""
                stdout = stdout.decode(errors="replace") if isinstance(stdout, bytes) else stdout
                stderr = stderr.decode(errors="replace") if isinstance(stderr, bytes) else stderr
                record["cleanup_reap_confirmed"] = False
            else:
                record["cleanup_reap_confirmed"] = True
        record.update(
            stdout=stdout,
            stderr=stderr,
            exit_code=process.returncode,
            timed_out=timed_out,
            cleanup_elapsed_seconds=None
            if cleanup_started is None
            else time.monotonic() - cleanup_started,
        )
        (self.transcripts / (number + ".json")).write_bytes(canonical(record))
        if timed_out:
            raise TimeoutError("SDK child exceeded its frozen admission/wait budget")
        assert process.returncode == expected, record
        selected, other = (stderr, stdout) if error_stream else (stdout, stderr)
        assert selected and not other, record
        captured = json.loads(guard_path.read_bytes())
        assert captured["guard"]["forbidden_attempts"] == []
        assert captured["guard"]["native_import_attempts"] == captured["native_modules"] == []
        assert captured["guarded_before_sdk_import"] is True
        return (json.loads(selected) if parse_json else selected), number


def main():
    parser = argparse.ArgumentParser()
    for name in (
        "python",
        "report",
        "records-dir",
        "source-records",
        "retention-records",
        "fault-records",
    ):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    sources = (args.source_records, args.retention_records, args.fault_records)
    for source in sources:
        if source.is_symlink() or not source.is_dir():
            raise ValueError("Prior evidence must be existing non-symlink directories")
        if not (source / "artifact-files.json").is_file():
            raise ValueError("Prior evidence requires its complete file manifest")
    sources = tuple(path.resolve() for path in sources)
    for destination in (args.report, args.records_dir):
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("SDK evidence destinations must be new")
        resolved = destination.resolve()
        if any(
            resolved.is_relative_to(source) or source.is_relative_to(resolved) for source in sources
        ):
            raise ValueError("SDK output must be disjoint from prior evidence")
    if args.report.resolve().is_relative_to(
        args.records_dir.resolve()
    ) or args.records_dir.resolve().is_relative_to(args.report.resolve()):
        raise ValueError("SDK outer report must be separate from records")
    interpreter = str(args.python.parent.resolve() / args.python.name)
    project_root = Path(__file__).resolve().parents[1]
    example_root = project_root / "examples" / "sdk"
    project = tomllib.loads((project_root / "pyproject.toml").read_text())
    roles = ("controls", "retention", "faults")
    with TemporaryDirectory(prefix="tickwitness-sdk-") as temporary:
        root = Path(temporary)
        supervisor = Supervisor(interpreter, root)
        before = dict(zip(roles, (tree(source) for source in sources), strict=True))
        observations = {}
        try:
            kinds = (
                ("job-controls-smoke", "installed_job_controls_acceptance_v1"),
                ("dataset-retention-smoke", "installed_dataset_retention_acceptance_v1"),
                ("dataset-faults-smoke", "installed_dataset_fault_budget_acceptance_v1"),
            )
            core_only_profile = None
            for role, source, (directory, kind) in zip(roles, sources, kinds, strict=True):
                listed = json.loads((source / "artifact-files.json").read_bytes())
                actual = {
                    name: value["sha256"]
                    for name, value in before[role].items()
                    if name != "artifact-files.json"
                }
                assert listed == actual
                accepted = json.loads((source / directory / "report.json").read_bytes())
                assert accepted["kind"] == kind and accepted["accepted"] is True
                if role == "controls":
                    core_only_profile = accepted["core_only_profile"]
            assert type(core_only_profile) is bool
            identity, identity_call = supervisor.invoke(_IDENTITY)
            assert identity["executable"] == interpreter
            assert identity["project_version"] == project["project"]["version"]
            assert identity["native_distribution"] is None
            copied = root / "consumer"
            shutil.copytree(example_root, copied)
            assert tree(copied) == tree(example_root)
            inputs = root / "inputs"
            inputs.mkdir()
            for name in ("development.jsonl", "confirmation.jsonl", "request.json", "strategy.py"):
                shutil.copyfile(copied / name, inputs / name)
            consumer = copied / "development_consumer.py"
            readme = (copied / "README.md").read_bytes()
            invocation = named_block(readme, "sdk-consumer-invocation:v1", "sh")
            parsed, logical_argv = consumer_arguments(
                invocation,
                interpreter=interpreter,
                consumer=consumer,
                inputs=inputs,
                store=root / "sdk-store",
                registry=root / "sdk-registry",
            )
            sdk, consumer_call = supervisor.invoke(
                _CONSUMER,
                tuple(logical_argv[2:]),
            )
            (root / "sdk-output.json").write_bytes(canonical(sdk))
            observations["identity"] = {"runtime": identity, "transcript": identity_call}
            observations["consumer"] = {
                "source": consumer.read_text(),
                "sha256": digest(consumer.read_bytes()),
                "transcript": consumer_call,
                "output": sdk,
            }
            consumer_transcript = json.loads(
                (supervisor.transcripts / (consumer_call + ".json")).read_bytes()
            )
            observations["consumer_invocation"] = {
                "readme_source": readme.decode("utf-8"),
                "readme_sha256": digest(readme),
                "marker": "sdk-consumer-invocation:v1",
                "template_source": invocation.decode("utf-8"),
                "template_sha256": digest(invocation),
                "parsed_template_argv": parsed,
                "bound_logical_argv": logical_argv,
                "actual_guarded_argv": consumer_transcript["argv"],
                "actual_transcript": consumer_call,
                "verbatim_shell_executed": False,
            }
            guide = (project_root / "docs" / "python-sdk.md").read_bytes()
            recipe = named_block(guide, "sdk-example:import-and-inspect:v1", "python")
            documentation = root / "documentation"
            documentation.mkdir()
            (documentation / "python-sdk.md").write_bytes(guide)
            recipe_entry = documentation / "import_and_inspect.py"
            recipe_entry.write_bytes(recipe)
            documentation_store = documentation / "store"
            documentation_registry = documentation / "registry"
            documentation_inputs_before = tree(inputs)
            documented, documentation_call = supervisor.invoke(
                _DOCUMENTATION,
                (
                    str(recipe_entry),
                    str(inputs),
                    str(documentation_store),
                    str(documentation_registry),
                ),
            )
            assert documented["receipt"] == sdk["dataset_inspected"]
            assert documented["repeated_receipt"] == documented["persisted_receipt"]
            assert documented["source_sha256"] == digest(recipe)
            assert documented["input_sha256"] == digest((inputs / "development.jsonl").read_bytes())
            assert documented["registry_created"] is False and not documentation_registry.exists()
            assert tree(inputs) == documentation_inputs_before
            observations["documentation_example"] = {
                "guide_path": "docs/python-sdk.md",
                "guide_source": guide.decode("utf-8"),
                "guide_sha256": digest(guide),
                "guide_copy": str(documentation / "python-sdk.md"),
                "marker": "sdk-example:import-and-inspect:v1",
                "source": recipe.decode("utf-8"),
                "source_sha256": digest(recipe),
                "source_file": str(recipe_entry),
                "transcript": documentation_call,
                "result": documented,
                "persistent_files": tree(documentation_store),
                "input_files_before": documentation_inputs_before,
                "input_files_after": tree(inputs),
            }
            cli_store, cli_registry = root / "cli-store", root / "cli-registry"
            calls = {}

            def cli(name, *command, expected=0, parse_json=True):
                payload, call = supervisor.invoke(
                    _CLI,
                    command,
                    expected=expected,
                    error_stream=expected != 0,
                    parse_json=parse_json,
                )
                calls[name] = {"transcript": call, "response": payload, "exit_code": expected}
                return payload

            def imported(name, filename="development.jsonl", store=cli_store):
                return cli(
                    name,
                    "import-events",
                    filename,
                    "--input-root",
                    str(inputs),
                    "--store",
                    str(store),
                )

            healthy = {}
            healthy["dataset_first"] = imported("dataset_first")
            healthy["confirmation_first"] = imported("confirmation_first", "confirmation.jsonl")
            healthy["dataset_repeated"] = imported("dataset_repeated")
            dataset_id = healthy["dataset_first"]["dataset_id"]
            confirmation_id = healthy["confirmation_first"]["dataset_id"]
            healthy["dataset_inspected"] = cli(
                "dataset_inspected", "inspect-dataset", dataset_id, "--store", str(cli_store)
            )
            freeze = (
                "freeze-protocol",
                "request.json",
                "--input-root",
                str(inputs),
                "--strategy-source",
                "strategy.py",
                "--development-dataset",
                dataset_id,
                "--confirmation-dataset",
                confirmation_id,
                "--store",
                str(cli_store),
                "--registry",
                str(cli_registry),
            )
            healthy["protocol_first"] = cli("protocol_first", *freeze)
            healthy["protocol_repeated"] = cli("protocol_repeated", *freeze)
            protocol_id = healthy["protocol_first"]["protocol_id"]
            healthy["protocol_inspected"] = cli(
                "protocol_inspected",
                "inspect-protocol",
                protocol_id,
                "--store",
                str(cli_store),
                "--registry",
                str(cli_registry),
            )
            read = (
                "read-protocol-data",
                protocol_id,
                "--store",
                str(cli_store),
                "--registry",
                str(cli_registry),
            )
            healthy["development"] = cli("development", *read, "--limit", "1")
            healthy["quiescence"] = imported("quiescence")
            for name, value in healthy.items():
                assert value == sdk[name], name
            assert healthy["dataset_first"]["created"] is True
            assert healthy["dataset_repeated"]["created"] is False
            assert healthy["protocol_first"]["created"] is True
            assert healthy["protocol_repeated"]["created"] is False
            assert healthy["dataset_inspected"]["report"]["unknown_receive_count"] == 1
            assert healthy["dataset_inspected"]["report"]["replay_certified"] is False
            assert healthy["protocol_inspected"]["document"]["budget"]["max_events"] == 2
            assert healthy["protocol_inspected"]["document"]["claim"]["threshold"] == "0"
            assert healthy["protocol_inspected"]["document"]["execution_ready"] is False
            assert sdk["summary"] == {
                "kind": "development_capture_summary_v1",
                "protocol_id": protocol_id,
                "dataset_id": dataset_id,
                "observed_records": 1,
                "total_records": 2,
                "truncated": True,
                "capture_sequences": [1],
                "unknown_receive_times": 1,
                "research_claim_evaluated": False,
            }
            assert healthy["development"]["observations"][0]["receive_time_ns"] is None
            negative, negative_call = supervisor.invoke(
                _NEGATIVES, (str(root), str(inputs), str(root / "sdk-output.json"))
            )
            observations["sdk_negatives"] = {"result": negative, "transcript": negative_call}
            open_parameters = negative["open_parameters"]
            observations["compatibility"] = {
                "contract": "sdk-compatibility-v1",
                "sdk_schema_cases": negative["schema_cases"],
                "open_parameters": open_parameters,
                "open_parameter_store_files": tree(Path(open_parameters["store"])),
                "open_parameter_registry_files": tree(Path(open_parameters["registry"])),
                "unknown_receive_time_preserved": (
                    open_parameters["development"]["observations"][0]["receive_time_ns"] is None
                ),
            }
            negatives = root / "negatives"
            invalid_store = negatives / "cli-invalid-store"
            errors = {}
            errors["invalid_data"] = cli(
                "invalid_data",
                "import-events",
                "invalid.jsonl",
                "--input-root",
                str(inputs),
                "--store",
                str(invalid_store),
                expected=2,
            )
            errors["invalid_strategy"] = cli(
                "invalid_strategy",
                "freeze-protocol",
                "request.json",
                "--input-root",
                str(inputs),
                "--strategy-source",
                "invalid_strategy.py",
                "--development-dataset",
                dataset_id,
                "--confirmation-dataset",
                confirmation_id,
                "--store",
                str(cli_store),
                "--registry",
                str(negatives / "cli-invalid-registry"),
                expected=2,
            )
            absent = root / "must-remain-absent-cli"
            errors["confirmation"] = cli(
                "confirmation",
                "read-protocol-data",
                protocol_id,
                "--split",
                "confirmation",
                "--limit",
                "1",
                "--store",
                str(absent / "store"),
                "--registry",
                str(absent / "registry"),
                expected=5,
            )
            errors["frozen_limit"] = cli("frozen_limit", *read, "--limit", "3", expected=2)
            errors["missing_dataset"] = cli(
                "missing_dataset",
                "inspect-dataset",
                "0" * 64,
                "--store",
                str(cli_store),
                expected=4,
            )
            errors["missing_protocol"] = cli(
                "missing_protocol",
                "inspect-protocol",
                "0" * 64,
                "--store",
                str(cli_store),
                "--registry",
                str(cli_registry),
                expected=4,
            )
            unsafe_inputs = (("symlink", "linked.jsonl"), ("traversal", "../development.jsonl"))
            for name, filename in unsafe_inputs:
                errors[name] = cli(
                    name,
                    "import-events",
                    filename,
                    "--input-root",
                    str(inputs),
                    "--store",
                    str(invalid_store),
                    expected=2,
                )
            corrupt_store = Path(negative["corrupt_store"])
            errors["corrupt_object"] = cli(
                "corrupt_object",
                "inspect-dataset",
                dataset_id,
                "--store",
                str(corrupt_store),
                expected=3,
            )
            errors["unknown_event"] = cli(
                "unknown_event",
                "import-events",
                "unknown-event.jsonl",
                "--input-root",
                str(inputs),
                "--store",
                str(invalid_store),
                expected=2,
            )
            unknown_budget_registry = negatives / "cli-unknown-budget-registry"
            errors["unknown_budget"] = cli(
                "unknown_budget",
                "freeze-protocol",
                "unknown-budget.json",
                "--input-root",
                str(inputs),
                "--strategy-source",
                "strategy.py",
                "--development-dataset",
                dataset_id,
                "--confirmation-dataset",
                confirmation_id,
                "--store",
                str(cli_store),
                "--registry",
                str(unknown_budget_registry),
                expected=2,
            )
            assert not unknown_budget_registry.exists()
            observations["compatibility"]["additional_cli_refusals"] = {
                name: calls[name] for name in ("unknown_event", "unknown_budget")
            }
            observations["compatibility"]["cli_unknown_destinations"] = {
                "store": str(invalid_store),
                "registry": str(unknown_budget_registry),
                "store_created": invalid_store.exists(),
                "registry_created": unknown_budget_registry.exists(),
            }
            for name, envelope in errors.items():
                assert envelope == negative["outcomes"][name]["response"], name
                assert calls[name]["exit_code"] == negative["outcomes"][name]["exit_code"]
            malformed = cli(
                "malformed_identity",
                "inspect-dataset",
                "not-an-identity",
                "--store",
                str(cli_store),
                expected=2,
                parse_json=False,
            )
            assert "dataset_id must be a lowercase SHA-256 digest" in malformed
            assert "usage:" in malformed
            assert not invalid_store.exists() and not absent.exists()
            assert not (negatives / "cli-invalid-registry").exists()
            assert imported("cli_final_quiescence") == sdk["quiescence"]
            prepared = imported("corrupt_final_quiescence", "confirmation.jsonl", corrupt_store)
            assert prepared == negative["corrupt_quiescence"]
            for store in (root / "sdk-store", cli_store, corrupt_store):
                sidecar_names = (
                    "catalog.sqlite3-wal",
                    "catalog.sqlite3-shm",
                    "catalog.sqlite3-journal",
                )
                assert not any((store / name).exists() for name in sidecar_names)
            shutil.copytree(cli_store, root / "images" / "cli-final")
            shutil.copytree(cli_registry, root / "images" / "cli-registry-final")
            shutil.copytree(corrupt_store, root / "images" / "corrupt-final")
            assert (
                digest((corrupt_store / negative["corruption"]["path"]).read_bytes())
                == (negative["corruption"]["after_sha256"])
            )
            link = inputs / "linked.jsonl"
            assert link.is_symlink() and os.readlink(link) == negative["owned_symlink"]["target"]
            link.unlink()
            observations["cli"] = calls
            observations["healthy_equal_fields"] = list(healthy)
            observations["negative_equal_fields"] = list(errors)
            observations["symlink_fixture_teardown"] = {"only_owned_link_removed": True}
            after = dict(zip(roles, (tree(source) for source in sources), strict=True))
            assert before == after
            elapsed = time.monotonic() - supervisor.started
            assert supervisor.calls == 27 and supervisor.calls <= 28 and elapsed <= 180
            report = {
                "kind": "installed_python_sdk_consumer_acceptance_v1",
                "schema_version": 1,
                "accepted": True,
                "interpreter_identity": identity,
                "budget": {
                    "max_child_invocations": 32,
                    "max_child_seconds": 30,
                    "max_supervisor_seconds": 180,
                    "child_invocations": supervisor.calls,
                    "actual_children": supervisor.calls,
                    "functional_max_child_invocations": 28,
                    "reserved_typing_child_invocations": 4,
                    "planned_functional_child_invocations": 27,
                    "remaining_functional_child_admissions": 28 - supervisor.calls,
                    "remaining_total_child_admissions": 32 - supervisor.calls,
                    "started_monotonic_seconds": supervisor.started,
                    "deadline_monotonic_seconds": supervisor.started + 180,
                    "elapsed_seconds": elapsed,
                    "cleanup_latency_included_in_hard_limit": False,
                },
                "observations": observations,
                "protected_sources_before": before,
                "protected_sources_after": after,
                "example_files": tree(copied),
                "source_driver_sha256": digest(Path(__file__).read_bytes()),
                "scope": {
                    "fixture_only": True,
                    "new_native_calls": 0,
                    "new_research_slots": 0,
                    "sdk_execution_supported": False,
                    "sdk_confirmation_exposure_supported": False,
                    "original_protocol_budgets_unchanged": True,
                    "budget_reset_or_refund": False,
                    "source_controls_core_only": core_only_profile,
                    "external_human_attempts": 0,
                    "external_human_successes": 0,
                    "external_human_gate": "PENDING",
                    "research_claim_evaluated": False,
                },
            }
            inner = root / "sdk-consumer-smoke" / "report.json"
            inner.parent.mkdir()
            inner.write_bytes(canonical(report))
            shutil.copytree(root, args.records_dir)
            manifest = canonical(tree(args.records_dir))
            (args.records_dir / "artifact-files.json").write_bytes(manifest)
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_bytes(canonical(report))
        except BaseException as error:
            with suppress(OSError, ValueError):
                link = root / "inputs" / "linked.jsonl"
                if link.is_symlink():
                    facts = {
                        "path": str(link),
                        "target": os.readlink(link),
                        "only_owned_link_removed_after_failure": True,
                    }
                    (root / "failure-owned-link.json").write_bytes(canonical(facts))
                    link.unlink()
                failure = {
                    "kind": "installed_python_sdk_consumer_acceptance_v1",
                    "schema_version": 1,
                    "accepted": False,
                    "message": str(error)[:4096],
                    "completed_observations": list(observations),
                    "child_invocations": supervisor.calls,
                    "budget": {
                        "actual_children": supervisor.calls,
                        "started_monotonic_seconds": supervisor.started,
                        "deadline_monotonic_seconds": supervisor.started + 180,
                        "max_child_invocations": 32,
                        "functional_max_child_invocations": 28,
                        "reserved_typing_child_invocations": 4,
                    },
                    "elapsed_seconds": time.monotonic() - supervisor.started,
                }
                if not args.records_dir.exists():
                    shutil.copytree(root, args.records_dir)
                (args.records_dir / "qualification-failure.json").write_bytes(canonical(failure))
                inventory = {
                    name: value
                    for name, value in tree(args.records_dir).items()
                    if name != "artifact-files.json"
                }
                (args.records_dir / "artifact-files.json").write_bytes(canonical(inventory))
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_bytes(canonical(failure))
            raise


if __name__ == "__main__":
    main()
