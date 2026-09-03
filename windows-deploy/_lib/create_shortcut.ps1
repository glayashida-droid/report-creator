param(
    [Parameter(Mandatory = $true)]
    [string]$TargetPath,
    [Parameter(Mandatory = $true)]
    [string]$ShortcutName,
    [string]$IconPath = ""
)

$WshShell = New-Object -ComObject WScript.Shell
$desktop = [System.Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "$ShortcutName.lnk"
$shortcut = $WshShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $TargetPath
$shortcut.WorkingDirectory = Split-Path -Parent $TargetPath
$shortcut.WindowStyle = 1
$shortcut.Description = $ShortcutName
if ($IconPath -and (Test-Path -LiteralPath $IconPath)) {
    $shortcut.IconLocation = "$IconPath,0"
}
$shortcut.Save()

# Explorer caches .lnk icons; notify the shell so an update replaces the old picture.
$notify = @"
[System.Runtime.InteropServices.DllImport("Shell32.dll")]
public static extern void SHChangeNotify(int wEventId, uint uFlags, System.IntPtr dwItem1, System.IntPtr dwItem2);
"@
try {
    $type = Add-Type -MemberDefinition $notify -Name "RcShellNotify" -Namespace Win32 -PassThru
    # SHCNE_ASSOCCHANGED = 0x08000000, SHCNF_IDLIST = 0
    $type::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
} catch {
}

Write-Host "已创建桌面快捷方式: $shortcutPath"
