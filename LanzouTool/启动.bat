@echo off
chcp 65001 >nul
title BlueLE No.1 lanzou tool
cd /d "%~dp0"
echo ============================================
echo   lanzou tool - starting...
echo   browser will open automatically
echo   DO NOT close this black window!
echo ============================================
"C:\Users\cyy\.workbuddy\binaries\python\versions\3.13.12\python.exe" lanzou_gui.py
pause
