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
    QUEUE_ENABLED,
    QUEUE_MAX_RECORDS,
    QUEUE_MAX_SIZE,
    QUEUE_RETRY_AFTER,
    VLX_SEEK_ROOT,
    WEDETECT_PATH,
)
from .protocols.image_store import ImageStore
from .protocols.job_queue import JobQueue
from .protocols.proposal_source import ProposalSource
from .protocols.task_runner import SuiteRunner, TaskRunner
from .services.image_store import LocalImageStore
from .services.job_queue import InMemoryJobQueue
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
# 队列容量等参数来自 config.ini（queue_*），环境变量 VLX_QUEUE_* 可覆盖
_job_queue: JobQueue = InMemoryJobQueue(
    _task_runner,
    _image_store,
    capacity=QUEUE_MAX_SIZE,
    max_records=QUEUE_MAX_RECORDS,
    retry_after=QUEUE_RETRY_AFTER,
    enabled=QUEUE_ENABLED,
)


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


def get_job_queue() -> JobQueue:
    """返回生产消费队列单例（外部服务投递入口的唯一持有者）。"""
    return _job_queue
