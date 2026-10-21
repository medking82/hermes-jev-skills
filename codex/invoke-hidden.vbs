Option Explicit
Dim shell, args, command, i, result
Set shell = CreateObject("WScript.Shell")
Set args = WScript.Arguments
If args.Count = 0 Then WScript.Quit 2
command = ""
For i = 0 To args.Count - 1
    If InStr(args(i), Chr(34)) > 0 Then WScript.Quit 2
    If i > 0 Then command = command & " "
    command = command & Chr(34) & args(i) & Chr(34)
Next
result = shell.Run(command, 0, True)
WScript.Quit result
