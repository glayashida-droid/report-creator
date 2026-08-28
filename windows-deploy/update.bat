@echo off
setlocal EnableExtensions EnableDelayedExpansion

title Report Creator Update

set "RC_FAIL_STEP="
set "RC_COMMON=%~dp0_lib\common.bat"

echo ============================================================
echo   Report Creator - Update
echo ============================================================
echo.
echo Sync latest app from USB to an installed copy on this PC.
echo Run setup.bat first if this PC has never been set up.
echo.

echo [Step 1/6] Check deploy scripts...
if not exist "%RC_COMMON%" (
    set "RC_FAIL_STEP=missing _lib\common.bat"
    echo [ERROR] !RC_FAIL_STEP!
    echo         expected: %RC_COMMON%
    goto Fail
)
echo         [OK] %RC_COMMON%

echo [Step 2/6] Resolve project paths...
call "%RC_COMMON%" InitPaths "%~dp0"
if errorlevel 1 (
    set "RC_FAIL_STEP=InitPaths failed"
    goto Fail
)
echo         DEPLOY_DIR   = %DEPLOY_DIR%
echo         PROJECT_ROOT = %PROJECT_ROOT%

echo [Step 3/6] Check project files...
call "%RC_COMMON%" Diagnose
if not exist "%PROJECT_ROOT%\run.py" (
    set "RC_FAIL_STEP=run.py missing in project root"
    echo [ERROR] !RC_FAIL_STEP!
    echo         PROJECT_ROOT: %PROJECT_ROOT%
    goto Fail
)
echo         [OK] run.py

echo [Step 4/6] Locate installed copy...
call :ReadInstallMarker
if errorlevel 1 (
    echo No install record found, pick the installed folder manually.
    call :PickInstallFolder "Select installed Report Creator folder" "%USERPROFILE%"
    if errorlevel 1 (
        set "RC_FAIL_STEP=pick install folder failed"
        goto Fail
    )
    set "RC_INSTALL_DIR=!RC_PICKED_DIR!"
) else (
    echo Found install folder: !RC_INSTALL_DIR!
    set /p RC_CONFIRM=Update this folder? [Y/n]: 
    if /I "!RC_CONFIRM!"=="N" (
        call :PickInstallFolder "Select installed Report Creator folder" "!RC_INSTALL_DIR!"
        if errorlevel 1 (
            set "RC_FAIL_STEP=pick install folder failed"
            goto Fail
        )
        set "RC_INSTALL_DIR=!RC_PICKED_DIR!"
    )
)
if not defined RC_INSTALL_DIR (
    set "RC_FAIL_STEP=install folder is empty"
    goto Fail
)
if "!RC_INSTALL_DIR!"=="" (
    set "RC_FAIL_STEP=install folder is empty"
    goto Fail
)

echo.
echo Will update: !RC_INSTALL_DIR!
set /p RC_GO=Continue? [Y/n]: 
if /I "!RC_GO!"=="N" (
    echo Cancelled.
    pause
    exit /b 0
)

echo [Step 5/6] Sync project files...
call :SyncProject "%PROJECT_ROOT%" "!RC_INSTALL_DIR!"
if errorlevel 1 (
    set "RC_FAIL_STEP=sync project failed"
    goto Fail
)
echo         [OK] sync done

echo [Step 6/6] Refresh venv dependencies...
call :FindPython
set "RC_PY_CODE=%ERRORLEVEL%"
if %RC_PY_CODE% EQU 0 goto PyReady
if %RC_PY_CODE% EQU 2 (
    set "RC_FAIL_STEP=Python too old, need %RC_PYTHON_MIN%+"
    echo [ERROR] !RC_FAIL_STEP!
    goto Fail
)
if %RC_PY_CODE% EQU 3 (
    echo         Found older Python; installing 3.12 alongside...
    call :InstallPython
    if errorlevel 1 (
        set "RC_FAIL_STEP=auto install Python failed"
        goto Fail
    )
    call :FindPython
    if errorlevel 1 (
        set "RC_FAIL_STEP=Python 3.12 not found after install"
        goto Fail
    )
) else (
    set "RC_FAIL_STEP=Python 3.12 not found, run setup.bat first"
    echo [ERROR] !RC_FAIL_STEP!
    goto Fail
)
:PyReady
echo         Python: !RC_PYTHON!
call :SetupVenv "!RC_INSTALL_DIR!"
if errorlevel 1 (
    set "RC_FAIL_STEP=venv or pip install failed"
    goto Fail
)
call :WriteRunLauncher "!RC_INSTALL_DIR!"
if errorlevel 1 (
    set "RC_FAIL_STEP=write run.bat failed"
    goto Fail
)
call :WriteInstallMarker "!RC_INSTALL_DIR!"
echo         [OK] update complete

echo.
echo ============================================================
echo   Update complete
echo ============================================================
echo.
echo Install folder: !RC_INSTALL_DIR!
echo Start app: !RC_INSTALL_DIR!\run.vbs  (or run.bat)
echo.
pause
exit /b 0

:ReadInstallMarker
call "%RC_COMMON%" ReadInstallMarker
exit /b %ERRORLEVEL%

:PickInstallFolder
call "%RC_COMMON%" PickInstallFolder %*
exit /b %ERRORLEVEL%

:SyncProject
call "%RC_COMMON%" SyncProject %*
exit /b %ERRORLEVEL%

:FindPython
call "%RC_COMMON%" FindPython
exit /b %ERRORLEVEL%

:SetupVenv
call "%RC_COMMON%" SetupVenv %*
exit /b %ERRORLEVEL%

:WriteRunLauncher
call "%RC_COMMON%" WriteRunLauncher %*
exit /b %ERRORLEVEL%

:WriteInstallMarker
call "%RC_COMMON%" WriteInstallMarker %*
exit /b %ERRORLEVEL%

:Fail
echo.
echo ============================================================
echo [FAILED] Update not completed
if defined RC_FAIL_STEP echo         failed step: !RC_FAIL_STEP!
echo ============================================================
echo.
echo Run test_paths.bat in this folder for full diagnostics.
echo.
if exist "%RC_COMMON%" call "%RC_COMMON%" Diagnose
pause
exit /b 1
