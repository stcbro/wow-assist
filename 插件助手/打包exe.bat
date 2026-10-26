@echo off
chcp 65001 >nul
rem ============================================================
rem  魔兽助手 exe 打包脚本（单文件 + 无窗口）
rem  用法：改完 addon_helper.py / ui.html 后，双击本文件重新生成
rem  产物名含版本号：魔兽助手 v<版本>.exe（版本取自 addon_helper.py 的 APP_VERSION）
rem  发版只需改 addon_helper.py 的 APP_VERSION，本脚本会自动带版本号
rem ============================================================
cd /d "%~dp0"

set PY=C:\Users\cyy\.workbuddy\binaries\python\envs\default\Scripts\python.exe

rem 从 addon_helper.py 提取单一版本号（APP_VERSION = "x.y"）；提取失败则回退 3.11
set "APPVER="
for /f "usebackq tokens=2 delims== " %%v in (`findstr /R /C:"APP_VERSION = " addon_helper.py 2^>nul`) do set "APPVER=%%v"
if defined APPVER set "APPVER=%APPVER:"=%"
if not defined APPVER set "APPVER=3.11"
echo [版本] APPVER=%APPVER%

rem 清理旧产物
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

"%PY%" -m PyInstaller ^
  --onefile ^
  --windowed ^
  --name "魔兽助手 v%APPVER%" ^
  --icon capy.ico ^
  --add-data "ui.html;." ^
  --add-data "capy.ico;." ^
  --collect-all webview ^
  --collect-all pythonnet ^
  --collect-all clr_loader ^
  --hidden-import bottle ^
  --hidden-import proxy_tools ^
  --clean ^
  --noconfirm ^
  addon_helper.py

if errorlevel 1 (
  echo.
  echo [打包失败] 请看上方错误信息
  pause
  exit /b 1
)

echo.
echo [打包成功] dist\魔兽助手 v%APPVER%.exe
rem 顺手把带版本号的 exe 拷到本目录，和 config.json 作伴（这是唯一交付副本，文件名含版本号一目了然）
copy /y "dist\魔兽助手 v%APPVER%.exe" "魔兽助手 v%APPVER%.exe" >nul
echo [已复制] 魔兽助手 v%APPVER%.exe（本目录，双击即用）
rem 清理可重生成的构建中间产物，避免和根目录 exe 重复（dist/build 下次打包会自动重建）
rmdir /s /q build >nul 2>&1
rmdir /s /q dist >nul 2>&1
echo [已清理] dist/ 与 build/（可重生成，根目录保留唯一带版本号 exe）

rem ------------------------------------------------------------
rem  一键上传到蓝奏云（可跳过）
rem  需要先设置环境变量（只在你自己的电脑上设，别提交）：
rem     set LZ_USER=你的蓝奏云账号
rem     set LZ_PW=你的蓝奏云密码      （注意用 LZ_PW，别用 LZ_PASS）
rem  未设置则跳过上传，不影响打包结果。
rem ------------------------------------------------------------
if not defined LZ_USER goto NOUPLOAD
if not defined LZ_PW goto NOUPLOAD
echo.
echo [上传] 正在上传到蓝奏云 ...
set "PYTHONPATH="
rem 1) 专用文件夹（干净，只有 exe）
"%PY%" 上传蓝奏云.py --folder "魔兽助手" --prune
rem 2) 分发文件夹（已有对外分享链接，新电脑可直接下载）
"%PY%" 上传蓝奏云.py --folder "乌龟服资源包20261025" --prune
echo [上传] 完成
goto DONEUPLOAD

:NOUPLOAD
echo.
echo [上传] 已跳过：未设置环境变量 LZ_USER / LZ_PW
echo        需要上传时，在本窗口先执行：
echo            set LZ_USER=你的账号
echo            set LZ_PW=你的密码
echo        然后重新运行本脚本；或直接执行：python 上传蓝奏云.py

:DONEUPLOAD
pause
