param(
    [Parameter(Mandatory = $true)]
    [string]$TargetPath,
    [Parameter(Mandatory = $true)]
    [string]$ShortcutName
)

$WshShell = New-Object -ComObject WScript.Shell
$desktop = [System.Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "$ShortcutName.lnk"
$shortcut = $WshShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $TargetPath
$shortcut.WorkingDirectory = Split-Path -Parent $TargetPath
$shortcut.WindowStyle = 1
$shortcut.Description = $ShortcutName
$shortcut.Save()

Write-Host "已创建桌面快捷方式: $shortcutPath"
