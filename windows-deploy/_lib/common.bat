@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Shared constants and helpers for Report Creator Windows deployment.
rem Called via: call "%~dp0..\windows-deploy\_lib\common.bat" :FunctionName args...

set "RC_APP_NAME=Report Creator"
set "RC_MARKER_DIR=%LOCALAPPDATA%\ReachReportCreator"
set "RC_MARKER_FILE=%RC_MARKER_DIR%\install_path.txt"
set "RC_PYTHON_MIN=3.10"

goto :eof

:InitPaths
rem common.bat lives in _lib\; parent folder is windows-deploy, grandparent is repo root.
for %%I in ("%~dp0..") do set "DEPLOY_DIR=%%~fI"
for %%I in ("%DEPLOY_DIR%\..") do set "PROJECT_ROOT=%%~fI"
exit /b 0

:EnsureMarkerDir
if not exist "%RC_MARKER_DIR%" mkdir "%RC_MARKER_DIR%" >nul 2>&1
exit /b 0

:WriteInstallMarker
call :EnsureMarkerDir
> "%RC_MARKER_FILE%" echo %~1
exit /b 0

:ReadInstallMarker
set "RC_INSTALL_DIR="
if exist "%RC_MARKER_FILE%" (
    set /p RC_INSTALL_DIR=<"%RC_MARKER_FILE%"
)
if defined RC_INSTALL_DIR (
    if exist "!RC_INSTALL_DIR!\run.py" exit /b 0
)
set "RC_INSTALL_DIR="
exit /b 1

:PickInstallFolder
set "RC_PICKED_DIR="
for /f "usebackq delims=" %%I in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%DEPLOY_DIR%\_lib\pick_folder.ps1" -Title "%~1" -DefaultPath "%~2"`) do set "RC_PICKED_DIR=%%I"
if not defined RC_PICKED_DIR exit /b 1
exit /b 0

:FindPython
set "RC_PYTHON="
where py >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "RC_PYTHON=%%P"
)
if not defined RC_PYTHON (
    where python >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "RC_PYTHON=%%P"
    )
)
if not defined RC_PYTHON exit /b 1

"%RC_PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info>=(3,10) else 1)" >nul 2>&1
if errorlevel 1 (
    set "RC_PYTHON="
    exit /b 2
)
exit /b 0

:InstallPython
echo.
echo [环境] 未检测到 Python %RC_PYTHON_MIN%+ ，正在尝试自动安装...
powershell -NoProfile -ExecutionPolicy Bypass -File "%DEPLOY_DIR%\_lib\install_python.ps1"
if errorlevel 1 exit /b 1
call :FindPython
if errorlevel 1 exit /b 1
exit /b 0

:SyncProject
set "RC_SYNC_SRC=%~1"
set "RC_SYNC_DST=%~2"
echo.
echo [同步] %RC_SYNC_SRC%
echo      -^> %RC_SYNC_DST%
robocopy "%RC_SYNC_SRC%" "%RC_SYNC_DST%" /E /NFL /NDL /NJH /NJS /NP /R:2 /W:2 ^
    /XD .venv __pycache__ .git .pytest_cache .mypy_cache .cursor .scratch ^
    /XF *.pyc *.pyo
set "RC_ROBO=%ERRORLEVEL%"
if %RC_ROBO% GEQ 8 exit /b 1
exit /b 0

:SetupVenv
set "RC_TARGET=%~1"
set "RC_VENV=%RC_TARGET%\.venv"
echo.
echo [虚拟环境] %RC_VENV%
if not exist "%RC_VENV%\Scripts\python.exe" (
    "%RC_PYTHON%" -m venv "%RC_VENV%"
    if errorlevel 1 exit /b 1
)
call "%RC_VENV%\Scripts\activate.bat"
python -m pip install --upgrade pip
if errorlevel 1 exit /b 1
python -m pip install -r "%RC_TARGET%\requirements.txt"
if errorlevel 1 exit /b 1
if exist "%RC_TARGET%\application_parser\requirements.txt" (
    python -m pip install -r "%RC_TARGET%\application_parser\requirements.txt"
    if errorlevel 1 exit /b 1
)
exit /b 0

:WriteRunLauncher
set "RC_TARGET=%~1"
> "%RC_TARGET%\run.bat" (
    echo @echo off
    echo setlocal
    echo cd /d "%%~dp0"
    echo if not exist ".venv\Scripts\python.exe" ^(
    echo     echo 未找到虚拟环境，请先运行 windows-deploy\setup.bat 完成部署。
    echo     pause
    echo     exit /b 1
    echo ^)
    echo call ".venv\Scripts\activate.bat"
    echo python run.py
    echo if errorlevel 1 pause
)
exit /b 0

:WriteDesktopShortcut
set "RC_TARGET=%~1"
powershell -NoProfile -ExecutionPolicy Bypass -File "%DEPLOY_DIR%\_lib\create_shortcut.ps1" -TargetPath "%RC_TARGET%\run.bat" -ShortcutName "%RC_APP_NAME%"
exit /b 0
