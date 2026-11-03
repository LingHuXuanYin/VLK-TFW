"""排队图的本地磁盘实现：`data/image_queue/` 下的原图 + sidecar。

目录布局（root = `data/image_queue`）：
    {job_id}.json     排队记录（任务、参数、client_ref、提交时间、attempts）
    {job_id}.png      推上来的原图（扩展名按白名单保留，未知类型落成 .bin）
    {job_id}.json.tmp 写入过程中的临时文件，`os.replace` 后消失
    failed/
      {job_id}.json   失败件的 sidecar，额外带 `error` 与 `failed_at`
      {job_id}.png    失败件的原图

只有这里碰 `image_queue` 目录；`job_queue` 通过 `JobSpool` 契约调用，不直接拼路径。
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from ..errors import ApiError

# 只保留常见图片后缀：`filename` 来自外部服务，直接拿来做文件名会把 `../` 或 `x.png.exe` 带进来
_ALLOWED_SUFFIXES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"})
_FAILED_DIRNAME = "failed"


class LocalJobSpool:
    """`JobSpool` 的本地磁盘实现（原子写 + 失败件隔离）。"""

    def __init__(self, root: Path) -> None:
        """
        入参：root 为排队目录，不存在则连同 `failed/` 子目录一起创建。
        异常：目录无法创建时抛 `OSError`（启动即失败，不留半可用状态）。
        """
        self._root = Path(root)
        self._failed = self._root / _FAILED_DIRNAME
        self._root.mkdir(parents=True, exist_ok=True)
        self._failed.mkdir(parents=True, exist_ok=True)

    # -- 对外能力 -----------------------------------------------------------
    def put(
        self,
        job_id: str,
        *,
        image_bytes: Optional[bytes],
        filename: str,
        meta: dict[str, Any],
    ) -> Optional[str]:
        """见 `JobSpool.put`。"""
        image_file: Optional[str] = None
        sidecar = dict(meta)
        sidecar["job_id"] = job_id
        try:
            if image_bytes:
                image_file = f"{job_id}{_safe_suffix(filename)}"
                _atomic_write_bytes(self._root / image_file, bytes(image_bytes))
            sidecar["image_file"] = image_file
            _atomic_write_text(
                self._sidecar_path(job_id), json.dumps(sidecar, ensure_ascii=False, indent=2)
            )
        except OSError as exc:
            # 原图可能已写成功但 sidecar 没写：调用方会拿到 500，图成为孤儿文件，
            # 由运维按 docs/deployment.md 的「孤儿文件检查」清理。
            raise ApiError(500, f"排队图片写入磁盘失败：{exc}") from exc
        return image_file

    def read_image(self, job_id: str) -> bytes:
        """见 `JobSpool.read_image`。"""
        entry = self.read(job_id)
        if entry is None:
            raise ApiError(410, f"排队记录不存在或已损坏：{job_id}，请重新投递。")
        name = entry.get("image_file")
        if not name:
            raise ApiError(410, f"排队记录没有原图：{job_id}（该任务复用图像库里的图片）。")
        path = self._root / str(name)
        if not path.is_file():
            raise ApiError(410, f"排队中的原图已被清理：{name}，请重新投递。")
        try:
            return path.read_bytes()
        except OSError as exc:
            raise ApiError(500, f"读取排队中的原图失败：{exc}") from exc

    def read(self, job_id: str) -> Optional[dict[str, Any]]:
        """见 `JobSpool.read`。"""
        path = self._sidecar_path(job_id)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def discard(self, job_id: str) -> None:
        """见 `JobSpool.discard`。"""
        # sidecar 损坏时读不到原图名，因此按 job_id 前缀清理同批文件，避免留孤儿
        for path in self._root.glob(f"{job_id}.*"):
            if path.is_file() and path.suffix != ".tmp":
                _unlink(path)
        _unlink(self._sidecar_path(job_id))

    def update(self, job_id: str, patch: dict[str, Any]) -> None:
        """见 `JobSpool.update`。"""
        entry = self.read(job_id)
        if entry is None:
            return
        entry.update(patch)
        try:
            _atomic_write_text(
                self._sidecar_path(job_id), json.dumps(entry, ensure_ascii=False, indent=2)
            )
        except OSError:
            # 回填失败只影响重启后能不能跳过重复搬运，不影响本次执行
            pass

    def fail(self, job_id: str, error: str) -> Optional[str]:
        """见 `JobSpool.fail`。"""
        entry = dict(self.read(job_id) or {"job_id": job_id})
        entry["job_id"] = job_id
        entry["error"] = error
        entry["failed_at"] = _now_iso()
        try:
            entry["attempts"] = int(entry.get("attempts") or 0)
        except (TypeError, ValueError):
            entry["attempts"] = 0
        name = entry.get("image_file")
        try:
            target = self._failed / f"{job_id}.json"
            _atomic_write_text(target, json.dumps(entry, ensure_ascii=False, indent=2))
            if name:
                source = self._root / str(name)
                if source.is_file():
                    source.replace(self._failed / str(name))
        except OSError:
            # 磁盘问题不该让消费者协程崩掉：原件留在原地，下次启动会再次尝试
            return None
        _unlink(self._sidecar_path(job_id))
        return f"{job_id}.json"

    def list_entries(self) -> list[dict[str, Any]]:
        """见 `JobSpool.list_entries`。"""
        items: list[dict[str, Any]] = []
        for path in self._root.glob("*.json"):
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and data.get("job_id"):
                items.append(data)
        items.sort(key=lambda entry: (str(entry.get("submitted_at") or ""), str(entry["job_id"])))
        return items

    def stats(self) -> dict[str, Any]:
        """见 `JobSpool.stats`。"""
        pending = 0
        total_bytes = 0
        try:
            for path in self._root.iterdir():
                if path.is_file() and path.suffix != ".tmp":
                    pending += 1
                    total_bytes += path.stat().st_size
        except OSError:
            return {"pending": 0, "failed": 0, "bytes": 0}
        failed = 0
        try:
            for path in self._failed.iterdir():
                if path.is_file():
                    failed += 1
                    total_bytes += path.stat().st_size
        except OSError:
            failed = 0
        return {"pending": pending, "failed": failed, "bytes": total_bytes}

    # -- 内部实现 -----------------------------------------------------------
    def _sidecar_path(self, job_id: str) -> Path:
        """排队记录的 sidecar 路径（`{job_id}.json`）。"""
        return self._root / f"{job_id}.json"


def _safe_suffix(filename: str) -> str:
    """从原始文件名取安全后缀：命中白名单才保留，否则落成 `.bin`（PIL 靠文件头识别格式）。"""
    suffix = Path(str(filename or "")).suffix.lower()
    return suffix if suffix in _ALLOWED_SUFFIXES else ".bin"


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """先写 `.tmp` 再 `os.replace`，保证读到的永远是完整文件。"""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _atomic_write_text(path: Path, text: str) -> None:
    """同上，写文本（UTF-8）。"""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _unlink(path: Path) -> None:
    """删除文件；不存在时静默返回。"""
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


def _now_iso() -> str:
    """本地时区时间戳，形如 `2026-11-02T10:30:00+08:00`。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")
