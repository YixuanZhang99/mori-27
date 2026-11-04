#!/usr/bin/env bash
# Keep the acceptance verifier's disposable copy and test fixtures on tmpfs.
set -euo pipefail

: "${GITHUB_ENV:?GitHub Actions environment file is required}"
tmp_root="${MORI_CI_TMP_ROOT:-/dev/shm}"
make_tmpdir() {
  local root="$1" candidate
  [[ -d "$root" && -w "$root" ]] || return 1
  candidate=$(mktemp -d "$root/mori-acceptance.XXXXXXXX") || return 1
  case "$candidate" in *$'\n'*|*$'\r'*) rmdir "$candidate"; return 1;; esac
  printf '#!/bin/sh\nexit 0\n' > "$candidate/exec-probe"
  chmod 700 "$candidate/exec-probe"
  if ! "$candidate/exec-probe" >/dev/null 2>&1; then
    rm -f "$candidate/exec-probe"
    rmdir "$candidate"
    return 1
  fi
  rm -f "$candidate/exec-probe"
  printf '%s' "$candidate"
}
available_kib=$(df -Pk "$tmp_root" 2>/dev/null | awk 'NR == 2 {print $4}') || available_kib=''
if [[ ! "$available_kib" =~ ^[0-9]+$ ]] || (( available_kib < 1048576 )) || \
   ! tmp_path=$(make_tmpdir "$tmp_root"); then
  printf '%s\n' 'Fast temporary root unavailable; using runner temporary storage' >&2
  tmp_path=$(make_tmpdir "${RUNNER_TEMP:?Runner temporary storage is required}")
fi
printf 'TMPDIR=%s\n' "$tmp_path" >> "$GITHUB_ENV"
