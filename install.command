#!/bin/bash
cd "$(dirname "$0")" || exit 1
echo
echo "=== REBECCA installer ==="
echo

PY=""
for v in python3.12 python3.11 python3.10 python3; do
  if command -v "$v" >/dev/null 2>&1; then
    ver=$("$v" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
    case "$ver" in 3.10|3.11|3.12) PY="$v"; break ;; esac
  fi
done

if [ -z "$PY" ]; then
  echo "Python 3.10 to 3.12 was not found."
  if command -v brew >/dev/null 2>&1; then
    echo "Installing Python 3.12 with Homebrew..."
    brew install python@3.12 && PY=python3.12
  fi
  if [ -z "$PY" ]; then
    echo "Please install Python 3.12 from https://www.python.org/downloads/ then double-click this file again."
    open "https://www.python.org/downloads/"
    read -n 1 -s -r -p "Press any key to close..."; exit 1
  fi
fi

echo "Using: $($PY --version)"
fail() { echo; echo "Something went wrong. Copy the messages above and send them to whoever is helping you."; read -n 1 -s -r -p "Press any key to close..."; exit 1; }

"$PY" -m venv .venv || fail
source .venv/bin/activate
pip install --upgrade pip >/dev/null 2>&1
echo
echo "Installing hand-tracking libraries (a few hundred MB, one time)..."
pip install -r requirements.txt || fail

cat > Rebecca.command <<'LAUNCH'
#!/bin/bash
cd "$(dirname "$0")" || exit 1
source .venv/bin/activate
python rebecca_tray.py "$@" &
LAUNCH
chmod +x Rebecca.command

echo
echo "Choose your camera: N / P to switch, ENTER to confirm."
python rebecca.py --setup || fail

echo
echo "=== Done! ==="
echo "Start Rebecca by double-clicking Rebecca.command. It lives in your menu bar. Put your cursor over"
echo "the CAD viewport and press Ctrl+Alt+R. Click the menu-bar icon for settings."
echo
echo "macOS will ask for permissions the first time. Allow Camera, and in System Settings >"
echo "Privacy & Security enable your Terminal under both Accessibility and Input Monitoring."
echo
read -n 1 -s -r -p "Press any key to close..."
