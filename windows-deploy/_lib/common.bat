@echo off
rem Shared helpers for Report Creator Windows deployment.
rem Usage: call "%~dp0_lib\common.bat" FunctionName [args...]
rem Do NOT use setlocal here - callers need DEPLOY_DIR / PROJECT_ROOT / RC_* to persist.

set "RC_APP_NAME=Report Creator"
set "RC_MARKER_DIR=%LOCALAPPDATA%\ReachReportCreator"
set "RC_MARKER_FILE=%RC_MARKER_DIR%\install_path.txt"
set "RC_PYTHON_MIN=3.12"

if "%~1"=="" exit /b 0

if /I "%~1"=="InitPaths" goto :InitPaths
if /I "%~1"=="EnsureMarkerDir" goto :EnsureMarkerDir
if /I "%~1"=="WriteInstallMarker" goto :WriteInstallMarker
if /I "%~1"=="ReadInstallMarker" goto :ReadInstallMarker
if /I "%~1"=="PickInstallFolder" goto :PickInstallFolder
if /I "%~1"=="FindPython" goto :FindPython
if /I "%~1"=="InstallPython" goto :InstallPython
if /I "%~1"=="SyncProject" goto :SyncProject
if /I "%~1"=="SetupVenv" goto :SetupVenv
if /I "%~1"=="WriteRunLauncher" goto :WriteRunLauncher
if /I "%~1"=="WriteDesktopShortcut" goto :WriteDesktopShortcut
if /I "%~1"=="Diagnose" goto :Diagnose
if /I "%~1"=="EnsureInstallFolder" goto :EnsureInstallFolder

echo [ERROR] common.bat unknown function: %~1
exit /b 1

:InitPaths
if not "%~2"=="" (
    for %%I in ("%~2.") do set "DEPLOY_DIR=%%~fI"
) else (
    for %%I in ("%~dp0..") do set "DEPLOY_DIR=%%~fI"
)
for %%I in ("%DEPLOY_DIR%\..") do set "PROJECT_ROOT=%%~fI"
if not defined DEPLOY_DIR (
    echo [ERROR] InitPaths: DEPLOY_DIR is empty
    exit /b 1
)
if not defined PROJECT_ROOT (
    echo [ERROR] InitPaths: PROJECT_ROOT is empty
    exit /b 1
)
exit /b 0

:Diagnose
echo.
echo ---------- path diagnose ----------
echo   %%~dp0 common.bat = %~dp0
echo   DEPLOY_DIR         = %DEPLOY_DIR%
echo   PROJECT_ROOT       = %PROJECT_ROOT%
echo   RC_MARKER_FILE     = %RC_MARKER_FILE%
echo.
if defined DEPLOY_DIR (
    if exist "%DEPLOY_DIR%\setup.bat" (echo   [OK] DEPLOY_DIR\setup.bat) else (echo   [MISS] DEPLOY_DIR\setup.bat)
    if exist "%DEPLOY_DIR%\_lib\common.bat" (echo   [OK] DEPLOY_DIR\_lib\common.bat) else (echo   [MISS] DEPLOY_DIR\_lib\common.bat)
    if exist "%DEPLOY_DIR%\_lib\pick_folder.ps1" (echo   [OK] pick_folder.ps1) else (echo   [MISS] pick_folder.ps1)
    if exist "%DEPLOY_DIR%\_lib\install_python.ps1" (echo   [OK] install_python.ps1) else (echo   [MISS] install_python.ps1)
    if exist "%DEPLOY_DIR%\_lib\create_shortcut.ps1" (echo   [OK] create_shortcut.ps1) else (echo   [MISS] create_shortcut.ps1)
    dir /b "%DEPLOY_DIR%\wheels\*.whl" >nul 2>&1
    if not errorlevel 1 (echo   [OK] wheels\ ^(local PySide6 etc^)) else (echo   [MISS] wheels\ ^(install will use internet^))
) else (
    echo   [MISS] DEPLOY_DIR is not set
)
if defined PROJECT_ROOT (
    if exist "%PROJECT_ROOT%\run.py" (echo   [OK] PROJECT_ROOT\run.py) else (echo   [MISS] PROJECT_ROOT\run.py)
    if exist "%PROJECT_ROOT%\requirements.txt" (echo   [OK] requirements.txt) else (echo   [MISS] requirements.txt)
    if exist "%PROJECT_ROOT%\src" (echo   [OK] src\) else (echo   [MISS] src\)
) else (
    echo   [MISS] PROJECT_ROOT is not set
)
echo ---------- diagnose end ----------
echo.
exit /b 0

:EnsureMarkerDir
if not exist "%RC_MARKER_DIR%" mkdir "%RC_MARKER_DIR%" >nul 2>&1
exit /b 0

:WriteInstallMarker
call :EnsureMarkerDir
> "%RC_MARKER_FILE%" echo %~2
exit /b 0

:ReadInstallMarker
set "RC_INSTALL_DIR="
if exist "%RC_MARKER_FILE%" set /p RC_INSTALL_DIR=<"%RC_MARKER_FILE%"
if not defined RC_INSTALL_DIR exit /b 1
if not exist "%RC_INSTALL_DIR%\run.py" (
    set "RC_INSTALL_DIR="
    exit /b 1
)
exit /b 0

:PickInstallFolder
set "RC_PICKED_DIR="
if not defined DEPLOY_DIR (
    echo [ERROR] PickInstallFolder: DEPLOY_DIR is not set, run InitPaths first
    exit /b 1
)
if not exist "%DEPLOY_DIR%\_lib\pick_folder.ps1" (
    echo [ERROR] pick_folder.ps1 not found
    echo         expected: %DEPLOY_DIR%\_lib\pick_folder.ps1
    exit /b 1
)
set "RC_PICK_FILE=%TEMP%\rc_folder_pick_%RANDOM%.txt"
if exist "%RC_PICK_FILE%" del /f /q "%RC_PICK_FILE%" >nul 2>&1
powershell -NoProfile -ExecutionPolicy Bypass -File "%DEPLOY_DIR%\_lib\pick_folder.ps1" -Title "%~2" -DefaultPath "%~3" -OutFile "%RC_PICK_FILE%"
if errorlevel 1 (
    echo [ERROR] folder picker cancelled or failed
    if exist "%RC_PICK_FILE%" del /f /q "%RC_PICK_FILE%" >nul 2>&1
    exit /b 1
)
if exist "%RC_PICK_FILE%" (
    set /p RC_PICKED_DIR=<"%RC_PICK_FILE%"
    del /f /q "%RC_PICK_FILE%" >nul 2>&1
)
rem Trim accidental spaces
for /f "tokens=* delims= " %%A in ("%RC_PICKED_DIR%") do set "RC_PICKED_DIR=%%A"
if not defined RC_PICKED_DIR (
    echo [ERROR] folder picker returned empty path
    exit /b 1
)
if "%RC_PICKED_DIR%"=="" (
    echo [ERROR] folder picker returned empty path
    exit /b 1
)
echo [OK] picked: %RC_PICKED_DIR%
exit /b 0

:FindPython
set "RC_PYTHON="

rem Prefer 3.12 first (matches windows-deploy\wheels).
where py >nul 2>&1
if not errorlevel 1 (
    for /f "delims=" %%P in ('py -3.12 -c "import sys; print(sys.executable)" 2^>nul') do set "RC_PYTHON=%%P"
)
if not defined RC_PYTHON (
    where py >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%P in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "RC_PYTHON=%%P"
    )
)
if not defined RC_PYTHON (
    where python >nul 2>&1
    if not errorlevel 1 (
        for /f "delims=" %%P in ('python -c "import sys; print(sys.executable)" 2^>nul') do set "RC_PYTHON=%%P"
    )
)
if not defined RC_PYTHON exit /b 1

rem exit 0 = 3.12+, 2 = too old ^(<3.10^), 3 = 3.10/3.11 needs 3.12 install
"%RC_PYTHON%" -c "import sys; v=sys.version_info; raise SystemExit(0 if v>=(3,12) else (2 if v<(3,10) else 3))" >nul 2>&1
exit /b %ERRORLEVEL%

:InstallPython
echo.
echo [ENV] Python %RC_PYTHON_MIN%+ not found, trying auto install...
if not defined DEPLOY_DIR (
    echo [ERROR] InstallPython: DEPLOY_DIR is not set
    exit /b 1
)
if not exist "%DEPLOY_DIR%\_lib\install_python.ps1" (
    echo [ERROR] install_python.ps1 not found
    echo         expected: %DEPLOY_DIR%\_lib\install_python.ps1
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%DEPLOY_DIR%\_lib\install_python.ps1"
if errorlevel 1 exit /b 1
call :FindPython
if errorlevel 1 exit /b 1
exit /b 0

:SyncProject
set "RC_SYNC_SRC=%~2"
set "RC_SYNC_DST=%~3"
call :NormalizeDir RC_SYNC_SRC
call :NormalizeDir RC_SYNC_DST
echo.
echo [SYNC] %RC_SYNC_SRC%
echo      -^> %RC_SYNC_DST%
if not defined RC_SYNC_SRC (
    echo [ERROR] sync source is empty
    exit /b 1
)
if not defined RC_SYNC_DST (
    echo [ERROR] sync destination is empty
    echo         Pick install folder again. Destination must not be blank.
    exit /b 1
)
if "%RC_SYNC_DST%"=="" (
    echo [ERROR] sync destination is empty
    exit /b 1
)
call :IsDriveRoot "%RC_SYNC_DST%"
if not errorlevel 1 (
    echo [ERROR] cannot install to drive root: %RC_SYNC_DST%
    echo         Pick a folder like D:\ReportCreator, not D:\
    exit /b 1
)
if not exist "%RC_SYNC_SRC%\run.py" (
    echo [ERROR] source missing run.py: %RC_SYNC_SRC%
    exit /b 1
)
if not exist "%RC_SYNC_DST%" mkdir "%RC_SYNC_DST%" >nul 2>&1
if not exist "%RC_SYNC_DST%" (
    echo [ERROR] cannot create destination: %RC_SYNC_DST%
    exit /b 1
)
rem Trailing backslash inside quotes breaks CMD ("D:\"). Paths are normalized above.
robocopy "%RC_SYNC_SRC%" "%RC_SYNC_DST%" /E /NFL /NDL /NJH /NJS /NP /R:2 /W:2 /XD .venv __pycache__ .git .pytest_cache .mypy_cache .cursor .scratch wheels /XF *.pyc *.pyo
set "RC_ROBO=%ERRORLEVEL%"
if %RC_ROBO% GEQ 8 (
    echo [ERROR] robocopy failed, exit code %RC_ROBO%
    echo         src="%RC_SYNC_SRC%"
    echo         dst="%RC_SYNC_DST%"
    exit /b 1
)
exit /b 0

:NormalizeDir
rem Strip trailing backslash from variable %1, except leave drive roots as X:\
set "RC_ND_NAME=%~1"
call set "RC_ND_VAL=%%%RC_ND_NAME%%%"
if not defined RC_ND_VAL exit /b 0
rem X: -> X:\
if "%RC_ND_VAL:~1,1%"==":" if "%RC_ND_VAL:~2%"=="" (
    set "%RC_ND_NAME%=%RC_ND_VAL%\"
    exit /b 0
)
rem Strip one trailing \
if "%RC_ND_VAL:~-1%"=="\" (
    set "RC_ND_VAL=%RC_ND_VAL:~0,-1%"
    rem If that made it a bare drive letter, restore X:\
    if "%RC_ND_VAL:~1,1%"==":" if "%RC_ND_VAL:~2%"=="" (
        set "%RC_ND_NAME%=%RC_ND_VAL%\"
        exit /b 0
    )
    set "%RC_ND_NAME%=%RC_ND_VAL%"
)
exit /b 0

:IsDriveRoot
rem exit 0 if path is X: or X:\
set "RC_IR=%~1"
if not defined RC_IR exit /b 1
if "%RC_IR:~1,1%"==":" if "%RC_IR:~2%"=="" exit /b 0
if "%RC_IR:~1,1%"==":" if "%RC_IR:~2%"=="\" exit /b 0
exit /b 1

:EnsureInstallFolder
rem If user picked drive root, use ^<drive^>\ReportCreator instead.
call :NormalizeDir RC_INSTALL_DIR
call :IsDriveRoot "%RC_INSTALL_DIR%"
if errorlevel 1 exit /b 0
set "RC_DRIVE=%RC_INSTALL_DIR:~0,2%"
set "RC_INSTALL_DIR=%RC_DRIVE%\ReportCreator"
echo [WARN] Drive root is not allowed. Will use: %RC_INSTALL_DIR%
exit /b 0

:SetupVenv
set "RC_TARGET=%~2"
set "RC_VENV=%RC_TARGET%\.venv"
echo.
echo [VENV] %RC_VENV%
if not defined RC_PYTHON (
    echo [ERROR] SetupVenv: RC_PYTHON is not set
    exit /b 1
)
if not exist "%RC_TARGET%\requirements.txt" (
    echo [ERROR] requirements.txt not found: %RC_TARGET%\requirements.txt
    exit /b 1
)
if not exist "%RC_VENV%\Scripts\python.exe" (
    "%RC_PYTHON%" -m venv "%RC_VENV%"
    if errorlevel 1 (
        echo [ERROR] failed to create venv
        exit /b 1
    )
)
call "%RC_VENV%\Scripts\activate.bat"
if errorlevel 1 (
    echo [ERROR] failed to activate venv: %RC_VENV%\Scripts\activate.bat
    exit /b 1
)
python -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERROR] pip upgrade failed
    exit /b 1
)

rem Prefer pre-downloaded Windows wheels next to setup.bat (USB), avoid slow PyPI.
set "RC_WHEELS="
if defined DEPLOY_DIR if exist "%DEPLOY_DIR%\wheels" (
    dir /b "%DEPLOY_DIR%\wheels\*.whl" >nul 2>&1
    if not errorlevel 1 set "RC_WHEELS=%DEPLOY_DIR%\wheels"
)
if not defined RC_WHEELS if exist "%RC_TARGET%\windows-deploy\wheels" (
    dir /b "%RC_TARGET%\windows-deploy\wheels\*.whl" >nul 2>&1
    if not errorlevel 1 set "RC_WHEELS=%RC_TARGET%\windows-deploy\wheels"
)

if defined RC_WHEELS (
    echo [WHEELS] installing from local folder:
    echo          %RC_WHEELS%
    python -m pip install --no-index --find-links="%RC_WHEELS%" -r "%RC_TARGET%\requirements.txt"
    if errorlevel 1 (
        echo [WARN] local wheel install failed, falling back to internet...
        python -m pip install -r "%RC_TARGET%\requirements.txt"
        if errorlevel 1 (
            echo [ERROR] failed to install requirements.txt
            exit /b 1
        )
    )
) else (
    echo [WHEELS] folder not found, downloading from internet ^(slow^)...
    python -m pip install -r "%RC_TARGET%\requirements.txt"
    if errorlevel 1 (
        echo [ERROR] failed to install requirements.txt
        exit /b 1
    )
)
if exist "%RC_TARGET%\application_parser\requirements.txt" (
    if defined RC_WHEELS (
        python -m pip install --no-index --find-links="%RC_WHEELS%" -r "%RC_TARGET%\application_parser\requirements.txt"
        if errorlevel 1 (
            python -m pip install -r "%RC_TARGET%\application_parser\requirements.txt"
            if errorlevel 1 (
                echo [ERROR] failed to install application_parser\requirements.txt
                exit /b 1
            )
        )
    ) else (
        python -m pip install -r "%RC_TARGET%\application_parser\requirements.txt"
        if errorlevel 1 (
            echo [ERROR] failed to install application_parser\requirements.txt
            exit /b 1
        )
    )
)
exit /b 0

:WriteRunLauncher
set "RC_TARGET=%~2"
if not defined DEPLOY_DIR (
    echo [ERROR] WriteRunLauncher: DEPLOY_DIR is not set
    exit /b 1
)
if not exist "%DEPLOY_DIR%\_lib\run_launcher.vbs" (
    echo [ERROR] run_launcher.vbs not found
    exit /b 1
)
copy /Y "%DEPLOY_DIR%\_lib\run_launcher.vbs" "%RC_TARGET%\run.vbs" >nul
if not exist "%RC_TARGET%\run.vbs" (
    echo [ERROR] failed to write run.vbs: %RC_TARGET%\run.vbs
    exit /b 1
)
> "%RC_TARGET%\run.bat" (
    echo @echo off
    echo wscript.exe //nologo "%%~dp0run.vbs"
)
if not exist "%RC_TARGET%\run.bat" (
    echo [ERROR] failed to write run.bat: %RC_TARGET%\run.bat
    exit /b 1
)
exit /b 0

:WriteDesktopShortcut
set "RC_TARGET=%~2"
if not defined DEPLOY_DIR (
    echo [ERROR] WriteDesktopShortcut: DEPLOY_DIR is not set
    exit /b 1
)
if not exist "%DEPLOY_DIR%\_lib\create_shortcut.ps1" (
    echo [ERROR] create_shortcut.ps1 not found
    exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%DEPLOY_DIR%\_lib\create_shortcut.ps1" -TargetPath "%RC_TARGET%\run.vbs" -ShortcutName "%RC_APP_NAME%"
if errorlevel 1 (
    echo [WARN] desktop shortcut failed, you can still use run.vbs or run.bat
    exit /b 0
)
exit /b 0
