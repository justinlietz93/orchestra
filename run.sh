#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
venv_python="$root_dir/.venv/bin/python"
state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/orchestra"
log_file="$state_dir/launch.log"

mkdir -p "$state_dir"
if [[ -f "$log_file" ]] && (( $(stat -c %s "$log_file") > 1048576 )); then
  mv -f "$log_file" "$state_dir/launch.previous.log"
fi

show_failure() {
  local message="Orchestra could not start. Details: $log_file"
  if [[ -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ]]; then
    if command -v zenity >/dev/null 2>&1; then
      zenity --error --title="Orchestra" --text="$message" >/dev/null 2>&1 || true
    elif command -v notify-send >/dev/null 2>&1; then
      notify-send "Orchestra" "$message" >/dev/null 2>&1 || true
    fi
  fi
}

if [[ ! -x "$venv_python" ]]; then
  message="Orchestra is not installed. Run: $root_dir/install.sh"
  printf '%s\n' "$message" | tee -a "$log_file" >&2
  show_failure
  exit 1
fi

{
  printf '\n[%s] Launching from %s\n' "$(date --iso-8601=seconds)" "$root_dir"
  printf 'Session: %s  Display: %s  Wayland: %s\n' \
    "${XDG_SESSION_TYPE:-unknown}" "${DISPLAY:-unset}" "${WAYLAND_DISPLAY:-unset}"
} >> "$log_file"

set +e
"$venv_python" -m phase_tracker "$@" \
  > >(tee -a "$log_file") \
  2> >(tee -a "$log_file" >&2)
status=$?
set -e

if (( status != 0 )); then
  printf 'Application exited with status %d.\n' "$status" | tee -a "$log_file" >&2
  show_failure
fi

exit "$status"
