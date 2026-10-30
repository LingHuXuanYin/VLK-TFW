@echo off
rem ============================================================
rem  debug.bat —— Taozi VLX 调测台（后台/无人值守运行，日志落 server.log）
rem  等价于：
rem    cd /d "%~dp0"
rem    set HF_ENDPOINT=https://hf-mirror.com
rem    set VLX_SEEK_BACKEND=nvidia
rem    ...\python.exe src\main.py > server.log 2>&1
rem  区别：端口可配、日志超 20MB 自动归档、退出后回显日志末尾
rem
rem  用法：
rem    debug.bat            端口取 config.ini（默认 7860）
rem    debug.bat 8080
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

rem 日志超过 20MB 先滚动归档，避免无限膨胀
if exist "%VLX_LOG%" for %%F in ("%VLX_LOG%") do if %%~zF GTR 20971520 (
  if exist "%VLX_LOG%.1" del /q "%VLX_LOG%.1"
  move /y "%VLX_LOG%" "%VLX_LOG%.1" >nul
)

echo ========================================
echo   Taozi VLX 调测台（后台模式）
echo   地址: http://%HOST%:%VLX_PORT%
echo   日志: %VLX_LOG%
echo   停止: Ctrl+C
echo ========================================
echo.

"%PY%" "%VLX_ENTRY%" > "%VLX_LOG%" 2>&1
set "EXITCODE=%ERRORLEVEL%"

echo.
echo [服务已退出] 退出码 %EXITCODE%
echo ---- server.log 末尾 15 行 ----
powershell -NoProfile -Command "if (Test-Path '%VLX_LOG%') { Get-Content -LiteralPath '%VLX_LOG%' -Tail 15 -Encoding UTF8 }"

echo %cmdcmdline% | "%SystemRoot%\System32\find.exe" /i "%~f0" >nul && pause
exit /b %EXITCODE%

:fail
echo %cmdcmdline% | "%SystemRoot%\System32\find.exe" /i "%~f0" >nul && pause
exit /b 1
