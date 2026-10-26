@echo off
chcp 65001 >nul
rem WowAssist作者工具：制作更新包（双击运行）
cd /d "%~dp0"
"C:\Users\cyy\.workbuddy\binaries\python\versions\3.13.12\python.exe" "制作更新包.py"
pause
