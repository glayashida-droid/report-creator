@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

title Report Creator - 更新部署

echo ============================================================
echo   Report Creator - 更新部署
echo ============================================================
echo.
echo 从 U 盘同步最新程序到已安装的 Windows 电脑。
echo 请在本机已安装过 setup.bat 的前提下运行本脚本。
echo.

call "%~dp0_lib\common.bat" :InitPaths
if errorlevel 1 goto :Fail

if not exist "%PROJECT_ROOT%\run.py" (
    echo [错误] 未找到 run.py，请确认 U 盘中的项目目录完整。
    pause
    exit /b 1
)

call :ReadInstallMarker
if errorlevel 1 (
    echo 未找到本机安装记录，请手动选择已安装目录。
    call :PickInstallFolder "选择已安装的 Report Creator 目录" "C:\ReportCreator"
    if errorlevel 1 goto :Fail
    set "RC_INSTALL_DIR=!RC_PICKED_DIR!"
) else (
    echo 检测到已安装目录: !RC_INSTALL_DIR!
    set /p RC_CONFIRM=使用该目录进行更新? [Y/n]: 
    if /I "!RC_CONFIRM!"=="N" (
        call :PickInstallFolder "选择已安装的 Report Creator 目录" "!RC_INSTALL_DIR!"
        if errorlevel 1 goto :Fail
        set "RC_INSTALL_DIR=!RC_PICKED_DIR!"
    )
)

echo.
echo 即将更新: !RC_INSTALL_DIR!
set /p RC_GO=继续更新? [Y/n]: 
if /I "!RC_GO!"=="N" (
    echo 已取消。
    pause
    exit /b 0
)

call :SyncProject "%PROJECT_ROOT%" "!RC_INSTALL_DIR!"
if errorlevel 1 goto :Fail

call :FindPython
if errorlevel 1 (
    if errorlevel 2 (
        echo [错误] Python 版本过低，需要 %RC_PYTHON_MIN% 或更高。
        goto :Fail
    )
    echo [错误] 未找到 Python，请先运行 setup.bat 或手动安装 Python %RC_PYTHON_MIN%+。
    goto :Fail
)

echo.
echo 使用 Python: !RC_PYTHON!
call :SetupVenv "!RC_INSTALL_DIR!"
if errorlevel 1 goto :Fail

call :WriteRunLauncher "!RC_INSTALL_DIR!"
call :WriteInstallMarker "!RC_INSTALL_DIR!"

echo.
echo ============================================================
echo   更新完成
echo ============================================================
echo.
echo 安装位置: !RC_INSTALL_DIR!
echo 启动程序: !RC_INSTALL_DIR!\run.bat
echo.
pause
exit /b 0

:ReadInstallMarker
call "%~dp0_lib\common.bat" :ReadInstallMarker
exit /b %ERRORLEVEL%

:PickInstallFolder
call "%~dp0_lib\common.bat" :PickInstallFolder %*
exit /b %ERRORLEVEL%

:SyncProject
call "%~dp0_lib\common.bat" :SyncProject %*
exit /b %ERRORLEVEL%

:FindPython
call "%~dp0_lib\common.bat" :FindPython
exit /b %ERRORLEVEL%

:SetupVenv
call "%~dp0_lib\common.bat" :SetupVenv %*
exit /b %ERRORLEVEL%

:WriteRunLauncher
call "%~dp0_lib\common.bat" :WriteRunLauncher %*
exit /b %ERRORLEVEL%

:WriteInstallMarker
call "%~dp0_lib\common.bat" :WriteInstallMarker %*
exit /b %ERRORLEVEL%

:Fail
echo.
echo [失败] 更新未完成，请根据上方提示排查后重试。
pause
exit /b 1
