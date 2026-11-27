#!/usr/bin/env bash
# Remote-only one-use recovery; invoke through the verified lifecycle launcher.
# Historical1 stays charged; the new24/600 allowance is never automatically retried.
set -euo pipefail
umask 077

export_evidence() {
    revision=$1
    run_id=$2
    original_result=$3
    operation=/var/lib/tickwitness-lifecycle/reference-batches/$run_id
    if [[ ! -d $operation || -L $operation || $(stat -c %u "$operation") != 0 ]]; then
        return 74
    fi
    # Refuse a second export rather than overwrite an uncertain first export.
    (set -o noclobber; printf 'source_revision=%s\nrun_id=%s\nexit_code=%s\n' "$revision" "$run_id" "$original_result" > "$operation/batch-exit.env") || return 74
    paths=("tickwitness-lifecycle/reference-batches/$run_id/batch-exit.env")
    for name in batch-source.sh preparer-source.sh preparation.log qualification.stdout qualification.stderr source-check.log; do
        if [[ -f $operation/$name && ! -L $operation/$name ]]; then
            paths+=("tickwitness-lifecycle/reference-batches/$run_id/$name")
        fi
    done
    for path in "tickwitness-reference-ec2/host-admission.json" "tickwitness-reference-ec2/recovery-plan.json" "tickwitness-reference-ec2/recovery-consumption.json" "tickwitness-reference-ec2/recovery-evidence" "tickwitness-reference-ec2/runs/$run_id" "tickwitness-reference-ec2/runs/ec201aab11254e8bb7cd1573a96a0001" "tickwitness-reference-ec2/sources/$revision" "tickwitness-reference-ec2/sources/ae3d8e7981a79d6fc692f2cb656534a2f9a6683b"; do
        if [[ -e /var/lib/$path && ! -L /var/lib/$path ]]; then
            paths+=("$path")
        fi
    done
    archive=$operation/evidence.tar.gz
    /usr/bin/tar --format=posix --numeric-owner -czf "$archive" -C /var/lib -- "${paths[@]}" 2> "$operation/export.stderr" || return 74
    count=$(stat -c %s "$archive") || return 74
    if [[ ! $count =~ ^[0-9]+$ || $count -le 0 || $count -gt 16777216 ]]; then
        return 74
    fi
    digest=$(sha256sum "$archive") || return 74
    digest=${digest%% *}
    if [[ ! $digest =~ ^[0-9a-f]{64}$ ]]; then
        return 74
    fi
    printf 'TICKWITNESS_EC2_ARCHIVE_BEGIN run=%s bytes=%s sha256=%s\n' "$run_id" "$count" "$digest" || return 74
    # Chunk completeness requires markers, byte count and SHA; journald settings
    # must be observed before use. No missing/dropped record becomes acceptance.
    /usr/bin/base64 -w 16384 "$archive" || return 74
    printf '\nTICKWITNESS_EC2_ARCHIVE_END run=%s\n' "$run_id" || return 74
    sync || return 74
}

if [[ $EUID != 0 ]]; then
    exit 64
fi
if [[ $# == 4 && $1 == --internal-export && $2 =~ ^[0-9a-f]{40}$ && $3 == ec201aab11254e8bb7cd1573a96a0002 && $4 =~ ^[0-9]{1,3}$ && $4 -le 255 ]]; then
    export_evidence "$2" "$3" "$4"
    exit 0
fi
if [[ $# != 2 || ! $1 =~ ^[0-9a-f]{40}$ || $2 != ec201aab11254e8bb7cd1573a96a0002 ]]; then
    echo 'Trusted recovery batch requires one selected commit and the frozen successor run' >&2
    exit 64
fi
revision=$1
run_id=$2
stage=/var/lib/tickwitness-lifecycle/ec2-recovery-batch-v1
preparer=$stage/provision_ec2_reference_source.sh
printf 'be8bc6feb8f4c72eb8377a118c9bc4001cb1b6526e12d1e1674eeff23d557503  %s\n' "$preparer" | sha256sum --check --strict

/usr/bin/python3 -I - "$run_id" <<'PY'
import os
import stat
import sys
from pathlib import Path

root = Path('/var/lib/tickwitness-lifecycle/reference-batches')
for current in (*reversed(root.parents), root):
    try:
        current.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = current.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise SystemExit('Unsafe trusted batch directory ancestry')
target = root / sys.argv[1]
target.mkdir(mode=0o700)
descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PY

operation=/var/lib/tickwitness-lifecycle/reference-batches/$run_id

finish_and_export() {
    result=$1
    trap - EXIT
    set +e
    # A separate host-only transport ceiling after execution; never renews the
    # original qualification clocks, reservations or any probe's resource limits.
    /usr/bin/timeout --signal=TERM --kill-after=2s 25s /usr/bin/prlimit --fsize=16777216:16777216 -- /bin/bash "$0" --internal-export "$revision" "$run_id" "$result"
    exported=$?
    if [[ $exported != 0 ]]; then
        printf 'TICKWITNESS_EC2_EXPORT_UNCERTAIN run=%s status=%s\n' "$run_id" "$exported" >&2
        result=74
    fi
    # The installed lifecycle service, not this data-export function, owns Stop.
    exit "$result"
}
trap 'finish_and_export "$?"' EXIT

cp --no-dereference -- "$0" "$operation/batch-source.sh"
cp --no-dereference -- "$preparer" "$operation/preparer-source.sh"
{
    date -u +%Y-%m-%dT%H:%M:%SZ
    cat /proc/sys/kernel/random/boot_id
    sha256sum "$0" "$preparer"
    systemctl show tickwitness-boot-deadline.timer -p ActiveState -p UnitFileState -p NextElapseUSecMonotonic
} > "$operation/source-check.log"

read_clone_control() {
    if [[ -e /proc/sys/kernel/unprivileged_userns_clone ]]; then
        cat /proc/sys/kernel/unprivileged_userns_clone
    else
        printf 'ABSENT\n'
    fi
}

# Official dependency maintainer scripts can apply this fixed sysctl prefix.
# Admit only an already-enabled (or absent) knob; never turn disabled0 into1.
apparmor_before=$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns)
clone_before=$(read_clone_control)
printf 'apparmor_restriction_before=%s\nclone_control_before=%s\n' "$apparmor_before" "$clone_before" >> "$operation/source-check.log"
if [[ $apparmor_before != 1 || ( $clone_before != 1 && $clone_before != ABSENT ) ]]; then
    echo 'Existing global userns controls refuse dependency preparation' >&2
    exit 78
fi
if /bin/bash "$preparer" --recovery "$revision" > "$operation/preparation.log" 2>&1; then
    preparation_status=0
else
    preparation_status=$?
fi
apparmor_after=$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns)
clone_after=$(read_clone_control)
printf 'preparation_exit=%s\napparmor_restriction_after=%s\nclone_control_after=%s\n' "$preparation_status" "$apparmor_after" "$clone_after" >> "$operation/source-check.log"
if [[ $apparmor_after != "$apparmor_before" || $clone_after != "$clone_before" ]]; then
    echo 'Unexpected global control change; qualification was not admitted' >&2
    exit 78
fi
if [[ $preparation_status != 0 ]]; then
    exit "$preparation_status"
fi
# Copy the exact historical owner observation without modifying any old record.
# It is trusted owner evidence, not a signed or live AWS attestation.
/usr/bin/python3 -I - "$stage/operator-stop.md" <<'PY'
import hashlib
import os
import stat
import sys
from pathlib import Path

source = Path(sys.argv[1])
descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
try:
    info = os.fstat(descriptor)
    raw = os.read(descriptor, 2323)
    after = os.fstat(descriptor)
    current = source.lstat()
    stable = ('st_dev', 'st_ino', 'st_mode', 'st_uid', 'st_gid', 'st_nlink',
              'st_size', 'st_mtime_ns', 'st_ctime_ns')
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1
            or info.st_mode & 0o022 or len(raw) != 2322 or info.st_size != len(raw)
            or any(getattr(info, key) != getattr(after, key)
                   or getattr(info, key) != getattr(current, key) for key in stable)
            or hashlib.sha256(raw).hexdigest() != 'a64c30e2fff9fad194184ee278636e19da6ebfecbcae1f19ffe715b2db266193'):
        raise SystemExit('Historical owner observation bytes/identity differ')
finally:
    os.close(descriptor)
directory = Path('/var/lib/tickwitness-reference-ec2/recovery-evidence')
for current in (*reversed(directory.parents), directory):
    try:
        current.mkdir(mode=0o700)
    except FileExistsError:
        pass
    info = current.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise SystemExit('Unsafe observation directory ancestry')
descriptor = os.open(directory / 'operator-stop.md', os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
with os.fdopen(descriptor, 'wb') as stream:
    stream.write(raw)
    stream.flush()
    os.fsync(stream.fileno())
descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
try:
    os.fsync(descriptor)
finally:
    os.close(descriptor)
PY

/usr/bin/python3 -I "/opt/tickwitness-reference/$revision/scripts/prepare_ec2_reference_recovery.py" --source-revision "$revision" --plan-id ec2-recovery-20261126-v1 >> "$operation/preparation.log" 2>&1
/usr/bin/python3 -I "/opt/tickwitness-reference/$revision/scripts/qualify_restricted_reference_ec2.py" --source-revision "$revision" --run-id "$run_id" --recovery-plan ec2-recovery-20261126-v1 > "$operation/qualification.stdout" 2> "$operation/qualification.stderr"
