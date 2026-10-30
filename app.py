"""Taozi VLX 调测台 · 入口薄壳。

保留「`python app.py` 就能起服务」的契约：`run.bat` / `debug.bat` / `启动器.exe` 都用这条路径，
所以本文件只做 `sys.path` 兜底 + 转发，不放任何业务代码。真实实现在 `backend/app/`。

启动：
    run.bat            （Windows，使用 VLX-Seek 的 .venv）
    python app.py
端口优先级：命令行参数 > 环境变量 PORT > config.ini > 7860（由 bat / 启动器处理）
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.app.main import app  # noqa: E402 - 必须先补 sys.path 再导入

if __name__ == "__main__":
    import uvicorn

    from backend.app.config import HOST, PORT

    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
