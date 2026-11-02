"""生产消费队列能力接口：外部服务推图进队列，服务端串行消费。

为什么单独抽一层：队列是**外部系统的边界**，它要同时依赖 `TaskRunner`（跑任务）、
`ImageStore`（落盘）与进程级的调度状态（容量、排队顺序、结果保留）。
把接口放这里，路由只依赖 Protocol，测试时可以换成纯内存假实现。

一致性约定：队列是**进程内内存队列**，不是持久化消息队列。服务重启 = 排队中的任务丢失，
这一点必须在部署文档里说清楚，不能让外部服务误以为投递即送达。
"""
from __future__ import annotations

from typing import Any, Optional, Protocol, TypedDict


class JobSpec(TypedDict, total=False):
    """投递一个队列任务所需的全部入参（与 `RunRequest` 同构，多了图片与任务列表）。

    字段含义：
        tasks: 要跑的任务 id 列表（1~7 个，取自 `/api/meta` 的 7 个任务），串行执行。
        image_id: 已上传图片的 id；与 `image_bytes` 二选一。
        image_bytes: 图片原始字节；外部服务直接推图时传它，服务端负责落盘与缩放。
        filename: 落盘用的原始文件名（仅用于元信息，可为空）。
        text / lang / bbox_list / roi / auto_proposals / target_region_indexes /
        max_new_tokens / temperature / top_p: 与 `RunRequest` 完全一致，逐个透传给任务执行器。
        client_ref: 外部服务自己的业务主键（如设备号+时间戳），仅原样回显，便于对账。
    """

    tasks: list[str]
    image_id: Optional[str]
    image_bytes: Optional[bytes]
    filename: str
    text: Optional[str]
    lang: Optional[str]
    bbox_list: Optional[list[list[float]]]
    roi: Optional[list[list[float]]]
    auto_proposals: bool
    target_region_indexes: Optional[list[int]]
    max_new_tokens: Optional[int]
    temperature: Optional[float]
    top_p: Optional[float]
    client_ref: Optional[str]


class JobQueue(Protocol):
    """内存生产消费队列：`submit` 入队，后台消费者串行执行，`get` 查结果。"""

    async def submit(self, spec: JobSpec) -> dict[str, Any]:
        """校验并把一个任务放进队列，立即返回，不等推理完成。

        入参：`spec` 见 `JobSpec`。
        返回：任务快照 `{job_id, status: "queued", position, capacity, tasks, image_id,
             client_ref, submitted_at}`。
        异常：
            `ApiError(400)` 缺图片 / 任务为空 / 任务 id 未知；
            `ApiError(404)` `image_id` 指向的图片不存在；
            `ApiError(429)` 排队数已达上限（文案含队列现状，响应头带 `Retry-After`）；
            `ApiError(503)` 队列接入被关闭，或消费者未启动。
        边界：容量只算「等待中」的任务，正在推理的那个不占额度；同一进程内串行消费。
        """
        ...

    def get(self, job_id: str) -> dict[str, Any]:
        """按 id 取任务快照（含逐任务结果）。

        入参：`job_id` 为 `submit` 返回的 id。
        返回：`{job_id, status, position, tasks, image_id, client_ref, submitted_at,
             started_at, finished_at, queue_wait_ms, elapsed_ms, progress, results, error}`。
              `status` 取值 queued / running / succeeded / partially_failed / failed。
        异常：`ApiError(404)` id 不存在或记录已被保留上限淘汰。
        """
        ...

    def list(self, status: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        """按状态倒序（新→旧）列出任务快照。

        入参：`status` 为 None 时不过滤；`limit` 上限 200。
        返回：任务快照列表（无结果时为空数组，不抛异常）。
        边界：只返回内存中仍保留的记录，被淘汰的历史任务查不到。
        """
        ...

    def status(self) -> dict[str, Any]:
        """队列运行态汇总，供外部服务判断要不要继续投递。

        返回：`{enabled, consumer_running, capacity, queued, processing, current_job,
             retry_after, retained, max_records, submitted_total, succeeded_total,
             failed_total, rejected_total, tasks_run}`。
        异常：无。
        """
        ...

    async def start(self) -> None:
        """启动后台消费者（服务 lifespan 里调用，幂等）。

        入参：无。返回：无。异常：无（队列关闭时直接返回）。
        """
        ...

    async def stop(self) -> None:
        """停止消费者；正在执行的任务记为失败（`服务关闭中断`），排队中的任务丢弃。

        入参：无。返回：无。异常：无。
        """
        ...
