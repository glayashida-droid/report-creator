$ErrorActionPreference = "Stop"

Write-Host "尝试通过 winget 安装 Python 3.12（当前用户，无需管理员）..." -ForegroundColor Cyan

$winget = Get-Command winget -ErrorAction SilentlyContinue
if ($winget) {
    & winget install --id Python.Python.3.12 -e `
        --scope user `
        --accept-package-agreements `
        --accept-source-agreements
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Python 安装完成。" -ForegroundColor Green
        exit 0
    }
    Write-Host "winget 安装失败，尝试下载官方安装包..." -ForegroundColor Yellow
}

$version = "3.12.7"
$installer = Join-Path $env:TEMP "python-$version-amd64.exe"
$url = "https://www.python.org/ftp/python/$version/python-$version-amd64.exe"

Write-Host "下载 $url"
Invoke-WebRequest -Uri $url -OutFile $installer -UseBasicParsing

Write-Host "静默安装 Python（添加到当前用户 PATH）..."
$args = @(
    "/quiet",
    "InstallAllUsers=0",
    "PrependPath=1",
    "Include_test=0",
    "Include_launcher=1"
)
$p = Start-Process -FilePath $installer -ArgumentList $args -Wait -PassThru
Remove-Item -LiteralPath $installer -Force -ErrorAction SilentlyContinue

if ($p.ExitCode -ne 0) {
    Write-Host "自动安装失败。请手动安装 Python 3.10+ 并勾选 Add to PATH：" -ForegroundColor Red
    Write-Host "https://www.python.org/downloads/windows/"
    exit 1
}

Write-Host "Python 安装完成。如仍提示找不到 python，请关闭窗口后重新运行 setup.bat。" -ForegroundColor Green
exit 0
