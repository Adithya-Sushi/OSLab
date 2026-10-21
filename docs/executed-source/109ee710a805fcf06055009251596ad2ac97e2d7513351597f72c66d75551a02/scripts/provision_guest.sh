#!/bin/sh
set -eu
# This script changes swap only inside the explicitly marked research VM.
test "$(uname -s)" = Linux
test -f /etc/oslab-research-vm
test "$(id -u)" = 0
if test "$(wc -l < /proc/swaps)" -gt 1; then
    if ! awk 'NR>1 && $1 !~ /^\/dev\/zram/ {bad=1} END {exit bad}' /proc/swaps; then
        echo 'Unexpected active swap; refusing to replace an existing backend' >&2
        exit 2
    fi
fi
if test -w /sys/module/zswap/parameters/enabled; then echo N > /sys/module/zswap/parameters/enabled; fi
modprobe zram num_devices=1
if ! awk 'NR>1 && $1=="/dev/zram0" {found=1} END {exit !found}' /proc/swaps; then
    test "$(cat /sys/block/zram0/disksize)" = 0
    zramctl /dev/zram0 --algorithm lz4 --size 1G
    mkswap /dev/zram0
    swapon /dev/zram0
fi
sysctl -w vm.swappiness=100
systemctl stop apt-daily.timer apt-daily-upgrade.timer man-db.timer 2>/dev/null || true
