#!/usr/bin/env bash
# Build a benchmark corpus from real data on this machine.
# Mixed on purpose: binaries, text config, source, logs, already-compressed blobs.
# That mix is what a real desktop pushes into swap.
set -euo pipefail

OUT=${1:-/var/tmp/zram-corpus.bin}
SIZE_MB=${2:-256}

SRC=(
  /usr/bin
  /usr/lib/firefox
  /usr/share/icons
  "$HOME/.config"
  "$HOME/.cache/mozilla"
  "$HOME/dotfiles"
)

exists=()
for d in "${SRC[@]}"; do [ -e "$d" ] && exists+=("$d"); done

tar --ignore-failed-read -cf - "${exists[@]}" 2>/dev/null \
  | head -c "$((SIZE_MB * 1024 * 1024))" > "$OUT" || true

# Real memory also holds a lot of zero and repeated pages; zram handles those
# specially (same_pages). Add ~10% so the ratio numbers stay honest.
dd if=/dev/zero bs=1M count=$((SIZE_MB / 10)) >> "$OUT" 2>/dev/null

ls -lh "$OUT"
