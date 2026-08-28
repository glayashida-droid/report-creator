param(
    [string]$Title = "Select folder",
    [string]$DefaultPath = "",
    [string]$OutFile = ""
)

Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = $Title
$dialog.ShowNewFolderButton = $true

# DefaultPath is only a browse starting point. Do not create it.
if ($DefaultPath -and (Test-Path -LiteralPath $DefaultPath)) {
    $dialog.SelectedPath = (Resolve-Path -LiteralPath $DefaultPath).Path
}

$result = $dialog.ShowDialog()
if ($result -ne [System.Windows.Forms.DialogResult]::OK) {
    exit 1
}
$path = $dialog.SelectedPath
if (-not $path) {
    exit 1
}

if ($OutFile) {
    # System ANSI so cmd set /p can read Chinese paths on Chinese Windows.
    Set-Content -LiteralPath $OutFile -Value $path -Encoding Default
}
Write-Output $path
exit 0
