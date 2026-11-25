@echo off
chcp 65001 >nul
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
cd /d "%ROOT%"
echo ========================================================
echo   AuroraDesktop 一键重新打包并热替换脚本
echo ========================================================
echo [1/3] 正在编译新版本到临时目录 build\dist ...
python -m PyInstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "AuroraDesktop" ^
    --distpath "%ROOT%\build\dist" ^
    --workpath "%ROOT%\build" ^
    --specpath "%ROOT%\build" ^
    --icon "%ROOT%\assets\aurora.ico" ^
    --add-data "%ROOT%\assets;assets" ^
    --paths "%ROOT%\src" ^
    --paths "%ROOT%" ^
    --hidden-import "win32com.client" ^
    --hidden-import "pythoncom" ^
    --hidden-import "pywintypes" ^
    --exclude-module "PySide6.QtWebEngineCore" ^
    --exclude-module "PySide6.QtWebEngineWidgets" ^
    --exclude-module "PySide6.QtQml" ^
    --exclude-module "PySide6.QtQuick" ^
    --exclude-module "PySide6.QtPdf" ^
    --exclude-module "PySide6.QtMultimedia" ^
    --exclude-module "PySide6.QtNetwork" ^
    --exclude-module "PIL" ^
    --exclude-module "fontTools" ^
    --exclude-module "brotli" ^
    --exclude-module "tkinter" ^
    --exclude-module "unittest" ^
    "%ROOT%\src\main.py"

if errorlevel 1 (
    echo [错误] 编译失败，请检查上方报错信息！
    pause
    exit /b 1
)

echo [2/3] 正在关闭旧版进程并替换 AuroraDesktop.exe ...
taskkill /F /IM AuroraDesktop.exe /T >nul 2>&1
timeout /t 1 /nobreak >nul
copy /Y "%ROOT%\build\dist\AuroraDesktop.exe" "%ROOT%\AuroraDesktop.exe" >nul

echo [3/3] 正在重新启动最新版 AuroraDesktop.exe ...
start "" "%ROOT%\AuroraDesktop.exe"
echo [完成] 热更新成功！
timeout /t 2 >nul
