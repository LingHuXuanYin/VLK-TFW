@echo off
rem ============================================================
rem  build_launcher.bat —— 重新打包「启动器.exe」
rem  改了 src\launcher.py 之后双击本脚本即可，产物覆盖到项目根目录
rem  需要：系统 Python 3.10+（带 tkinter）与 PyInstaller
rem        C:\Python310\python.exe -m pip install pyinstaller
rem ============================================================
setlocal
cd /d "%~dp0"

set "PY=C:\Python310\python.exe"
if not exist "%PY%" (
  echo [ERROR] 未找到 %PY%，请改成本机装了 tkinter 的 Python 路径
  pause
  exit /b 1
)

"%PY%" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
  echo [ERROR] 当前 Python 没装 PyInstaller：
  echo         "%PY%" -m pip install pyinstaller
  pause
  exit /b 1
)

echo 正在打包启动器……
"%PY%" -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name VLX-Launcher --icon "assets\launcher.ico" src\launcher.py
if errorlevel 1 (
  echo [ERROR] 打包失败，看上面的输出
  pause
  exit /b 1
)

copy /y "dist\VLX-Launcher.exe" "启动器.exe" >nul
echo.
echo 打包完成：%~dp0启动器.exe
pause
