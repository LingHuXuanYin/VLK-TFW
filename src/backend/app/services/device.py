"""设备解析：模型与 WeDetect 共用同一套「auto → cuda:0 / cpu」规则。"""
from __future__ import annotations


def resolve_device(preference: str = "auto") -> str:
    """把设备偏好解析成实际设备字符串。

    入参：preference 为 `auto` / `cuda:0` / `cpu` 等；`auto` 时探测 cuda 可用性。
    返回：可直接传给 torch 的设备字符串。
    异常：不抛异常——没装 torch 或探测失败一律退化为 `cpu`。
    """
    if preference and preference != "auto":
        return preference
    try:
        import torch

        return "cuda:0" if torch.cuda.is_available() else "cpu"
    except Exception:  # noqa: BLE001 - 无 torch 环境也要能起服务（只跑元数据接口）
        return "cpu"
