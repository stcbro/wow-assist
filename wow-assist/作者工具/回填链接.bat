@echo off
chcp 65001 >nul
rem WowAssist作者工具：回填蓝奏云分享链接到 manifest（上传后运行）
cd /d "%~dp0"
"C:\Users\cyy\.workbuddy\binaries\python\versions\3.13.12\python.exe" "回填链接.py"
pause
