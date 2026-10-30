@echo off
rem ============================================================
rem  run.bat —— Taozi VLX 调测台（前台运行，日志直接打在窗口里）
rem
rem  用法：
rem    run.bat            端口取 config.ini（默认 7860）
rem    run.bat 8080       本次强制用 8080
rem    set PORT=8080 ^&^& run.bat
rem ============================================================
setlocal
cd /d "%~dp0"

call "%~dp0_env.bat" %1
if errorlevel 1 goto :fail

if not exist "%PY%" (
  echo [ERROR] 未找到 VLX-Seek 虚拟环境：%PY%
  echo         请先按 VLX-Seek 的 使用教程.md 创建 .venv 并安装依赖。
  goto :fail
)

rem 端口已被占用时先提醒一句，避免误以为启动失败
"%SystemRoot%\System32\netstat.exe" -ano -p TCP | "%SystemRoot%\System32\findstr.exe" /r /c:":%VLX_PORT% .*LISTENING" >nul
if not errorlevel 1 (
  echo [WARN] 端口 %VLX_PORT% 已在监听，可能已有实例在跑。
  echo        换个端口：run.bat 7861
  echo.
)

echo ========================================
echo   Taozi VLX 调测台
echo   模型: ..\VLX-Seek\resources\VLX-Seek-1.5-10B
echo   地址: http://%HOST%:%VLX_PORT%
echo   端口来源: 参数 ^> PORT 环境变量 ^> config.ini ^> 7860
echo ========================================
echo.

"%PY%" "%VLX_ENTRY%"
set "EXITCODE=%ERRORLEVEL%"

echo.
echo [服务已退出] 退出码 %EXITCODE%
if not "%EXITCODE%"=="0" echo 报错内容见上方；需要落盘请改用 debug.bat

rem 双击运行时停住窗口，命令行调用不暂停
echo %cmdcmdline% | "%SystemRoot%\System32\find.exe" /i "%~f0" >nul && pause
exit /b %EXITCODE%

:fail
echo %cmdcmdline% | "%SystemRoot%\System32\find.exe" /i "%~f0" >nul && pause
exit /b 1
