"""单任务执行：参数校验 → 候选框解析 → 派发到 worker → 生成警告。

这是七任务的核心业务逻辑，只依赖三个 Protocol（worker / 图片存储 / 候选框来源），
因此可以用假 worker 完整单测。
"""
from __future__ import annotations

import threading
import time
from typing import Any, Mapping, Optional

from PIL import Image

from ..errors import ApiError
from ..protocols.image_store import ImageStore
from ..protocols.proposal_source import ProposalSource
from ..protocols.worker import WorkerProvider, VisionWorker
from .task_catalog import REGION_TASK_IDS, get_task


class DefaultTaskRunner:
    """`TaskRunner` 的实现：串行执行，进程内加锁。"""

    def __init__(
        self,
        workers: WorkerProvider,
        image_store: ImageStore,
        proposals: ProposalSource,
    ) -> None:
        """
        入参：
            workers: 提供已就绪的 worker（未就绪时由它抛 409/500）。
            image_store: 读取图片与候选框缓存。
            proposals: 候选框来源（未传 bbox_list 时自动生成）。
        """
        self._workers = workers
        self._store = image_store
        self._proposals = proposals
        self._infer_lock = threading.Lock()

    # -- 对外能力 -----------------------------------------------------------
    @property
    def is_busy(self) -> bool:
        """见 `TaskRunner.is_busy`。"""
        return self._infer_lock.locked()

    def run(self, task_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """见 `TaskRunner.run`。"""
        task = get_task(task_id)
        if task is None:
            raise ApiError(404, f"未知任务：{task_id}")

        worker = self._workers.require()  # 未就绪：409（加载中）或 500（加载失败）
        params = _task_params(task, payload)
        image_id = payload.get("image_id")
        if not image_id:
            raise ApiError(400, "缺少 image_id。")
        image = self._store.load(str(image_id))

        text = payload.get("text")
        if text is None:
            text = task["default_text"]
        text = str(text).strip()

        boxes: Optional[list[list[float]]] = None
        boxes_source = "none"
        if task["needs_bbox"]:
            boxes, boxes_source = self._resolve_boxes(str(image_id), image, payload)
            if not boxes:
                raise ApiError(
                    400,
                    f"{task['name']} 需要候选框：请先上传图片并生成 WeDetect 候选框，"
                    "或手动传入 bbox_list。",
                )

        indexes: Optional[list[int]] = payload.get("target_region_indexes")
        if task["needs_index"]:
            if not indexes:
                raise ApiError(
                    400,
                    f"{task['name']} 需要 target_region_indexes，请在左侧图上点选至少一个候选框。",
                )
            if any(isinstance(i, bool) or not isinstance(i, int) for i in indexes):
                raise ApiError(400, "target_region_indexes 必须是整数数组，例如 [0, 2]。")

        if task_id != "vqa" and not text and task_id not in REGION_TASK_IDS:
            raise ApiError(400, f"{task['name']} 的 text 不能为空。")

        started = time.perf_counter()
        result = self._dispatch(worker, task_id, image, boxes, indexes, text, params)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)

        return {
            "ok": True,
            "task": task_id,
            "task_name": task["name"],
            "answer": result.get("answer", ""),
            "result_bbox_list": result.get("result_bbox_list", []),
            "prompt_tokens": result.get("prompt_tokens", 0),
            "completion_tokens": result.get("completion_tokens", 0),
            "elapsed_ms": elapsed_ms,
            "prompt": _prompt_preview(task_id, text, params["lang"], indexes),
            "lang": params["lang"],
            "text": text,
            "max_new_tokens": params["max_new_tokens"],
            "temperature": params["temperature"],
            "top_p": params["top_p"],
            "boxes_source": boxes_source,
            "boxes_count": len(boxes) if boxes else 0,
            "target_region_indexes": indexes if task["needs_index"] else None,
            "warnings": _warnings(task_id, result, text, params),
        }

    # -- 内部实现 -----------------------------------------------------------
    def _resolve_boxes(
        self, image_id: str, image: Image.Image, payload: Mapping[str, Any]
    ) -> tuple[Optional[list[list[float]]], str]:
        """决定本次用哪组候选框。

        返回：(boxes, source)。source 取值 request / wedetect / wedetect-cache / none。
        优先级：请求显式传入 > 磁盘缓存 > 现场 WeDetect 生成（生成后写缓存）。
        """
        boxes = payload.get("bbox_list")
        if boxes:
            return boxes, "request"
        if not payload.get("auto_proposals", True):
            return None, "none"
        proposal = self._proposals.get(image_id, image)
        source = "wedetect-cache" if proposal.source == "cache" else "wedetect"
        return proposal.boxes, source

    def _dispatch(
        self,
        worker: VisionWorker,
        task_id: str,
        image: Image.Image,
        boxes: Optional[list[list[float]]],
        indexes: Optional[list[int]],
        text: str,
        params: Mapping[str, Any],
    ) -> dict[str, Any]:
        """按 task_id 选 worker 方法。任务串行执行，避免显存竞争。"""
        gen = {
            "max_new_tokens": params["max_new_tokens"],
            "temperature": params["temperature"],
            "top_p": params["top_p"],
        }
        try:
            with self._infer_lock:
                if task_id == "vqa":
                    return worker.predict(image, text, bbox_list=boxes, **gen)
                if task_id == "detection":
                    return worker.detect(image, boxes, text, lang=params["lang"], **gen)
                if task_id == "grounding_single":
                    return worker.ground(image, boxes, text, lang=params["lang"], **gen)
                if task_id == "counting":
                    return worker.count(image, boxes, text, lang=params["lang"], **gen)
                if task_id == "reasoning_detection":
                    return worker.reasoning_detect(image, boxes, text, lang=params["lang"], **gen)
                if task_id == "brief_region_caption":
                    return worker.describe_region(image, boxes, indexes, lang=params["lang"], **gen)
                if task_id == "region_ocr":
                    return worker.read_region_text(image, boxes, indexes, lang=params["lang"], **gen)
        except ApiError:
            raise
        except ValueError as exc:
            raise ApiError(400, f"参数校验失败：{exc}") from exc
        except Exception as exc:  # noqa: BLE001 - 推理异常统一转 500，保留类型名便于查
            raise ApiError(500, f"推理失败：{type(exc).__name__}: {exc}") from exc
        raise ApiError(404, f"未知任务：{task_id}")


def _task_params(task: Mapping[str, Any], payload: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """合并请求参数与任务默认值，并校验 lang。

    入参：task 为任务定义；payload 为用户请求（可为 None 或空）。
    返回：含 lang / max_new_tokens / temperature / top_p 的 dict。
    异常：lang 不是 en/zh 抛 `ApiError(400)`。
    """
    req: Mapping[str, Any] = payload or {}
    lang = req.get("lang") or task["default_lang"]
    if lang not in ("en", "zh"):
        raise ApiError(400, f"lang 只支持 en / zh，收到：{lang}")
    return {
        "lang": lang,
        "max_new_tokens": int(req.get("max_new_tokens") or task["default_max_new_tokens"]),
        "temperature": float(
            task["default_temperature"] if req.get("temperature") is None else req["temperature"]
        ),
        "top_p": float(
            req["top_p"] if req.get("top_p") is not None else task.get("default_top_p", 1.0)
        ),
    }


def _warnings(
    task_id: str, result: Mapping[str, Any], text: str, params: Mapping[str, Any]
) -> list[str]:
    """按任务给出已知坑提示。永不为空抛异常，解析失败时静默降级。"""
    warnings: list[str] = []
    if task_id == "reasoning_detection":
        if params["max_new_tokens"] < 1024:
            warnings.append("max_new_tokens < 1024，思考链可能被截断，<answer> 标签可能出不来。")
        labels = {b.get("label") for b in result.get("result_bbox_list", [])}
        if len(labels) <= 1 and len(text.split(";")) > 1:
            warnings.append("多类别被合并成同一段 <ground>，label 无法区分类别。")
    if task_id == "grounding_single" and len(result.get("result_bbox_list", [])) == 1:
        warnings.append("该任务永远返回 1 个框，无法区分“找到了”和“没找到”。")
    if task_id == "region_ocr":
        warnings.append("模型无法判断区域内是否有文字，请人工核对结果。")
    return warnings


def _prompt_preview(
    task_id: str, text: str, lang: str, indexes: Optional[list[int]]
) -> str:
    """复现模板填充结果，供前端「提示词」面板展示。

    直接调 VLX-Seek 的 `build_prompt` 保证与真实推理一致；导入失败时退化为原始 text。
    区域任务的 text 由索引拼成 `<obj0><obj2>`。
    """
    try:
        from vlx_seek.task_templates import build_prompt  # noqa: PLC0415 - 与推理侧同源

        if task_id == "vqa":
            return text
        if task_id in REGION_TASK_IDS:
            text = "".join(f"<obj{i}>" for i in (indexes or []))
        return build_prompt("vlx_seek_1_5", task_id, text, lang=lang)
    except Exception:  # noqa: BLE001 - 预览失败不影响主流程
        return text
