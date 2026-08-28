@echo off
setlocal EnableExtensions EnableDelayedExpansion

title Report Creator Path Check

set "RC_COMMON=%~dp0_lib\common.bat"
set "RC_ERRS=0"

echo ============================================================
echo   Report Creator - Path Self-Check
echo ============================================================
echo.
echo Read-only checks. Screenshot this window if something fails.
echo.

echo ---------- basic info ----------
echo   current dir cd   = %CD%
echo   script dir dp0   = %~dp0
echo   computer         = %COMPUTERNAME%
echo.

echo ---------- [1] common.bat ----------
if exist "%RC_COMMON%" (
    echo   [OK] found: %RC_COMMON%
) else (
    echo   [MISS] not found: %RC_COMMON%
    set /a RC_ERRS+=1
    echo.
    echo Fix: copy windows-deploy\_lib from Mac to USB.
    goto Done
)

echo.
echo ---------- [2] InitPaths ----------
call "%RC_COMMON%" InitPaths "%~dp0"
if errorlevel 1 (
    echo   [FAIL] InitPaths exit code %ERRORLEVEL%
    set /a RC_ERRS+=1
) else (
    echo   [OK] InitPaths ok
)
echo   DEPLOY_DIR   = %DEPLOY_DIR%
echo   PROJECT_ROOT = %PROJECT_ROOT%

echo.
echo ---------- [3] file list ----------
call "%RC_COMMON%" Diagnose

if not defined DEPLOY_DIR set /a RC_ERRS+=1
if not defined PROJECT_ROOT set /a RC_ERRS+=1
if not exist "%DEPLOY_DIR%\setup.bat" set /a RC_ERRS+=1
if not exist "%DEPLOY_DIR%\_lib\pick_folder.ps1" set /a RC_ERRS+=1
if not exist "%PROJECT_ROOT%\run.py" set /a RC_ERRS+=1
if not exist "%PROJECT_ROOT%\requirements.txt" set /a RC_ERRS+=1

echo ---------- [4] PowerShell ----------
where powershell >nul 2>&1
if errorlevel 1 (
    echo   [MISS] powershell not in PATH
    set /a RC_ERRS+=1
) else (
    for /f "delims=" %%P in ('where powershell') do (
        echo   [OK] %%P
        goto PsDone
    )
)
:PsDone

echo.
echo ---------- [5] Python optional ----------
call "%RC_COMMON%" FindPython
if errorlevel 1 (
    if errorlevel 2 (
        echo   [WARN] Python found but version ^< %RC_PYTHON_MIN%
    ) else if errorlevel 3 (
        echo   [INFO] Python 3.10/3.11 found; setup.bat will install 3.12 alongside
    ) else (
        echo   [INFO] Python %RC_PYTHON_MIN% not installed yet, setup.bat can install it
    )
) else (
    echo   [OK] %RC_PYTHON%
)

echo.
echo ---------- [6] install record optional ----------
if exist "%RC_MARKER_FILE%" (
    echo   marker file: %RC_MARKER_FILE%
    type "%RC_MARKER_FILE%"
) else (
    echo   [INFO] no install record yet, normal on first setup
)

:Done
echo.
echo ============================================================
if %RC_ERRS% GTR 0 (
    echo   result: %RC_ERRS% problem(s) found
    echo   screenshot this window and send it back.
) else (
    echo   result: PASS
    echo   paths look good, you can run setup.bat
)
echo ============================================================
echo.
pause
exit /b %RC_ERRS%
