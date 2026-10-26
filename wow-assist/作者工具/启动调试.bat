@echo off
chcp 65001 >nul
rem ============================================================
rem  WowAssist · 源码调试启动（开发用）
rem  改完 addon_helper.py / ui.html 后直接双击本文件看效果，
rem  免去「打包exe.bat」那一分钟打包。
rem  注意：依赖 pywebview 的解释器必须是下面这个（envs/default）。
rem ============================================================
cd /d "%~dp0.."
set "PYTHONPATH="
set "PY=C:\Users\cyy\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not exist "%PY%" (
  echo [错误] 找不到 python: %PY%
  echo        请改成你机器上装了 pywebview 的 python 路径。
  pause
  exit /b 1
)
echo [调试] 启动 WowAssist 源码版 ...（关掉本窗口即退出）
"%PY%" -u addon_helper.py
echo.
echo [调试] 程序已退出。上面的输出是运行日志。
pause
