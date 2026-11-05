# REBECCA
**R**eally **E**xciting **B**orderline **E**cstatic **C**AD **C**ontrol **A**rticulator

Webcam hand tracking that drives your CAD viewport by emulating mouse input. Built for
**inspecting a finished model or a link someone sent you**, not for everyday modeling.
Hotkey-activated: the camera is off until you press the hotkey, and off again afterwards.

## Try it with zero install
Open `testbench/index.html` in Chrome or Edge (or host the `testbench/` folder on Vercel/GitHub Pages).
Video is processed in the tab and never uploaded. SPACE simulates the hotkey, ESC stops the camera.

## Gestures (either hand)
| Gesture | Action |
|---|---|
| Pinch (thumb + index), move | Orbit |
| Fist, move | Pan |
| Both hands pinched, spread / close | Zoom |
| Both fists, turn like a wheel | Twist (roll in SolidWorks, otherwise spins the model) |
| Open hand | Idle (lift the "mouse") |

## Install (throwaway virtual environment, delete the folder to remove everything)
Python 3.10 to 3.12.
```
python -m venv .venv
# macOS/Linux: source .venv/bin/activate     Windows: .venv\Scripts\activate
pip install -r requirements.txt
python rebecca.py --list-cameras
python rebecca.py --pick-camera
python rebecca.py --app onshape --dry-run --now    # preview only, never touches the mouse
python rebecca.py --app fusion360                  # then press Ctrl+Alt+R
```
Apps: `fusion360 onshape solidworks blender freecad webviewer generic`. In the preview window:
`C` next camera, `A` next app profile, `SPACE` pause, `Q` end session.

Options: `--mode hold --hotkey "<f8>"` (live only while held), `--arm` (shoulder-relative tracking,
downloads a small pose model on first use), `--sensitivity`, `--zoom-gain`, `--twist-gain`, `--invert-zoom`,
`--no-preview`, `--no-save`. Settings are remembered in `~/.rebecca.json`.

## Permissions
- **macOS:** allow Camera, Accessibility and Input Monitoring for your terminal.
- **Windows:** allow camera access for desktop apps.
- Linux/Wayland: global hotkeys and mouse emulation via pynput may not work.
