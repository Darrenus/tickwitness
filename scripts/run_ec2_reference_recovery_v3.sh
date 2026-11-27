#!/usr/bin/env bash
# One detached controller; the unchanged installed lifecycle owns automatic Stop.
set -euo pipefail
umask 077
if [[ $EUID != 0 || $# != 2 || ! $1 =~ ^[0-9a-f]{40}$ || $2 != ec201aab11254e8bb7cd1573a96a0004 ]]; then
    echo 'The fixed root v3 controller requires its exact source and fourth run' >&2
    exit 64
fi
exec /usr/bin/timeout --signal=TERM --kill-after=2s 1500s \
    /usr/bin/python3 -I \
    /var/lib/tickwitness-lifecycle/ec2-recovery-batch-v3/ec2_reference_handoff_v3.py \
    run --source-revision "$1" --run-id "$2"
