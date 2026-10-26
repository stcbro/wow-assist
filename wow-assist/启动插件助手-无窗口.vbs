' ============================================================
'  Start Turtle WoW Addon Helper WITHOUT console window
'  Double-click: launches the helper hidden in background,
'  only the browser UI pops up (http://127.0.0.1:8766)
'
'  Run log      : run.log (same folder as this script)
'  How to quit  : click the "Exit Tool (and restore)" button
'                 in the browser UI - game closes and everything
'                 installed this session is removed automatically
'  Lost the page: double-click "Open Helper UI.url"
'
'  NOTE: keep this file pure ASCII (no BOM). Windows Script Host
'  fails with error 800A0408 on UTF-8 BOM or non-ASCII content.
' ============================================================
Dim sh, fso, HERE, PY, LOGF, INNER
Set sh  = CreateObject("Wscript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
HERE = fso.GetParentFolderName(WScript.ScriptFullName)
PY   = "C:\Users\cyy\.workbuddy\binaries\python\versions\3.13.12\python.exe"
LOGF = HERE & "\run.log"
INNER = """" & PY & """ -u """ & HERE & "\addon_helper.py"" >> """ & LOGF & """ 2>&1"
sh.CurrentDirectory = HERE
sh.Run "cmd /c """ & INNER & """", 0, False
