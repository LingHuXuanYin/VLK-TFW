"""组装根（composition root）：单例在这里创建，路由通过 `Depends` 取用。

为什么单例放这里而不是 service 内部：模型与 WeDetect 的实例必须进程内唯一（显存 + 434MB 权重），
但 service 自身保持「可注入」以便测试。换实现只需改本文件。
"""
from __future__ import annotations

from .config import (
    DATA_DIR,
    DEVICE_PREFERENCE,
    MAX_IMAGE_SIDE,
    MODEL_PATH,
    VLX_SEEK_ROOT,
    WEDETECT_PATH,
)
from .protocols.image_store import ImageStore
from .protocols.proposal_source import ProposalSource
from .protocols.task_runner import SuiteRunner, TaskRunner
from .services.image_store import LocalImageStore
from .services.model_runtime import ModelRuntime
from .services.suite_runner import DefaultSuiteRunner
from .services.task_runner import DefaultTaskRunner
from .services.wedetect_source import WedetectProposalSource

# -- 单例 ---------------------------------------------------------------
_image_store: ImageStore = LocalImageStore(DATA_DIR, max_side=MAX_IMAGE_SIDE)
_model_runtime: ModelRuntime = ModelRuntime(MODEL_PATH, device_preference=DEVICE_PREFERENCE)
_proposal_source: ProposalSource = WedetectProposalSource(
    WEDETECT_PATH, VLX_SEEK_ROOT, _image_store, DEVICE_PREFERENCE
)
_task_runner: TaskRunner = DefaultTaskRunner(_model_runtime, _image_store, _proposal_source)
_suite_runner: SuiteRunner = DefaultSuiteRunner(_task_runner)


# -- 依赖获取函数（供 FastAPI Depends 使用） --------------------------------
def get_image_store() -> ImageStore:
    """返回图片存储单例。"""
    return _image_store


def get_model_runtime() -> ModelRuntime:
    """返回模型运行时单例（状态机的唯一持有者）。"""
    return _model_runtime


def get_proposal_source() -> ProposalSource:
    """返回候选框来源单例。"""
    return _proposal_source


def get_task_runner() -> TaskRunner:
    """返回单任务执行器单例。"""
    return _task_runner


def get_suite_runner() -> SuiteRunner:
    """返回全量调测执行器单例。"""
    return _suite_runner
