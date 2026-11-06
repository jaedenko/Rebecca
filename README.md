# REBECCA
**R**eally **E**xciting **B**orderline **E**cstatic **C**AD **C**ontrol **A**rticulator

Webcam hand tracking that moves your CAD viewport by emulating the mouse. Built for **inspecting a
finished model or a link someone sent you**, not for everyday modeling.

Rebecca lives in your **system tray**. The camera is **off** until you press the hotkey
(**Ctrl+Alt+R**) with your cursor over a CAD viewport, and off again when you press it again
(or after 45 s without hands). A short beep and a small **on-screen indicator pill** ("ORBIT | Onshape") tell you it went live / stopped. The camera window is
**hidden by default**; turn it on from the tray menu if you want to see yourself.

**Website:** https://rebecca-cad.vercel.app (downloads, how it works, and a try-it-in-your-browser demo)

## Install
**Windows:** download `RebeccaSetup.exe` from the [Releases](../../releases) page (or run the *Build Rebecca*
workflow and grab the artifact), double-click, done. No Python needed.
**macOS (experimental):** download `Rebecca-macOS.dmg`, drag the app to Applications, allow Camera,
Accessibility and Input Monitoring when asked.

> The builds are not code-signed yet, so Windows SmartScreen / Smart App Control may warn or block them.
> "More info -> Run anyway" works for SmartScreen. Smart App Control needs a signed app.

From source instead: `pip install -r requirements.txt`, then `python rebecca_tray.py`
(Python 3.10-3.12). `install.bat` / `install.command` automate that.

## Using it
1. Right-click the tray icon (ring icon near the clock). Check **Camera** and pick yours.
2. Open your model. Put the cursor over the viewport. Press **Ctrl+Alt+R**.
3. Gestures (either hand):

| Gesture | Action |
|---|---|
| Pinch (thumb + index), move | Orbit |
| Fist, move | Pan |
| Both hands pinched, spread / close | Zoom |
| Both fists, turn like a wheel | Twist (roll in SolidWorks, otherwise spins the model) |
| Open hand | Idle (lift the "mouse") |

**Fusion 360, Onshape, SolidWorks, Blender, FreeCAD, Sketchfab/Printables-style viewers** are supported.
By default Rebecca reads the title of the window you're looking at and picks the right mouse mapping
automatically (a browser tab with "Onshape" in its title -> Onshape, and so on). To force one, use
**App to control** in the tray menu. Onshape must use its default mouse settings (right-drag rotates).

## Tray menu
Status line - Start/stop now (left-click the icon) - Camera - App to control - Speed - Zoom speed -
Reverse zoom direction - Show camera preview - Show on-screen indicator - Sound cues -
Arm-relative tracking (experimental) - Hotkey (change it, or switch to hold-to-use) - Start at login -
Check for updates - Website and help - Quit. Settings are saved in `~/.rebecca.json`; a log is in `~/.rebecca.log`.

## Privacy
Video is processed on your computer and is never saved or sent anywhere. The camera is on only while a
session is running. There are no accounts and no analytics; the only network request Rebecca ever makes is
the one you trigger with **Check for updates**.

## Troubleshooting
- **Camera won't open:** another app (Zoom, Teams, a browser tab) may be using it. Close it or pick another camera.
- **Nothing moves in a CAD program running as administrator:** Windows blocks input from a normal app into an
  elevated one. Run Rebecca as administrator too.
- **Wrong mouse mapping:** choose the app under **App to control** instead of auto-detect. Onshape must use its default mouse settings.
- Logs: `~/.rebecca.log`. Settings: `~/.rebecca.json`.

## Building the apps yourself
`.github/workflows/build.yml` builds the Windows installer (PyInstaller + Inno Setup) and a macOS dmg on
GitHub: *Actions -> Build Rebecca -> Run workflow*, or push a tag like `v1.0.0` to publish a Release.
The build runs a self-test on the packaged app before uploading.

## Zero-install test bench
Open `testbench/index.html` in Chrome or Edge to try the gestures on a 3D part, no install.
SPACE simulates the hotkey, ESC stops the camera.

## Development
`pip install -r requirements.txt pytest && pytest` runs the tests (they also run in CI before every build).

## License
MIT, see `LICENSE`. Bundled libraries are listed in `THIRD_PARTY_NOTICES.md`.

## Command line (debugging)
`python rebecca.py --list-cameras | --setup | --now --dry-run --preview | --mode hold --hotkey "<f8>"`
