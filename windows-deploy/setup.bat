@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

title Report Creator - 一键部署

echo ============================================================
echo   Report Creator - Windows 一键部署
echo ============================================================
echo.
echo 本脚本将把程序安装到您选择的目录，并自动配置 Python 环境与依赖。
echo 建议从 U 盘中的项目根目录运行：windows-deploy\setup.bat
echo.

call "%~dp0_lib\common.bat" :InitPaths
if errorlevel 1 goto :Fail

if not exist "%PROJECT_ROOT%\run.py" (
    echo [错误] 未找到 run.py，请确认 U 盘中的项目目录完整。
    echo        当前识别到的项目根目录: %PROJECT_ROOT%
    pause
    exit /b 1
)

set "RC_DEFAULT_INSTALL=C:\ReportCreator"
echo 请选择安装目录（默认: %RC_DEFAULT_INSTALL%）
call :PickInstallFolder "选择 Report Creator 安装目录" "%RC_DEFAULT_INSTALL%"
if errorlevel 1 goto :Fail
set "RC_INSTALL_DIR=!RC_PICKED_DIR!"

echo.
echo 安装目录: !RC_INSTALL_DIR!
set /p RC_CONFIRM=确认安装到以上目录? [Y/n]: 
if /I "!RC_CONFIRM!"=="N" (
    echo 已取消。
    pause
    exit /b 0
)

call :SyncProject "%PROJECT_ROOT%" "!RC_INSTALL_DIR!"
if errorlevel 1 goto :Fail

call :FindPython
if errorlevel 1 (
    if errorlevel 2 (
        echo [错误] 检测到 Python 版本过低，需要 %RC_PYTHON_MIN% 或更高。
        goto :Fail
    )
    call :InstallPython
    if errorlevel 1 goto :Fail
)

echo.
echo 使用 Python: !RC_PYTHON!
call :SetupVenv "!RC_INSTALL_DIR!"
if errorlevel 1 goto :Fail

call :WriteRunLauncher "!RC_INSTALL_DIR!"
call :WriteInstallMarker "!RC_INSTALL_DIR!"
call :WriteDesktopShortcut "!RC_INSTALL_DIR!"

echo.
echo ============================================================
echo   部署完成
echo ============================================================
echo.
echo 安装位置: !RC_INSTALL_DIR!
echo.
echo 启动方式:
echo   1. 双击桌面快捷方式 "%RC_APP_NAME%"
echo   2. 运行 !RC_INSTALL_DIR!\run.bat
echo.
echo 以后更新: 将 U 盘插到目标电脑，运行 windows-deploy\update.bat
echo.
pause
exit /b 0

:PickInstallFolder
call "%~dp0_lib\common.bat" :PickInstallFolder %*
exit /b %ERRORLEVEL%

:SyncProject
call "%~dp0_lib\common.bat" :SyncProject %*
exit /b %ERRORLEVEL%

:FindPython
call "%~dp0_lib\common.bat" :FindPython
exit /b %ERRORLEVEL%

:InstallPython
call "%~dp0_lib\common.bat" :InstallPython
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

:WriteDesktopShortcut
call "%~dp0_lib\common.bat" :WriteDesktopShortcut %*
exit /b %ERRORLEVEL%

:Fail
echo.
echo [失败] 部署未完成，请根据上方提示排查后重试。
pause
exit /b 1
