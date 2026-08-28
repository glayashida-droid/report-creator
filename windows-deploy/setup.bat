@echo off
setlocal EnableExtensions EnableDelayedExpansion

title Report Creator Setup

set "RC_FAIL_STEP="
set "RC_COMMON=%~dp0_lib\common.bat"

echo ============================================================
echo   Report Creator - Windows Setup
echo ============================================================
echo.
echo Installs to a folder you choose and sets up Python + deps.
echo Run from USB: windows-deploy\setup.bat
echo.

echo [Step 1/8] Check deploy scripts...
if not exist "%RC_COMMON%" (
    set "RC_FAIL_STEP=missing _lib\common.bat"
    echo [ERROR] !RC_FAIL_STEP!
    echo         expected: %RC_COMMON%
    echo         script dir: %~dp0
    goto Fail
)
echo         [OK] %RC_COMMON%

echo [Step 2/8] Resolve project paths...
call "%RC_COMMON%" InitPaths "%~dp0"
if errorlevel 1 (
    set "RC_FAIL_STEP=InitPaths failed"
    goto Fail
)
echo         DEPLOY_DIR   = %DEPLOY_DIR%
echo         PROJECT_ROOT = %PROJECT_ROOT%

echo [Step 3/8] Check project files...
call "%RC_COMMON%" Diagnose
if not exist "%PROJECT_ROOT%\run.py" (
    set "RC_FAIL_STEP=run.py missing in project root"
    echo [ERROR] !RC_FAIL_STEP!
    echo         PROJECT_ROOT: %PROJECT_ROOT%
    echo         Copy the whole project folder to USB, not only windows-deploy.
    goto Fail
)
if not exist "%PROJECT_ROOT%\requirements.txt" (
    set "RC_FAIL_STEP=requirements.txt missing in project root"
    goto Fail
)
echo         [OK] run.py / requirements.txt

rem Start folder picker at user profile only as a browse hint (not the install target).
set "RC_BROWSE_START=%USERPROFILE%"
echo [Step 4/8] Pick install folder...
echo         Choose where to install. Nothing is copied until you confirm.
call :PickInstallFolder "Select Report Creator install folder" "%RC_BROWSE_START%"
if errorlevel 1 (
    set "RC_FAIL_STEP=pick install folder failed"
    goto Fail
)
set "RC_INSTALL_DIR=!RC_PICKED_DIR!"
if not defined RC_INSTALL_DIR (
    set "RC_FAIL_STEP=install folder is empty"
    goto Fail
)
if "!RC_INSTALL_DIR!"=="" (
    set "RC_FAIL_STEP=install folder is empty"
    goto Fail
)
call "%RC_COMMON%" EnsureInstallFolder
if errorlevel 1 (
    set "RC_FAIL_STEP=invalid install folder"
    goto Fail
)

echo.
echo Install folder: !RC_INSTALL_DIR!
echo         Tip: pick a real folder such as D:\ReportCreator, not D:\
set /p RC_CONFIRM=Continue with this folder? [Y/n]: 
if /I "!RC_CONFIRM!"=="N" (
    echo Cancelled.
    pause
    exit /b 0
)

echo [Step 5/8] Sync project files...
call :SyncProject "%PROJECT_ROOT%" "!RC_INSTALL_DIR!"
if errorlevel 1 (
    set "RC_FAIL_STEP=sync project failed"
    goto Fail
)
echo         [OK] sync done

echo [Step 6/8] Find or install Python 3.12...
call :FindPython
set "RC_PY_CODE=%ERRORLEVEL%"
if %RC_PY_CODE% EQU 0 goto PyReady
if %RC_PY_CODE% EQU 2 (
    set "RC_FAIL_STEP=Python too old, need %RC_PYTHON_MIN%+"
    echo [ERROR] !RC_FAIL_STEP!
    goto Fail
)
if %RC_PY_CODE% EQU 3 (
    echo         Found older Python; installing 3.12 alongside ^(wheels need 3.12^)...
) else (
    echo         Python not found; installing 3.12...
)
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
:PyReady
echo         [OK] Python: !RC_PYTHON!

echo [Step 7/8] Create venv and install deps...
call :SetupVenv "!RC_INSTALL_DIR!"
if errorlevel 1 (
    set "RC_FAIL_STEP=venv or pip install failed"
    goto Fail
)
echo         [OK] dependencies installed

echo [Step 8/8] Write launcher and desktop shortcut...
call :WriteRunLauncher "!RC_INSTALL_DIR!"
if errorlevel 1 (
    set "RC_FAIL_STEP=write run.bat failed"
    goto Fail
)
call :WriteInstallMarker "!RC_INSTALL_DIR!"
call :WriteDesktopShortcut "!RC_INSTALL_DIR!"
echo         [OK] launcher ready

echo.
echo ============================================================
echo   Setup complete
echo ============================================================
echo.
echo Install folder: !RC_INSTALL_DIR!
echo.
echo Start app:
echo   1. Desktop shortcut "%RC_APP_NAME%"
echo   2. !RC_INSTALL_DIR!\run.vbs  (or run.bat)
echo.
echo Updates: run windows-deploy\update.bat from USB
echo.
pause
exit /b 0

:PickInstallFolder
call "%RC_COMMON%" PickInstallFolder %*
exit /b %ERRORLEVEL%

:SyncProject
call "%RC_COMMON%" SyncProject %*
exit /b %ERRORLEVEL%

:FindPython
call "%RC_COMMON%" FindPython
exit /b %ERRORLEVEL%

:InstallPython
call "%RC_COMMON%" InstallPython
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

:WriteDesktopShortcut
call "%RC_COMMON%" WriteDesktopShortcut %*
exit /b %ERRORLEVEL%

:Fail
echo.
echo ============================================================
echo [FAILED] Setup not completed
if defined RC_FAIL_STEP echo         failed step: !RC_FAIL_STEP!
echo ============================================================
echo.
echo Run test_paths.bat in this folder for full diagnostics.
echo.
if exist "%RC_COMMON%" call "%RC_COMMON%" Diagnose
pause
exit /b 1
