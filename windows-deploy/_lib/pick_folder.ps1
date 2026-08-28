param(
    [string]$Title = "选择文件夹",
    [string]$DefaultPath = ""
)

Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = $Title
$dialog.ShowNewFolderButton = $true

if ($DefaultPath -and (Test-Path -LiteralPath $DefaultPath)) {
    $dialog.SelectedPath = $DefaultPath
}

$result = $dialog.ShowDialog()
if ($result -eq [System.Windows.Forms.DialogResult]::OK -and $dialog.SelectedPath) {
    Write-Output $dialog.SelectedPath
}
