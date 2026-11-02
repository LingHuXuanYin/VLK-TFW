"""领域异常：让 services 层不依赖 fastapi。

services / protocols 抛 `ApiError`，由 `main.py` 统一翻译成 `{"detail": "..."}` 响应，
状态码与文案和重构前的 `HTTPException` 完全一致，前端无需改动。
"""
from __future__ import annotations

from typing import Optional


class ApiError(Exception):
    """可直接映射为 HTTP 响应的业务异常。

    入参：
        status_code: 建议的 HTTP 状态码（400 参数问题 / 404 不存在 / 409 未就绪 /
                     429 队列超限 / 500 内部错误 / 503 能力关闭）。
        detail: 面向用户的中文错误文案，会原样出现在响应体的 `detail` 字段。
        headers: 需要附加的响应头，目前只有队列超限用（`Retry-After`）；其余场景传 None。
    边界：`detail` 不包含堆栈信息；内部异常细节由调用方拼进文案。
    """

    def __init__(
        self, status_code: int, detail: str, headers: Optional[dict[str, str]] = None
    ) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.headers = headers

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"ApiError({self.status_code}, {self.detail!r})"
