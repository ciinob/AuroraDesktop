@echo off
chcp 65001 >nul
echo [AuroraDesktop] 正在停止已运行的 exe 实例并以源码调试模式启动...
taskkill /F /IM AuroraDesktop.exe /T >nul 2>&1
cd /d "%~dp0"
python "src\main.py"
pause
