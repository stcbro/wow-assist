' ============================================================
'  WowAssist - start from source WITHOUT console window (dev only)
'
'  Use: double-click this file. It launches addon_helper.py hidden;
'        the UI window (pywebview) pops up as usual.
'  Why : after editing addon_helper.py / ui.html, this shows the
'        change immediately - no need to wait for a PyInstaller build.
'
'  Log   : %LOCALAPPDATA%\wowassist\run.log  (same as the packaged exe)
'  Quit  : tray icon -> Exit, or close the UI window
'  Note  : the python path MUST be one that has pywebview installed
'          (envs\default below). A bare interpreter fails with
'          "No module named webview".
'
'  NOTE: keep this file pure ASCII (no BOM). Windows Script Host
'  fails with error 800A0408 on UTF-8 BOM or non-ASCII content.
' ============================================================
Dim sh, fso, HERE, PY, LOGF, INNER
Set sh  = CreateObject("Wscript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
HERE = fso.GetParentFolderName(WScript.ScriptFullName)
HERE = fso.GetParentFolderName(HERE)          ' -> project root
PY   = "C:\Users\cyy\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
LOGF = sh.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\wowassist\run.log"
INNER = """" & PY & """ -u """ & HERE & "\addon_helper.py"" >> """ & LOGF & """ 2>&1"
sh.CurrentDirectory = HERE
sh.Run "cmd /c """ & INNER & """", 0, False
