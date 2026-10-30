"""领域异常：让 services 层不依赖 fastapi。

services / protocols 抛 `ApiError`，由 `main.py` 统一翻译成 `{"detail": "..."}` 响应，
状态码与文案和重构前的 `HTTPException` 完全一致，前端无需改动。
"""
from __future__ import annotations


class ApiError(Exception):
    """可直接映射为 HTTP 响应的业务异常。

    入参：
        status_code: 建议的 HTTP 状态码（400 参数问题 / 404 不存在 / 409 未就绪 / 500 内部错误）。
        detail: 面向用户的中文错误文案，会原样出现在响应体的 `detail` 字段。
    边界：`detail` 不包含堆栈信息；内部异常细节由调用方拼进文案。
    """

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"ApiError({self.status_code}, {self.detail!r})"
