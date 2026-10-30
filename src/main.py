"""Taozi VLX 调测台 · 服务入口薄壳。

保留「一条命令就能起服务」的契约：`run.bat` / `debug.bat` / `启动器.exe` 都以
`python src/main.py` 拉起，所以本文件只做 `sys.path` 兜底 + 转发，不放任何业务代码。
真实实现在 `src/backend/app/`，前端在 `src/web/`。

启动：
    run.bat            （Windows，使用 VLX-Seek 的 .venv）
    python src/main.py
端口优先级：命令行参数 > 环境变量 PORT > config.ini > 7860（由 bat / 启动器处理）

边界：`BASE_DIR` 是 `src/`，加进 `sys.path` 后 `backend` 作为顶层包被导入，
因此 `src/backend/` 内部一律写 `from backend.app.xxx import ...`，不写 `from src.backend...`。
"""
from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent  # = src/
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.app.main import app  # noqa: E402 - 必须先补 sys.path 再导入

if __name__ == "__main__":
    import uvicorn

    from backend.app.config import HOST, PORT

    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
