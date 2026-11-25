@echo off
chcp 65001 >nul
for %%I in ("%~dp0..") do set "ROOT=%%~fI"
echo [AuroraDesktop] 正在停止已运行的实例并以源码模式启动...
taskkill /F /IM AuroraDesktop.exe /T >nul 2>&1
cd /d "%ROOT%"
python "src\main.py"
pause
