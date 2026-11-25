@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ========================================================
echo   AuroraDesktop 一键重新打包并热替换脚本
echo ========================================================
echo [1/3] 正在编译新版本到临时目录 build\dist ...
python -m PyInstaller ^
    --noconfirm ^
    --onefile ^
    --windowed ^
    --name "AuroraDesktop" ^
    --distpath "D:\AuroraDesktop\build\dist" ^
    --workpath "D:\AuroraDesktop\build" ^
    --specpath "D:\AuroraDesktop\build" ^
    --icon "D:\AuroraDesktop\assets\aurora.ico" ^
    --add-data "D:\AuroraDesktop\assets;assets" ^
    --paths "D:\AuroraDesktop\src" ^
    --paths "D:\AuroraDesktop" ^
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
    "D:\AuroraDesktop\src\main.py"

if errorlevel 1 (
    echo [错误] 编译失败，请检查上方报错信息！
    pause
    exit /b 1
)

echo [2/3] 正在关闭旧版进程并替换 AuroraDesktop.exe ...
taskkill /F /IM AuroraDesktop.exe /T >nul 2>&1
timeout /t 1 /nobreak >nul
copy /Y "D:\AuroraDesktop\build\dist\AuroraDesktop.exe" "D:\AuroraDesktop\AuroraDesktop.exe" >nul

echo [3/3] 正在重新启动最新版 AuroraDesktop.exe ...
start "" "D:\AuroraDesktop\AuroraDesktop.exe"
echo [完成] 热更新成功！
timeout /t 2 >nul
