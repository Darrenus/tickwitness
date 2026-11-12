#!/usr/bin/env python3
"""Exercise a finite installed-core storage fault budget, never research execution."""

import argparse
import hashlib
import json
import shutil
import subprocess
import time
import tomllib
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory

_CASES = ("P01", "P02", "P03", "R01", "R02", "L01", "M01", "M02")
_BASE = r'''
import errno,fcntl,hashlib,importlib.abc,io,json,os,shutil,socket,sqlite3,stat,sys,time
from importlib import metadata
from pathlib import Path
try:metadata.version('nautilus_trader')
except metadata.PackageNotFoundError:pass
else:raise AssertionError('Fault qualification requires an independent core-only wheel')
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith('nautilus_trader'):raise AssertionError('No native execution')
sys.meta_path.insert(0,NoNative())
from tickwitness.infrastructure.local_dataset_store import LocalDatasetStore,DatasetStoreError
from tickwitness.infrastructure.dataset_retention import LocalDatasetMaintenance
from tickwitness.infrastructure.attempt_ledger import LocalAttemptLedger
from tickwitness.infrastructure.bounded_replay import BoundedReplayAdapter
from tickwitness.infrastructure.subprocess_replay import SubprocessReplayAdapter
def forbidden(*args,**kwargs):raise AssertionError('No research or network authority')
BoundedReplayAdapter.__init__=forbidden;SubprocessReplayAdapter.__init__=forbidden
for name in ('reserve','reserve_with_nonce','bind_intent','publish'):
    setattr(LocalAttemptLedger,name,forbidden)
socket.socket=forbidden;socket.create_connection=forbidden
import subprocess
subprocess.Popen=forbidden
def document(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,
                      allow_nan=False).encode()
def digest(raw):return hashlib.sha256(raw).hexdigest()
def emit(value):print(document(value).decode())
def inputs(case,role):
    return ((case+' '+role+' raw fixture').encode(),(case+' '+role+' normalized').encode(),
            {'case':case,'role':role,'fixture_only':True})
def publish(owner,case,role):return owner.publish(*inputs(case,role))
def readback(owner,identity):
    record=owner.get(identity)
    return {'dataset_id':record.dataset_id,'manifest':record.manifest,
            'objects':{role:digest(raw) for role,raw in owner.read_artifacts(identity).items()}}
def quiesce(root,case):
    names=('catalog.sqlite3-wal','catalog.sqlite3-shm','catalog.sqlite3-journal')
    before=[name for name in names if (root/name).exists()]
    record=publish(LocalDatasetStore(root),case,'healthy')
    assert record.created is False
    after=[name for name in names if (root/name).exists()]
    assert after==[]
    return {'ordinary_validated_rw_initialization':True,'idempotent_healthy_publication':True,
            'created':False,'sidecars_before':before,'sidecars_after':after}
def tree(root):
    result={}
    for path in sorted(root.rglob('*')):
        assert not path.is_symlink()
        if path.is_file():result[str(path.relative_to(root))]=digest(path.read_bytes())
    return result
def image(case_root,name,root,*,catalog=True):
    files=tree(root);facts={}
    for relative in files:
        info=(root/relative).stat()
        facts[relative]={'device':info.st_dev,'inode':info.st_ino,'size_bytes':info.st_size,
            'mtime_ns':info.st_mtime_ns,'ctime_ns':info.st_ctime_ns,'nlink':info.st_nlink}
    rows=None
    if catalog:
        assert not any((root/('catalog.sqlite3'+suffix)).exists()
                       for suffix in ('-wal','-shm','-journal'))
        connection=sqlite3.connect((root/'catalog.sqlite3').as_uri()+'?mode=ro&immutable=1',
                                  uri=True)
        try:rows=connection.execute('SELECT dataset_id,manifest_sha256,sealed FROM datasets '
                                    'ORDER BY dataset_id').fetchall()
        finally:connection.close()
    destination=case_root/'images'/name
    destination.parent.mkdir(exist_ok=True)
    shutil.copytree(root,destination)
    return {'image':str(destination.relative_to(case_root)),'files':files,'facts':facts,
            'catalog_rows':rows,'catalog_inspected_as_closed_immutable':catalog}
def error_chain(error):
    result=[]
    while error is not None:
        result.append({'type':type(error).__name__,'message':str(error),
                       'errno':getattr(error,'errno',None)})
        error=error.__cause__
    return result
def protected(root):
    return sorted({ref['sha256'] for path in (root/'manifests').glob('*.json')
                   for ref in json.loads(path.read_bytes())['objects'].values()})
def baseline(case_root,case):
    root=case_root/'store';owner=LocalDatasetStore(root)
    record=publish(owner,case,'healthy')
    return root,owner,record.dataset_id
'''
_IDENTITY = r'''
emit({'executable':sys.executable,'prefix':sys.prefix,'base_prefix':sys.base_prefix,
      'effective_uid':os.geteuid(),'project_version':metadata.version('tickwitness'),
      'native_distribution':None})
'''
_SDK = r'''
case,phase,location=sys.argv[1:4];case_root=Path(location)
if phase=='publish':
    root,owner,healthy=baseline(case_root,case)
    before=image(case_root,'before',root);hits=[];original_mode=None
    actual_open=os.open;actual_fdopen=os.fdopen;tracked=set()
    objects=root/'objects'/'sha256';identity=os.stat(objects)
    def selected(dir_fd):
        if dir_fd is None:return False
        value=os.fstat(dir_fd)
        return (value.st_dev,value.st_ino)==(identity.st_dev,identity.st_ino)
    def opened(path,flags,mode=0o777,*,dir_fd=None):
        match=selected(dir_fd) and os.fsdecode(path).startswith('.pending-')
        try:descriptor=actual_open(path,flags,mode,dir_fd=dir_fd)
        except OSError as error:
            if match:hits.append({'operation':'pending_create','errno':error.errno,
                'effective_uid':os.geteuid(),'mode':stat.S_IMODE(os.stat(objects).st_mode),
                'origin':'actual_kernel'})
            raise
        if match and flags&os.O_CREAT:tracked.add(descriptor)
        return descriptor
    class Partial:
        def __init__(self,stream):self.stream=stream
        def __enter__(self):self.stream.__enter__();return self
        def __exit__(self,*args):return self.stream.__exit__(*args)
        def __getattr__(self,name):return getattr(self.stream,name)
        def write(self,data):
            count=max(1,len(data)//2);assert count<len(data)
            written=self.stream.write(data[:count]);self.stream.flush()
            assert written==count and os.fstat(self.stream.fileno()).st_size==count
            hits.append({'operation':'pending_write','requested':len(data),'written':written,
                         'pending_size':os.fstat(self.stream.fileno()).st_size,
                         'origin':'injected_boundary',
                         'injected_errno':errno.ENOSPC if case=='P01' else None})
            if case=='P01':raise OSError(errno.ENOSPC,'Declared pending-prefix ENOSPC')
            return written
    def fdopen(descriptor,*args,**kwargs):
        stream=actual_fdopen(descriptor,*args,**kwargs)
        return Partial(stream) if descriptor in tracked else stream
    os.open=opened
    if actual_open in os.supports_dir_fd:os.supports_dir_fd=os.supports_dir_fd|{opened}
    if case in ('P01','P02'):os.fdopen=fdopen
    if case=='P03':
        assert os.geteuid()!=0
        original_mode=stat.S_IMODE(objects.stat().st_mode);assert original_mode==0o700
        os.chmod(objects,0o500)
    try:
        try:publish(owner,case,'target')
        except DatasetStoreError as error:failure=error_chain(error)
        else:raise AssertionError('Fault publication unexpectedly returned success')
    finally:
        os.open=actual_open;os.fdopen=actual_fdopen
        if original_mode is not None:os.chmod(objects,original_mode)
    expected={'P01':errno.ENOSPC,'P02':errno.EIO,'P03':errno.EACCES}[case]
    assert any(item['errno']==expected for item in failure) and len(hits)==1
    if case=='P03':assert hits[0]['errno']==errno.EACCES and hits[0]['mode']==0o500
    failed=image(case_root,'failed',root)
    assert before['files']==failed['files'] and before['catalog_rows']==failed['catalog_rows']
    assert not any(path.name.startswith('.pending-') for path in objects.iterdir())
    baseline_read=readback(owner,healthy)
    preparation=quiesce(root,case)
    recovered=publish(owner,case,'target');assert recovered.created is True
    repeated=publish(owner,case,'target');assert repeated.created is False
    assert recovered.dataset_id==repeated.dataset_id
    target_read=readback(owner,recovered.dataset_id)
    assert readback(owner,healthy)==baseline_read
    closing=quiesce(root,case)
    after=image(case_root,'recovered',root)
    emit({'case_id':case,'fault_origin':'actual_kernel' if case=='P03' else 'injected_boundary',
          'product_outcome':{'published':False,'exception_chain':failure},'injection_hits':hits,
          'permission_restoration':None if original_mode is None else
              {'original_mode':original_mode,'restored_mode':stat.S_IMODE(objects.stat().st_mode)},
          'before':before,'failed':failed,'recovered':after,'baseline_read':baseline_read,
          'recovery':{'created':recovered.created,'repeat_created':repeated.created,
                      'readback':target_read},'ordinary_preparations':[preparation,closing]})
elif phase=='damage':
    root,owner,healthy=baseline(case_root,case)
    target=publish(owner,case,'target');before=image(case_root,'before',root)
    reference=target.manifest['objects']['raw'];path=root/reference['ref']
    raw=path.read_bytes();assert digest(raw)==reference['sha256']
    if case=='R01':path.write_bytes(bytes([raw[0]^1])+raw[1:])
    else:path.unlink()
    try:owner.get(target.dataset_id)
    except DatasetStoreError as error:failure=error_chain(error)
    else:raise AssertionError('Damaged dataset returned a successful read')
    preparation=quiesce(root,case)
    failed=image(case_root,'failed',root)
    emit({'case_id':case,'fault_origin':'declared_fixture_data_fault','healthy':healthy,
          'target':target.dataset_id,'damaged_object':reference['sha256'],
          'protected':protected(root),'product_outcome':{'read_success':False,
          'exception_chain':failure},'before':before,'failed':failed,
          'ordinary_preparations':[preparation]})
elif phase=='prepare':
    root=case_root/'store';preparation=quiesce(root,case)
    emit({'case_id':case,'ordinary_preparation':preparation,
          'before_gc':image(case_root,'before-gc',root)})
elif phase=='replace':
    root=case_root/'store';original_before=tree(root)
    replacement=case_root/'replacement';owner=LocalDatasetStore(replacement)
    healthy=publish(owner,case,'healthy');target=publish(owner,case,'target')
    target_read=readback(owner,target.dataset_id);baseline_read=readback(owner,healthy.dataset_id)
    preparation=quiesce(replacement,case)
    assert tree(root)==original_before
    emit({'case_id':case,'recovery':{'new_store':True,'created':target.created,
          'dataset_id':target.dataset_id,'readback':target_read,'baseline_read':baseline_read},
          'ordinary_preparation':preparation,'original_preserved':image(case_root,'preserved',root),
          'replacement':image(case_root,'replacement',replacement)})
elif phase=='orphans':
    root,owner,healthy=baseline(case_root,case);orphans=[];actual=owner._publish_file
    for raw in ((case+' first orphan').encode(),(case+' second longer orphan bytes').encode()):
        expected=digest(raw)
        def interrupted(directory,name,data):
            actual(directory,name,data)
            if name==expected:raise OSError(errno.EIO,'Declared first durable CAS interruption')
        owner._publish_file=interrupted
        try:
            try:owner.publish(raw,b'not installed',{'fixture':'not installed'})
            except DatasetStoreError:pass
            else:raise AssertionError('Orphan interruption did not occur')
        finally:owner._publish_file=actual
        assert (root/'objects'/'sha256'/expected).read_bytes()==raw
        orphans.append(expected)
    emit({'case_id':case,'healthy':healthy,'protected':protected(root),
          'orphans':sorted(orphans),'before':image(case_root,'before',root)})
elif phase=='verify':
    root=case_root/'store';owner=LocalDatasetStore(root,create=False)
    healthy=publish(owner,case,'healthy');assert healthy.created is False
    read=readback(owner,healthy.dataset_id);preparation=quiesce(root,case)
    emit({'case_id':case,'baseline_read':read,'ordinary_preparation':preparation,
          'recovered':image(case_root,'recovered',root)})
else:raise AssertionError('Unknown finite fixture phase')
'''
_INSPECT = r'''
from tickwitness.cli import main
raise SystemExit(main(sys.argv[1:]))
'''
_HOLDER = r'''
case_root=Path(sys.argv[1]);controls=case_root/'controls';controls.mkdir()
root,owner,healthy=baseline(case_root,'L01');before=image(case_root,'before',root)
descriptor=os.open(root,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
fcntl.flock(descriptor,fcntl.LOCK_EX|fcntl.LOCK_NB);info=os.fstat(descriptor)
ready={'pid':os.getpid(),'device':info.st_dev,'inode':info.st_ino,'lock':'EX',
       'healthy':healthy,'protected':protected(root),'before':before}
(controls/'ready.pending').write_bytes(document(ready))
os.replace(controls/'ready.pending',controls/'ready.json')
try:
    deadline=time.monotonic()+25
    while not (controls/'release').exists() and time.monotonic()<deadline:time.sleep(0.01)
    assert (controls/'release').exists(),'Explicit holder release did not arrive'
finally:fcntl.flock(descriptor,fcntl.LOCK_UN);os.close(descriptor)
plan=LocalDatasetMaintenance(root).plan(0);assert plan.document['status']=='READY'
read=readback(owner,healthy);preparation=quiesce(root,'L01')
emit({'case_id':'L01','ready':ready,'released':True,'pid':os.getpid(),
      'recovery':{'plan':plan.document,'plan_id':plan.plan_id,'baseline_read':read},
      'ordinary_preparation':preparation,'recovered':image(case_root,'recovered',root)})
'''
_GC_CLI = r'''
import builtins
from urllib.parse import parse_qs,unquote,urlsplit
from tickwitness.cli import main
target=Path(sys.argv.pop(1)).resolve();rules=json.loads(sys.argv.pop(1))
log=Path(sys.argv.pop(1));fault=sys.argv.pop(1);command=sys.argv[1]
assert command in ('plan-dataset-retention','apply-dataset-retention')
assert Path(sys.argv[sys.argv.index('--store')+1]).resolve()==target
protected_ids=set(rules['protected']);allowed=set(rules['orphans'])
intended=rules['intended'];objects=target/'objects'/'sha256';object_info=objects.stat()
directories={}
for path in (target,target/'objects',objects,target/'manifests'):
    info=path.stat();directories[(info.st_dev,info.st_ino)]=path
events={'orphan_opens':[],'unlink_attempts':[],'unlinked':[],'sqlite_uris':[],
        'sql':[],'fsync_attempts':[],'fsync_directories':[],
        'retained_payload_reads':0,'metadata_write_attempts':0,'injection_hits':[]}
actual_open=os.open;actual_io=io.open;actual_builtin=builtins.open
actual_unlink=os.unlink;actual_fsync=os.fsync;actual_connect=sqlite3.connect
LocalDatasetStore.__init__=forbidden;LocalDatasetStore.publish=forbidden
def object_name(path,dir_fd=None):
    if isinstance(path,int):return None
    value=Path(os.fsdecode(path))
    if dir_fd is not None:
        info=os.fstat(dir_fd);parent=directories.get((info.st_dev,info.st_ino))
        if parent is not None:value=parent/value
    if not value.is_absolute():value=Path.cwd()/value
    return value.name if value.parent.resolve()==objects else None
def check_read(path,dir_fd=None):
    name=object_name(path,dir_fd)
    if name in protected_ids:
        events['retained_payload_reads']+=1;forbidden()
    if name is not None:
        if name not in allowed:forbidden()
        events['orphan_opens'].append(name)
def opened(path,flags,mode=0o777,*,dir_fd=None):
    if flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND|os.O_EXCL):
        events['metadata_write_attempts']+=1;forbidden()
    check_read(path,dir_fd);return actual_open(path,flags,mode,dir_fd=dir_fd)
def io_open(file,mode='r',*args,**kwargs):
    if any(value in mode for value in ('w','a','x','+')):
        events['metadata_write_attempts']+=1;forbidden()
    check_read(file);return actual_io(file,mode,*args,**kwargs)
def builtin_open(file,mode='r',*args,**kwargs):
    if any(value in mode for value in ('w','a','x','+')):
        events['metadata_write_attempts']+=1;forbidden()
    check_read(file);return actual_builtin(file,mode,*args,**kwargs)
def unlink(path,*,dir_fd=None):
    name=object_name(path,dir_fd)
    if command!='apply-dataset-retention' or name not in intended:forbidden()
    events['unlink_attempts'].append(name)
    if fault=='partial' and name==intended[1]:
        events['injection_hits'].append({'operation':'unlink','name':name,'errno':errno.EACCES,
                                        'origin':'injected_boundary'})
        raise PermissionError(errno.EACCES,'Declared second-candidate unlink failure')
    actual_unlink(path,dir_fd=dir_fd);events['unlinked'].append(name)
def fsync(descriptor):
    info=os.fstat(descriptor)
    if not stat.S_ISDIR(info.st_mode):forbidden()
    identity={'device':info.st_dev,'inode':info.st_ino}
    events['fsync_attempts'].append(identity)
    if fault=='fsync' and (info.st_dev,info.st_ino)==(object_info.st_dev,object_info.st_ino):
        events['injection_hits'].append({'operation':'fsync','errno':errno.EIO,
                                        'origin':'injected_boundary',**identity})
        raise OSError(errno.EIO,'Declared objects-directory fsync uncertainty')
    actual_fsync(descriptor);events['fsync_directories'].append(identity)
def connect(database,*args,**kwargs):
    locator=str(database);parsed=urlsplit(locator);query=parse_qs(parsed.query)
    if parsed.scheme!='file' or Path(unquote(parsed.path)).resolve()!=target/'catalog.sqlite3':
        forbidden()
    if query.get('mode')!=['ro'] or query.get('immutable')!=['1'] or not kwargs.get('uri'):
        forbidden()
    events['sqlite_uris'].append(locator);connection=actual_connect(database,*args,**kwargs)
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
                ('trusted_schema','0'),('query_only','1'),('table_info','datasets')):
                return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    connection.set_authorizer(authorize);connection.set_trace_callback(events['sql'].append)
    return connection
os.open=opened;io.open=io_open;builtins.open=builtin_open
if actual_open in os.supports_dir_fd:os.supports_dir_fd=os.supports_dir_fd|{opened}
os.unlink=unlink;os.remove=unlink;os.fsync=fsync;sqlite3.connect=connect
for name in ('mkdir','makedirs','rmdir','rename','replace','link','symlink','truncate',
             'chmod','fchmod','chown','fchown','utime'):setattr(os,name,forbidden)
try:result=main(sys.argv[1:])
finally:
    with actual_io(log,'wb') as stream:stream.write(document(events))
raise SystemExit(result)
'''


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def tree(root):
    files = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise AssertionError("Fault evidence cannot contain symlinks")
        if path.is_file():
            with path.open("rb") as stream:
                hashed = hashlib.file_digest(stream, "sha256").hexdigest()
                files[str(path.relative_to(root))] = hashed
        elif not path.is_dir():
            raise AssertionError("Fault evidence must contain only regular files and directories")
    return files


class Supervisor:
    def __init__(self, interpreter, root):
        self.interpreter, self.root = interpreter, root
        self.started = time.monotonic()
        self.calls = 0
        self.transcripts = root / "transcripts"
        self.transcripts.mkdir()
        self.cwd = root / "unrelated-cwd"
        self.cwd.mkdir()

    def remaining(self):
        return 180 - (time.monotonic() - self.started)

    def start(self, code, arguments=(), *, expected=0, error_stream=False):
        remaining = self.remaining()
        if remaining <= 0 or self.calls >= 32:
            raise TimeoutError("Frozen fault exercise admission budget exhausted")
        self.calls += 1
        allowance = min(30, remaining)
        argv = [self.interpreter, "-I", "-B", "-c", _BASE + code, *arguments]
        process = subprocess.Popen(
            argv, cwd=self.cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        return {
            "process": process,
            "number": f"{self.calls:04d}",
            "deadline": time.monotonic() + allowance,
            "record": {
                "executable": self.interpreter,
                "argv": argv,
                "entry": ["-c", _BASE + code],
                "command": list(arguments),
                "pid": process.pid,
                "allowance_seconds": allowance,
                "expected_exit_code": expected,
                "error_stream": error_stream,
            },
        }

    def finish(self, pending):
        process, record = pending["process"], pending["record"]
        timeout = min(pending["deadline"] - time.monotonic(), self.remaining())
        timed_out = timeout <= 0
        cleanup_started = None
        try:
            if timed_out:
                raise subprocess.TimeoutExpired(record["argv"], max(0, timeout))
            out, err = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            cleanup_started = time.monotonic()
            process.kill()
            try:
                out, err = process.communicate(timeout=5)
            except subprocess.TimeoutExpired as error:
                out, err = str(error.stdout or ""), str(error.stderr or "")
                record["cleanup_reap_confirmed"] = False
            else:
                record["cleanup_reap_confirmed"] = True
        record.update(
            exit_code=process.returncode,
            stdout=out,
            stderr=err,
            timed_out=timed_out,
            cleanup_elapsed_seconds=None
            if cleanup_started is None
            else time.monotonic() - cleanup_started,
        )
        (self.transcripts / (pending["number"] + ".json")).write_bytes(canonical(record))
        if timed_out:
            raise TimeoutError("Child exceeded the frozen admission/wait budget")
        if process.returncode != record["expected_exit_code"]:
            raise AssertionError(f"Unexpected fault helper outcome: {record}")
        selected = err if record["error_stream"] else out
        if (out if record["error_stream"] else err) or not selected:
            raise AssertionError(f"Unexpected fault helper streams: {record}")
        return json.loads(selected), pending["number"]

    def invoke(self, code, arguments=(), **kwargs):
        return self.finish(self.start(code, arguments, **kwargs))


def main():
    parser = argparse.ArgumentParser()
    for name in ("python", "report", "records-dir", "source-records", "retention-records"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    destinations = (args.report, args.records_dir)
    for source in (args.source_records, args.retention_records):
        if source.is_symlink() or not source.is_dir():
            raise ValueError("Prior evidence must be an existing non-symlink directory")
        if not (source / "artifact-files.json").is_file():
            raise ValueError("Prior evidence requires its complete file manifest")
    sources = (args.source_records.resolve(), args.retention_records.resolve())
    for destination in destinations:
        if destination.exists() or destination.is_symlink():
            raise FileExistsError("Fault qualification destinations must be new")
        resolved = destination.resolve()
        if any(
            resolved.is_relative_to(source) or source.is_relative_to(resolved)
            for source in sources
        ):
            raise ValueError("Fault output and prior evidence must be disjoint")
    if (
        args.report.resolve().is_relative_to(args.records_dir.resolve())
        or args.records_dir.resolve().is_relative_to(args.report.resolve())
    ):
        raise ValueError("Outer fault report must be outside its records")
    interpreter = str(args.python.parent.resolve() / args.python.name)
    with TemporaryDirectory(prefix="tickwitness-faults-") as temporary:
        root = Path(temporary)
        supervisor = Supervisor(interpreter, root)
        before = {"controls": tree(sources[0]), "retention": tree(sources[1])}
        observations = []
        try:
            for role, source in zip(("controls", "retention"), sources, strict=True):
                listed = json.loads((source / "artifact-files.json").read_bytes())
                actual = {
                    name: value for name, value in before[role].items()
                    if name != "artifact-files.json"
                }
                assert listed == actual
            source_controls = json.loads(
                (sources[0] / "job-controls-smoke" / "report.json").read_bytes()
            )
            source_retention = json.loads(
                (sources[1] / "dataset-retention-smoke" / "report.json").read_bytes()
            )
            assert source_controls["kind"] == "installed_job_controls_acceptance_v1"
            assert source_retention["kind"] == "installed_dataset_retention_acceptance_v1"
            assert source_controls["accepted"] is source_retention["accepted"] is True
            identity, _ = supervisor.invoke(_IDENTITY)
            project_file = Path(__file__).resolve().parents[1] / "pyproject.toml"
            project = tomllib.loads(project_file.read_text())
            assert identity["executable"] == interpreter
            assert identity["project_version"] == project["project"]["version"]
            assert identity["native_distribution"] is None
            cases_root = root / "cases"
            cases_root.mkdir()
            guards = root / "guards"
            guards.mkdir()
            plans = root / "plans"
            plans.mkdir()

            def sdk(case, phase):
                case_root = cases_root / case
                case_root.mkdir(exist_ok=True)
                return supervisor.invoke(_SDK, (case, phase, str(case_root)))

            def gc(case, fixture, *, plan=None, fault="none", expected=0):
                store = cases_root / case / "store"
                number = f"{supervisor.calls + 1:04d}"
                guard_file = guards / (number + ".json")
                intended = [] if plan is None else plan["plan"]["candidates"]
                rules = {"protected": fixture["protected"], "orphans": fixture.get("orphans", []),
                         "intended": intended}
                command = [
                    "plan-dataset-retention", "--store", str(store), "--min-age-seconds", "0"
                ]
                if plan is not None:
                    command = ["apply-dataset-retention", "--store", str(store), "--plan",
                               str(plans / (case + ".json")), "--expected-plan-id", plan["plan_id"]]
                before_tree = tree(store)
                payload, transcript = supervisor.invoke(
                    _GC_CLI, (str(store), json.dumps(rules), str(guard_file), fault, *command),
                    expected=expected
                )
                guard = json.loads(guard_file.read_bytes())
                assert guard["retained_payload_reads"] == guard["metadata_write_attempts"] == 0
                return {"response": payload, "transcript": transcript, "guard": guard,
                        "before": before_tree, "after": tree(store)}

            for case in _CASES[:3]:
                payload, transcript = sdk(case, "publish")
                payload["transcript"] = transcript
                observations.append(payload)
            for case in ("R01", "R02"):
                fixture, setup_call = sdk(case, "damage")
                store = cases_root / case / "store"
                error, inspect_call = supervisor.invoke(
                    _INSPECT, ("inspect-dataset", fixture["target"], "--store", str(store)),
                    expected=3, error_stream=True
                )
                assert error["error"]["code"] == "store_integrity_or_publication_failure"
                preparation, prepare_call = sdk(case, "prepare")
                planned = gc(case, fixture)
                plan = planned["response"]["plan"]
                assert planned["before"] == planned["after"]
                assert not planned["guard"]["orphan_opens"]
                if case == "R01":
                    assert plan["status"] == "READY"
                    assert fixture["damaged_object"] in plan["protected_objects"]
                    assert all(row["content_verified"] is False for row in plan["files"]
                               if row["path"].endswith(fixture["damaged_object"]))
                else:
                    assert plan["status"] == "BLOCKED" and plan["candidates"] == []
                    assert plan["diagnostics"] == ["missing_reference"]
                recovered, recover_call = sdk(case, "replace")
                assert recovered["recovery"]["dataset_id"] == fixture["target"]
                assert recovered["original_preserved"]["files"] == planned["after"]
                observations.append({**fixture, "inspect_failure": {"response": error,
                    "transcript": inspect_call}, "pre_gc": preparation, "maintenance": planned,
                    "recovery": recovered, "invocations": [setup_call, prepare_call, recover_call]})
            holder_root = cases_root / "L01"
            holder_root.mkdir()
            pending = supervisor.start(_HOLDER, (str(holder_root),))
            ready_file = holder_root / "controls" / "ready.json"
            try:
                while not ready_file.exists():
                    if pending["process"].poll() is not None:
                        raise AssertionError("Owned gate holder exited before ready")
                    if time.monotonic() >= pending["deadline"] or supervisor.remaining() <= 0:
                        raise TimeoutError("Holder readiness exceeded frozen wait budget")
                    time.sleep(0.01)
                ready = json.loads(ready_file.read_bytes())
                assert ready["pid"] == pending["process"].pid and ready["lock"] == "EX"
                blocked = gc("L01", ready)
                assert blocked["response"]["plan"]["diagnostics"] == ["maintenance_busy"]
                assert blocked["response"]["plan"]["status"] == "BLOCKED"
                assert blocked["before"] == blocked["after"]
                assert not blocked["guard"]["sqlite_uris"] and not blocked["guard"]["orphan_opens"]
            finally:
                controls = holder_root / "controls"
                controls.mkdir(exist_ok=True)
                (controls / "release").touch()
                holder, holder_call = supervisor.finish(pending)
            assert holder["pid"] == ready["pid"] and holder["released"] is True
            observations.append({"case_id": "L01", "fault_origin": "actual_process_lock",
                                 "blocked": blocked, "holder": holder, "transcript": holder_call})
            for case in ("M01", "M02"):
                fixture, setup_call = sdk(case, "orphans")
                planned = gc(case, fixture)
                preview = planned["response"]
                assert preview["plan"]["status"] == "READY"
                assert preview["plan"]["candidates"] == fixture["orphans"]
                assert digest(canonical(preview["plan"])) == preview["plan_id"]
                plan_path = plans / (case + ".json")
                transcript = root / "transcripts" / (planned["transcript"] + ".json")
                plan_path.write_text(json.loads(transcript.read_bytes())["stdout"])
                failed = gc(case, fixture, plan=preview,
                            fault="partial" if case == "M01" else "fsync", expected=9)
                response = failed["response"]
                store = cases_root / case / "store"
                shutil.copytree(store, cases_root / case / "images" / "failed")
                intended = fixture["orphans"]
                sizes = {row["sha256"]: row["size_bytes"] for row in preview["plan"]["files"]
                         if row["path"].startswith("objects/sha256/")}
                assert len(failed["guard"]["injection_hits"]) == 1
                assert response["intended"] == intended and response["already_absent"] == []
                assert failed["guard"]["unlinked"] == response["unlinked"]
                if case == "M01":
                    assert response["status"] == "PARTIAL"
                    assert response["diagnostic"] == "unlink_failed"
                    assert response["unlinked"] == intended[:1]
                    assert failed["guard"]["unlink_attempts"] == intended
                    assert failed["guard"]["fsync_directories"] == [
                        preview["plan"]["store"]["objects"]
                    ]
                else:
                    assert response["status"] == "IO_UNCONFIRMED"
                    assert response["diagnostic"] == "fsync_unconfirmed"
                    assert response["unlinked"] == intended
                    assert not failed["guard"]["fsync_directories"]
                assert response["removed_logical_bytes"] == sum(
                    sizes[key] for key in response["unlinked"]
                )
                repeated = gc(case, fixture, plan=preview)
                result = repeated["response"]
                assert result["status"] == "APPLIED" and result["diagnostic"] is None
                assert result["already_absent"] == response["unlinked"]
                remaining = [key for key in intended if key not in response["unlinked"]]
                assert result["unlinked"] == remaining
                assert repeated["guard"]["unlinked"] == remaining
                assert result["removed_logical_bytes"] == sum(sizes[key] for key in remaining)
                assert repeated["guard"]["fsync_directories"] == [
                    preview["plan"]["store"]["objects"]
                ]
                final_repeat = None
                if case == "M01":
                    final_repeat = gc(case, fixture, plan=preview)
                    assert final_repeat["response"]["status"] == "APPLIED"
                    assert final_repeat["response"]["unlinked"] == []
                    assert final_repeat["response"]["already_absent"] == intended
                    assert final_repeat["response"]["removed_logical_bytes"] == 0
                    assert final_repeat["guard"]["unlinked"] == []
                verified, verify_call = sdk(case, "verify")
                retained = {name: value for name, value in fixture["before"]["files"].items()
                            if name not in {"objects/sha256/" + key for key in intended}}
                assert verified["recovered"]["files"] == retained
                observations.append({"case_id": case, "fault_origin": "injected_boundary",
                    "fixture": fixture, "planned": planned, "failed": failed, "repeated": repeated,
                    "final_repeat": final_repeat, "verified": verified,
                    "invocations": [setup_call, verify_call]})
            assert tuple(item["case_id"] for item in observations) == _CASES
            after = {"controls": tree(sources[0]), "retention": tree(sources[1])}
            assert before == after
            elapsed = time.monotonic() - supervisor.started
            assert elapsed <= 180 and supervisor.calls <= 32
            report = {
                "kind": "installed_dataset_fault_budget_acceptance_v1", "schema_version": 1,
                "accepted": True, "interpreter_identity": identity,
                "budget": {"cases": 8, "max_child_invocations": 32, "max_child_seconds": 30,
                           "max_supervisor_seconds": 180, "child_invocations": supervisor.calls,
                           "elapsed_seconds": elapsed,
                           "cleanup_latency_included_in_hard_limit": False},
                "observations": observations, "protected_sources_before": before,
                "protected_sources_after": after,
                "scope": {"fixture_only": True, "new_native_calls": 0, "new_research_slots": 0,
                          "actual_disk_saturation": False, "actual_nonroot_eacces": True,
                          "actual_exclusive_gate_holder": True,
                          "known_source_new_store_recovery": True,
                          "in_place_corruption_repair": False,
                          "physical_freed_bytes_measured": False,
                          "source_controls_core_only": source_controls["core_only_profile"],
                          "power_loss_certified": False, "external_human_attempts": 0,
                          "external_human_gate": "PENDING"},
                "source_driver_sha256": digest(Path(__file__).read_bytes()),
            }
            inner = root / "dataset-faults-smoke" / "report.json"
            inner.parent.mkdir()
            inner.write_bytes(canonical(report))
            shutil.copytree(root, args.records_dir)
            inventory = tree(args.records_dir)
            (args.records_dir / "artifact-files.json").write_bytes(canonical(inventory))
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_bytes(canonical(report))
        except BaseException as error:
            with suppress(OSError, ValueError):
                if not args.records_dir.exists():
                    shutil.copytree(root, args.records_dir)
                (args.records_dir / "qualification-failure.json").write_bytes(canonical({
                    "accepted": False, "message": str(error)[:4096],
                    "completed_cases": [item["case_id"] for item in observations],
                    "child_invocations": supervisor.calls,
                    "elapsed_seconds": time.monotonic() - supervisor.started,
                }))
                inventory = {name: value for name, value in tree(args.records_dir).items()
                             if name != "artifact-files.json"}
                (args.records_dir / "artifact-files.json").write_bytes(canonical(inventory))
            raise


if __name__ == "__main__":
    main()
