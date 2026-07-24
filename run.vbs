Option Explicit

' Chạy Screen Translator 2K (bản Python) không hiện cửa sổ CMD.
Dim fso, shell, root, script, pyw, command
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

root = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = root
script = root & "\python-app\main.py"

If Not fso.FileExists(script) Then
    MsgBox "Không tìm thấy python-app\main.py.", 16, "Screen Translator 2K"
    WScript.Quit 1
End If

' Ưu tiên pythonw.exe của Python 3.10 đã cài; nếu không có, dùng pyw launcher.
pyw = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%\Programs\Python\Python310\pythonw.exe")
If Not fso.FileExists(pyw) Then
    pyw = "pyw"
End If

command = Chr(34) & pyw & Chr(34) & " " & Chr(34) & script & Chr(34)
shell.Run command, 0, False
