#!/usr/bin/env bash
# Benchmark zram compression algorithms and levels on a scratch device.
# Never touches the live zram0 swap device.
#
# Usage: sudo ./zram-bench.sh [corpus-file]
set -euo pipefail

CORPUS=${1:-/var/tmp/zram-corpus.bin}
[ -r "$CORPUS" ] || { echo "no corpus at $CORPUS - run make-corpus.sh first"; exit 1; }
[ "$(id -u)" -eq 0 ] || { echo "needs root"; exit 1; }

CORPUS_BYTES=$(stat -c %s "$CORPUS")
DISKSIZE=$((CORPUS_BYTES + CORPUS_BYTES / 4))   # headroom so writes never fill up

# Configs to test: "algorithm level" (level "-" = algorithm default)
# Override with CONFIGS="zstd 1|zstd 3" and REPEATS=n
REPEATS=${REPEATS:-1}
if [ -n "${CONFIGS:-}" ]; then
  IFS='|' read -r -a CONFIGS <<<"$CONFIGS"
else
  CONFIGS=(
    "lzo-rle -"
    "lz4 -"
    "lz4hc 1"
    "lz4hc 9"
    "zstd 1"
    "zstd 3"
    "zstd 6"
    "zstd 12"
    "deflate -"
  )
fi

DEV=$(cat /sys/class/zram-control/hot_add)
SYS=/sys/block/zram$DEV
trap 'echo 1 > "$SYS/reset" 2>/dev/null; echo $DEV > /sys/class/zram-control/hot_remove 2>/dev/null || true' EXIT
echo "scratch device: /dev/zram$DEV (live zram0 untouched)"
echo

now() { local t=${EPOCHREALTIME/,/.}; echo "$t"; }
elapsed() { awk -v a="$1" -v b="$2" 'BEGIN{d=b-a; print (d>0?d:0.001)}'; }

printf '%-12s %-6s %8s %8s %8s %8s %6s %8s %6s\n' ALGO LVL RATIO ORIG_MB USED_MB WRITE_MBs +- READ_MBs +-

for cfg in "${CONFIGS[@]}"; do
  read -r algo lvl <<<"$cfg"

  echo 1 > "$SYS/reset"
  if ! echo "$algo" > "$SYS/comp_algorithm" 2>/dev/null; then
    printf '%-12s %-6s %8s\n' "$algo" "$lvl" "unsupported"; continue
  fi
  if [ "$lvl" != "-" ]; then
    if ! echo "algo=$algo level=$lvl" > "$SYS/algorithm_params" 2>/dev/null; then
      printf '%-12s %-6s %8s\n' "$algo" "$lvl" "no-level"; continue
    fi
  fi
  echo "$DISKSIZE" > "$SYS/disksize"

  # average over REPEATS runs, plus spread so noise is visible in the table
  ws=""; rs=""
  for _i in $(seq "$REPEATS"); do
    # write = compression path. conv=fsync so the timing includes the real work.
    sync; echo 3 > /proc/sys/vm/drop_caches
    t0=$(now)
    dd if="$CORPUS" of=/dev/zram$DEV bs=1M conv=fsync status=none
    t1=$(now)

    # read = decompression path, page cache dropped first
    sync; echo 3 > /proc/sys/vm/drop_caches
    t2=$(now)
    dd if=/dev/zram$DEV of=/dev/null bs=1M status=none
    t3=$(now)

    ws="$ws $(elapsed "$t0" "$t1")"; rs="$rs $(elapsed "$t2" "$t3")"
  done
  read -r orig compr used _ < "$SYS/mm_stat"
  awk -v a="$algo" -v l="$lvl" -v o="$orig" -v c="$compr" -v u="$used" \
      -v ws="$ws" -v rs="$rs" -v n="$CORPUS_BYTES" -v d="$DISKSIZE" 'BEGIN{
    # mean MB/s over the runs, and +/- half the min-max spread
    nw = split(ws, W); nr = split(rs, R)
    for (i=1;i<=nw;i++){ v=(n/1048576)/W[i]; sw+=v; if(i==1||v<lw)lw=v; if(i==1||v>hw)hw=v }
    for (i=1;i<=nr;i++){ v=(d/1048576)/R[i]; sr+=v; if(i==1||v<lr)lr=v; if(i==1||v>hr)hr=v }
    printf "%-12s %-6s %8.2f %8.0f %8.0f %8.0f %6s %8.0f %6s\n",
      a, l, (c>0?o/c:0), o/1048576, u/1048576,
      sw/nw, sprintf("+-%.0f",(hw-lw)/2), sr/nr, sprintf("+-%.0f",(hr-lr)/2)
  }'
done
