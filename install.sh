#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python_bin="${PYTHON:-python3}"

"$python_bin" -m venv "$root_dir/.venv"
"$root_dir/.venv/bin/python" -m pip install --upgrade pip
"$root_dir/.venv/bin/python" -m pip install -e "$root_dir"

qt_python="$root_dir/.venv/bin/python"
xcb_plugin="$(find "$root_dir/.venv" -path '*/PySide6/Qt/plugins/platforms/libqxcb.so' -print -quit)"

if [[ -n "$xcb_plugin" ]]; then
  missing_libraries="$(ldd "$xcb_plugin" 2>/dev/null | awk '/not found/ {print $1}' | sort -u)"
else
  missing_libraries=""
fi

if [[ -n "$missing_libraries" ]]; then
  echo
  echo "Qt is installed, but Linux desktop libraries are missing:"
  echo "$missing_libraries"
  echo
  echo "On Ubuntu, install the Qt/XCB runtime set with:"
  echo "sudo apt install libegl1 libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-render-util0 libxcb-xkb1 libxcb-util1"
  exit 1
fi

if [[ -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ]]; then
  if ! "$qt_python" - <<'PY'
from PySide6.QtWidgets import QApplication, QWidget

app = QApplication([])
window = QWidget()
window.setWindowTitle("Orchestra installation check")
window.close()
app.quit()
PY
  then
    echo
    echo "Qt could not create a desktop window."
    echo "Run ./diagnose.sh for the exact missing library or platform error."
    exit 1
  fi
elif ! "$qt_python" -c "from PySide6.QtWidgets import QApplication"; then
  echo "Qt could not load. Run ./diagnose.sh for details."
  exit 1
fi

desktop_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
icon_dir="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
mkdir -p "$desktop_dir" "$icon_dir"

sed \
  -e "s|@EXEC@|$root_dir/run.sh|g" \
  -e "s|@ICON@|$root_dir/assets/orchestra.svg|g" \
  "$root_dir/assets/orchestra.desktop.in" \
  > "$desktop_dir/orchestra.desktop"
chmod +x "$desktop_dir/orchestra.desktop" "$root_dir/run.sh"
rm -f "$desktop_dir/project-handoff-tracker.desktop"

echo "Installed. Launch 'Orchestra' from your application menu or run ./run.sh"
