#!/bin/sh
# VirtualBox VMSVGA guest: VBoxDRMClient pushes the new window size to the kernel
# as the preferred mode, but nothing applies it under i3. Apply it on each DRM
# hotplug event. Exits immediately when not running on a VMSVGA adapter.

output=$(xrandr | awk '/^Virtual-[0-9]+ connected/ {print $1; exit}')
[ -n "$output" ] || exit 0

xrandr --output "$output" --auto

udevadm monitor --udev --subsystem-match=drm | while read -r line; do
    case "$line" in
        *change*) xrandr --output "$output" --auto ;;
    esac
done
