@echo off
rem ============================================================
rem  _env.bat —— run.bat / debug.bat 共用的环境准备（不是给人双击的）
rem  用法：call "%~dp0_env.bat" [端口]
rem  导出：PY / VLX_PORT / HOST / PORT / VLX_LOG 及模型所需环境变量
rem  注意：这里不写 setlocal，变量要留在调用方作用域里
rem ============================================================

set "VLX_HOME=%~dp0"
set "PY=%VLX_HOME%..\VLX-Seek\.venv\Scripts\python.exe"
set "VLX_LOG=%VLX_HOME%server.log"

rem ---- 与 VLX-Seek 官方推理脚本一致的环境变量 ----
set "HF_ENDPOINT=https://hf-mirror.com"
set "HF_HUB_DISABLE_XET=1"
set "HF_HUB_ENABLE_HF_TRANSFER=0"
set "VLX_SEEK_BACKEND=nvidia"
set "PYTHONUNBUFFERED=1"
set "PYTHONIOENCODING=utf-8"

rem ---- 端口优先级：命令行参数 > 环境变量 PORT > config.ini > 7860 ----
set "VLX_PORT="
if not "%~1"=="" set "VLX_PORT=%~1"
if not defined VLX_PORT if defined PORT set "VLX_PORT=%PORT%"
if not defined VLX_PORT if exist "%VLX_HOME%config.ini" (
  for /f "usebackq eol=; tokens=1,2 delims==" %%A in ("%VLX_HOME%config.ini") do (
    if /i "%%A"=="port" set "VLX_PORT=%%B"
  )
)
if not defined VLX_PORT set "VLX_PORT=7860"
rem 去掉首尾空格（启动器写文件时可能带空格）
set "VLX_PORT=%VLX_PORT: =%"

rem ---- 端口合法性：纯数字、无前导 0、不超过 5 位、1~65535 ----
echo %VLX_PORT%| findstr /r "^[1-9][0-9]*$" >nul
if errorlevel 1 (
  echo [ERROR] 端口必须是正整数：%VLX_PORT%
  exit /b 1
)
if not "%VLX_PORT:~5%"=="" (
  echo [ERROR] 端口超出范围 1~65535：%VLX_PORT%
  exit /b 1
)
set /a "VLX_PORT_NUM=%VLX_PORT%"
if %VLX_PORT_NUM% GTR 65535 (
  echo [ERROR] 端口超出范围 1~65535：%VLX_PORT%
  exit /b 1
)

rem ---- 监听地址（默认只本机；config.ini 里改 host 可放局域网）----
set "HOST=127.0.0.1"
if exist "%VLX_HOME%config.ini" (
  for /f "usebackq eol=; tokens=1,2 delims==" %%A in ("%VLX_HOME%config.ini") do (
    if /i "%%A"=="host" set "HOST=%%B"
  )
)
set "HOST=%HOST: =%"
if not defined HOST set "HOST=127.0.0.1"

set "PORT=%VLX_PORT%"
exit /b 0
