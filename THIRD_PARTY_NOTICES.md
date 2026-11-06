# Third-party software

Rebecca's own code is MIT licensed (see `LICENSE`). The packaged apps include these libraries,
each under its own license:

| Component | License | Used for |
|---|---|---|
| MediaPipe | Apache-2.0 | hand and pose tracking models |
| OpenCV (opencv-contrib-python) | Apache-2.0 | camera capture, preview window |
| NumPy | BSD-3-Clause | numeric arrays |
| pynput | LGPL-3.0 | global hotkey, mouse and keyboard control |
| pystray | LGPL-3.0 | system tray icon |
| Pillow | HPND | drawing the tray icon |
| Python and Tcl/Tk | PSF / Tcl license | runtime and the on-screen indicator |
| PyInstaller | GPL-2.0 with bootloader exception | packaging the app |
| Inno Setup | Inno Setup License | building the Windows installer |

**LGPL libraries (pynput, pystray).** Rebecca is open source, so you can rebuild the app from
source with modified versions of these libraries: `pip install -r requirements.txt` and follow
`.github/workflows/build.yml`. The source for the versions used is published by their authors on PyPI.
