#!/usr/bin/env bash
set -uo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
venv_python="$root_dir/.venv/bin/python"
state_dir="${XDG_STATE_HOME:-$HOME/.local/state}/orchestra"
report="$state_dir/diagnostics.log"
mkdir -p "$state_dir"

exec > >(tee "$report") 2>&1

printf 'Orchestra diagnostics\n'
printf 'Application: %s\n' "$root_dir"
printf 'Session: %s\n' "${XDG_SESSION_TYPE:-unknown}"
printf 'DISPLAY: %s\n' "${DISPLAY:-unset}"
printf 'WAYLAND_DISPLAY: %s\n' "${WAYLAND_DISPLAY:-unset}"

if [[ ! -x "$venv_python" ]]; then
  printf 'FAIL: virtual environment is missing. Run ./install.sh\n'
  exit 1
fi

"$venv_python" --version
"$venv_python" - <<'PY'
import PySide6
print("PySide6:", PySide6.__version__)
PY

xcb_plugin="$(find "$root_dir/.venv" -path '*/PySide6/Qt/plugins/platforms/libqxcb.so' -print -quit)"
if [[ -n "$xcb_plugin" ]]; then
  printf '\nXCB plugin: %s\n' "$xcb_plugin"
  missing="$(ldd "$xcb_plugin" 2>/dev/null | awk '/not found/ {print $1}' | sort -u)"
  if [[ -n "$missing" ]]; then
    printf 'FAIL: missing shared libraries:\n%s\n' "$missing"
  else
    printf 'PASS: XCB shared-library closure is complete.\n'
  fi
fi

printf '\nCreating a real QApplication instance…\n'
set +e
"$venv_python" - <<'PY'
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QWidget

app = QApplication([])
window = QWidget()
window.setWindowTitle("Orchestra diagnostic")
window.close()
print("PASS: Qt platform initialized:", QGuiApplication.platformName())
app.quit()
PY
status=$?
set -e

if (( status != 0 )); then
  printf 'FAIL: Qt platform initialization exited with status %d.\n' "$status"
  printf 'Ubuntu runtime repair:\n'
  printf 'sudo apt install libegl1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-xkb1 libxcb-util1\n'
  exit "$status"
fi

printf '\nDiagnostics passed. Report: %s\n' "$report"
