@echo off
setlocal
cd /d "%~dp0"
title REBECCA installer
echo.
echo === REBECCA installer ===
echo.

set "PYCMD="
for %%V in (3.12 3.11 3.10) do (
  if not defined PYCMD (
    py -%%V --version >nul 2>nul
    if not errorlevel 1 set "PYCMD=py -%%V"
  )
)

if not defined PYCMD (
  echo Python 3.10 to 3.12 was not found.
  where winget >nul 2>nul
  if errorlevel 1 (
    echo Please install Python 3.12 from python.org, then double-click install.bat again.
    start https://www.python.org/downloads/
    pause
    exit /b 1
  )
  echo Installing Python 3.12 with winget...
  winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
  echo.
  echo Python is installed. CLOSE this window, then double-click install.bat once more.
  pause
  exit /b 0
)

echo Using: %PYCMD%
%PYCMD% -m venv .venv
if errorlevel 1 goto fail
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul 2>nul
echo.
echo Installing hand-tracking libraries (a few hundred MB, one time)...
pip install -r requirements.txt
if errorlevel 1 goto fail

(
  echo @echo off
  echo cd /d "%%~dp0"
  echo start "" ".venv\Scripts\pythonw.exe" rebecca_tray.py
) > Rebecca.bat

powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Rebecca.lnk');$s.TargetPath='%~dp0Rebecca.bat';$s.WorkingDirectory='%~dp0';$s.WindowStyle=7;$s.Save()" >nul 2>nul

echo.
echo Choose your camera: N / P to switch, ENTER to confirm.
python rebecca.py --setup
if errorlevel 1 goto fail

echo.
echo === Done! ===
echo Start Rebecca with the "Rebecca" shortcut on your Desktop. It lives in your system tray (the ^ by the clock).
echo Put your cursor over the CAD viewport and press Ctrl+Alt+R. Right-click the tray icon for settings.
echo.
pause
exit /b 0

:fail
echo.
echo Something went wrong. Copy the messages above and send them to whoever is helping you.
pause
exit /b 1
