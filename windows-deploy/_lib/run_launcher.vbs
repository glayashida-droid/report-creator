' Hidden GUI launcher (no console window). Installed as run.vbs in the app directory.
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
installDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonw = installDir & "\.venv\Scripts\pythonw.exe"
runPy = installDir & "\run.py"

If Not fso.FileExists(pythonw) Then
    MsgBox "Virtual environment not found." & vbCrLf & vbCrLf & "Run windows-deploy\setup.bat first.", vbCritical, "Report Creator"
    WScript.Quit 1
End If

If Not fso.FileExists(runPy) Then
    MsgBox "run.py not found in install folder." & vbCrLf & vbCrLf & "Re-run setup.bat.", vbCritical, "Report Creator"
    WScript.Quit 1
End If

shell.CurrentDirectory = installDir
shell.Run """" & pythonw & """ """ & runPy & """", 0, False
