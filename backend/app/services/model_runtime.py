"""模型运行时：异步加载、状态机、worker 单例。

这是后端**唯一**允许持有进程级可变状态的地方（模型只能加载一次，锁必须共享）。
状态机：idle → loading → ready / error（error 下可由前端触发 retry 回到 loading）。
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

from ..errors import ApiError
from ..protocols.worker import VisionWorker
from .device import resolve_device

# worker 工厂：(model_path, device) -> 具备七任务方法的对象
WorkerFactory = Callable[[str, str], VisionWorker]


def default_worker_factory(model_path: str, device: str) -> VisionWorker:
    """从 VLX-Seek 导入真实 worker。

    懒导入：没有 torch 的环境也能起服务、看元数据接口。
    异常：模型目录/依赖缺失时由底层抛出，交给 `ModelRuntime` 记进 error 状态。
    """
    from vlx_seek_worker import VLXSeekWorker  # noqa: PLC0415 - 必须在运行期才导入

    return VLXSeekWorker(model_path, device=device)


class ModelRuntime:
    """`WorkerProvider` 的实现：常驻显存、只加载一次。"""

    def __init__(
        self,
        model_path: str,
        device_preference: str = "auto",
        worker_factory: WorkerFactory = default_worker_factory,
    ) -> None:
        """
        入参：
            model_path: 模型目录。
            device_preference: auto / cuda:0 / cpu。
            worker_factory: 便于测试注入假 worker，默认加载真实 VLX-Seek worker。
        """
        self._model_path = model_path
        self._device_preference = device_preference
        self._factory = worker_factory
        self._worker: Optional[VisionWorker] = None
        self._lock = threading.Lock()          # 保护 _worker / _state 的读写
        self._load_lock = threading.Lock()     # 保证只有一次真实加载在跑
        self._start_lock = threading.Lock()    # 保证只有一个加载线程被拉起
        self._state: dict[str, Any] = {
            "status": "idle",  # idle | loading | ready | error
            "message": "等待加载",
            "error": None,
            "load_seconds": None,
            "loaded_at": None,
            "model_path": model_path,
            "device": None,
        }

    # -- 对外能力 -----------------------------------------------------------
    @property
    def model_path(self) -> str:
        """当前配置的模型目录（`/api/meta` 展示用）。"""
        return self._model_path

    def status(self) -> dict[str, Any]:
        """见 `WorkerProvider.status`。返回快照副本，含解析后的实际设备。"""
        with self._lock:
            snapshot = dict(self._state)
        snapshot["device"] = snapshot["device"] or self.resolved_device()
        return snapshot

    def resolved_device(self) -> str:
        """把设备偏好解析成实际设备（auto → cuda:0 / cpu）。"""
        return resolve_device(self._device_preference)

    def start_loading(self, retry: bool = False) -> None:
        """见 `WorkerProvider.start_loading`。幂等：loading/ready 直接返回。"""
        with self._start_lock:
            with self._lock:
                status = self._state["status"]
                if status == "ready" or status == "loading":
                    return
                if status == "error" and not retry:
                    return
                self._state.update(status="loading", message="正在加载模型…", error=None)
            threading.Thread(
                target=self._load, daemon=True, name="vlx-model-loader"
            ).start()

    def require(self) -> VisionWorker:
        """见 `WorkerProvider.require`。未就绪时顺带触发加载再报 409。"""
        with self._lock:
            worker = self._worker
            status = self._state["status"]
            error = self._state["error"]
        if worker is not None:
            return worker
        if status == "error":
            raise ApiError(500, f"模型加载失败：{error}")
        self.start_loading()
        raise ApiError(409, "模型正在加载，请稍候（首次加载约 1 分钟），状态会自动刷新。")

    # -- 内部实现 -----------------------------------------------------------
    def _load(self) -> None:
        """后台线程里执行真实加载，结果写进状态机。"""
        with self._load_lock:
            started = time.time()
            try:
                device = self.resolved_device()
                worker = self._factory(self._model_path, device)
            except Exception as exc:  # noqa: BLE001 - 任何加载异常都要变成可读状态
                with self._lock:
                    self._state.update(
                        status="error",
                        message="模型加载失败",
                        error=f"{type(exc).__name__}: {exc}",
                    )
                return
            with self._lock:
                self._worker = worker
                self._state.update(
                    status="ready",
                    message="模型已就绪",
                    device=str(device),
                    load_seconds=round(time.time() - started, 1),
                    loaded_at=time.strftime("%Y-%m-%d %H:%M:%S"),
                )
