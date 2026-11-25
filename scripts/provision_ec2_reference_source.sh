#!/usr/bin/env bash
# Trusted host preparation only. Run remotely inside the verified stop wrapper.
# No policy load, probe, research reservation, controller enablement or disk format.
set -euo pipefail

if [[ $# != 1 || ! $1 =~ ^[0-9a-f]{40}$ ]]; then
    echo 'usage: provision_ec2_reference_source.sh <actual-pushed-40hex-commit>' >&2
    exit 64
fi
revision=$1
if [[ $EUID != 0 || $(uname -m) != x86_64 ]]; then
    echo 'Trusted preparation requires the selected root x86_64 EC2 host' >&2
    exit 78
fi
if ! /usr/bin/python3 -I -c 'import platform; r=platform.freedesktop_os_release(); assert r.get("ID")=="ubuntu" and r.get("VERSION_ID")=="24.04"'; then
    echo 'Unsupported host release' >&2
    exit 78
fi
if [[ $(systemctl is-active tickwitness-boot-deadline.timer) != active || $(systemctl is-enabled tickwitness-boot-deadline.timer) != enabled ]]; then
    echo 'Verified automatic-stop timer must already be enabled and active' >&2
    exit 78
fi

checkout_root=/opt/tickwitness-reference
checkout=$checkout_root/$revision
anchor_root=/var/lib/tickwitness-reference-ec2/sources
anchor=$anchor_root/$revision

# Verify common parents instead of chmod/chown of any pre-existing foreign path.
/usr/bin/python3 -I - "$checkout_root" "$anchor_root" <<'PY'
import os
import stat
import sys
from pathlib import Path

for target in map(Path, sys.argv[1:]):
    current = Path('/')
    for part in target.parts[1:]:
        current /= part
        try:
            current.mkdir(mode=0o755)
        except FileExistsError:
            pass
        info = current.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise SystemExit('Unsafe common preparation ancestor: ' + str(current))
PY

if [[ -e $checkout || -L $checkout || -e $anchor || -L $anchor ]]; then
    echo 'Selected source or anchor already exists; retain and inspect it, do not overwrite' >&2
    exit 78
fi

# Official Ubuntu packages are installed before the qualification claim/TCB freeze.
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install --no-install-recommends -y bubblewrap linux-libc-dev git ca-certificates

git -c core.hooksPath=/dev/null clone --no-checkout https://github.com/Darrenus/tickwitness.git "$checkout"
git -C "$checkout" -c core.hooksPath=/dev/null checkout --detach "$revision"
actual_revision=$(git -C "$checkout" rev-parse --verify HEAD)
if [[ $actual_revision != "$revision" || -n $(git -C "$checkout" status --porcelain --untracked-files=all) ]]; then
    echo 'Actual Git source is not the selected clean commit' >&2
    exit 78
fi

/usr/bin/python3 -I - "$revision" "$checkout" "$anchor" <<'PY'
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

revision, source, anchor = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
selected = (
    'src/tickwitness/infrastructure/restricted_reference_ec2.py',
    'scripts/qualify_restricted_reference_ec2.py',
    'scripts/prepare_reference_policy_ec2.py',
    'scripts/prepare_reference_policy.py',
    'scripts/qualify_restricted_reference.py',
    'src/tickwitness/infrastructure/restricted_reference.py',
    'src/tickwitness/infrastructure/restricted_reference_bootstrap.py',
    'scripts/restricted_reference_payload.py',
    'research/security/reference-ec2.apparmor',
)
rows = {}
for relative in selected:
    path = source / relative
    for parent in (path, *path.parents):
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise SystemExit('Untrusted selected source identity: ' + str(parent))
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise SystemExit('Selected source is not a single regular file')
        raw = bytearray()
        while piece := os.read(descriptor, 65536):
            raw.extend(piece)
            if len(raw) > 1024 * 1024:
                raise SystemExit('Selected source exceeds trusted preparation bound')
        after = os.fstat(descriptor)
        stable = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_nlink',
                  'st_size', 'st_mtime_ns', 'st_ctime_ns')
        if any(getattr(before, key) != getattr(after, key) for key in stable) or len(raw) != before.st_size:
            raise SystemExit('Selected source changed during preparation')
    finally:
        os.close(descriptor)
    rows[relative] = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}

lock = {
    'kind': 'restricted_reference_ec2_source_lock_v1',
    'schema_version': 1,
    'source_revision': revision,
    'source_root': str(source),
    'files': rows,
}
raw = json.dumps(lock, sort_keys=True, separators=(',', ':'), allow_nan=False).encode() + b'\n'
if len(raw) > 65536:
    raise SystemExit('Source lock exceeds the selected document bound')
anchor.mkdir(mode=0o755)
descriptor = os.open(anchor / 'source-lock.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
with os.fdopen(descriptor, 'wb') as stream:
    stream.write(raw)
    stream.flush()
    os.fsync(stream.fileno())
directory = os.open(anchor, os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(directory)
finally:
    os.close(directory)
parent = os.open(anchor.parent, os.O_RDONLY | os.O_DIRECTORY)
try:
    os.fsync(parent)
finally:
    os.close(parent)
print(json.dumps({'source_revision': revision, 'source_root': str(source), 'source_lock_sha256': hashlib.sha256(raw).hexdigest()}, sort_keys=True))
PY

dpkg-query -W python3.12 bubblewrap apparmor libapparmor1 linux-libc-dev git
sha256sum /usr/bin/bwrap /usr/include/x86_64-linux-gnu/asm/unistd_64.h "$anchor/source-lock.json"
echo 'Trusted source preparation completed; no qualification claim or probe was opened.'
