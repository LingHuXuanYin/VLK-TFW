"""电子围栏几何：多边形归一化、外接矩形、面积、包围盒过滤、围栏外灰化。

本模块是围栏能力的**唯一**几何实现，只做数学与像素操作，不碰 HTTP、不碰模型。
`Backend` 侧的候选框裁剪与过滤都走这里；前端另有一份等价实现
（`features/fence/fence-geometry.js`），两边算法刻意保持一致。

坐标口径与候选框完全一致：原图（落盘图）像素坐标，原点在左上角。
"""
from __future__ import annotations

import hashlib
import math
from typing import Optional, Sequence

from PIL import Image, ImageDraw

from ..errors import ApiError

Point = Sequence[float]
Rect = tuple[float, float, float, float]

# 围栏外灰化的填充色。取 128 是因为它接近 ImageNet 均值，
# 模型不会把它当成某个物体；纯黑容易被读成阴影或背景，纯白容易诱发“空白区域”描述。
MASK_FILL = (128, 128, 128)

# 裁剪区域的最小边长（像素）。围栏画得很小时直接裁会把模型输入放大成纯噪声，
# 因此向外扩到这个尺寸再裁。
MIN_CROP_SIDE = 64

# 围栏面积占整图比例的下限。低于此值不做裁剪、退回整图推理后过滤，
# 避免把极小区域放大到模型输入尺寸后产生大量误检。
MIN_CROP_AREA_RATIO = 0.005

# 判定“框属于围栏内”的面积占比阈值：交集面积 ≥ 框面积的一半即保留。
BOX_KEEP_RATIO = 0.5


def normalize(roi: Optional[Sequence[Point]], size: tuple[int, int]) -> Optional[list[list[float]]]:
    """把前端传来的多边形规整成可用的顶点列。

    入参：
        roi: `[[x, y], ...]` 原图像素坐标，可为 None。
        size: 落盘图尺寸 `(width, height)`，用于把越界顶点夹回图内。
    返回：去重后的顶点列；roi 为空返回 None。
    异常：顶点不足 3 个、顶点坐标非法、围栏面积过小，抛 `ApiError(400)`。
    """
    if not roi:
        return None

    raw = list(roi)
    if len(raw) < 3:
        raise ApiError(400, "围栏至少需要 3 个顶点。")

    width, height = float(size[0]), float(size[1])
    points: list[list[float]] = []
    for item in raw:
        if len(item) != 2:
            raise ApiError(400, "围栏顶点必须是 [x, y] 两个数字。")
        try:
            x, y = float(item[0]), float(item[1])
        except (TypeError, ValueError) as exc:
            raise ApiError(400, "围栏顶点必须是数字。") from exc
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ApiError(400, "围栏顶点坐标必须是有限数值。")
        points.append([min(max(x, 0.0), width), min(max(y, 0.0), height)])

    deduped = _drop_duplicate_points(points)
    if len(deduped) < 3:
        raise ApiError(400, "围栏顶点重合过多，至少需要 3 个不同的点。")

    if polygon_area(deduped) < width * height * 1e-5:
        raise ApiError(400, "围栏面积过小，请画大一些。")
    return deduped


def digest(points: Sequence[Point]) -> str:
    """围栏指纹，用于隔离候选框缓存。

    为什么必须有：候选框按 `image_id` 缓存，同一张图画不同围栏时必须各存一份，
    否则「先跑整图、再画围栏」会命中整图那份缓存，表现为围栏完全没生效。
    """
    payload = ";".join(f"{float(p[0]):.1f},{float(p[1]):.1f}" for p in points)
    return hashlib.md5(payload.encode("utf-8")).hexdigest()[:10]


def polygon_area(points: Sequence[Point]) -> float:
    """多边形面积（鞋带公式取绝对值）。顶点顺序（顺/逆时针）不影响结果。"""
    total = 0.0
    count = len(points)
    for index in range(count):
        x1, y1 = float(points[index][0]), float(points[index][1])
        x2, y2 = float(points[(index + 1) % count][0]), float(points[(index + 1) % count][1])
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def bounds(
    points: Sequence[Point], size: tuple[int, int], pad: int = 8
) -> tuple[int, int, int, int]:
    """围栏外接矩形（整数裁剪框），用于裁剪推理。

    入参：
        points: 已 normalize 的顶点列。
        size: 图像尺寸。
        pad: 外扩像素。贴边的目标若被裁掉一半，候选框会偏小甚至完全漏掉。
    返回：`(left, top, right, bottom)`，已夹在图像范围内。
    """
    width, height = size
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    left = max(0, int(math.floor(min(xs))) - pad)
    top = max(0, int(math.floor(min(ys))) - pad)
    right = min(width, int(math.ceil(max(xs))) + pad)
    bottom = min(height, int(math.ceil(max(ys))) + pad)
    return left, top, right, bottom


def should_crop(points: Sequence[Point], size: tuple[int, int]) -> bool:
    """围栏足够大才裁剪推理，否则退回整图。

    判据：外接矩形面积占整图 ≥ `MIN_CROP_AREA_RATIO`，且两条边都不小于 `MIN_CROP_SIDE`。
    过小的围栏裁剪后等于把一小块噪声放大到模型输入尺寸，误检会明显变多。
    """
    left, top, right, bottom = bounds(points, size, pad=0)
    crop_area = max(0, right - left) * max(0, bottom - top)
    if crop_area < size[0] * size[1] * MIN_CROP_AREA_RATIO:
        return False
    return (right - left) >= MIN_CROP_SIDE and (bottom - top) >= MIN_CROP_SIDE


def point_in_polygon(x: float, y: float, points: Sequence[Point]) -> bool:
    """射线法判断点是否在多边形内。边界上的点判定为在内。"""
    inside = False
    count = len(points)
    for index in range(count):
        x1, y1 = float(points[index][0]), float(points[index][1])
        x2, y2 = float(points[(index + 1) % count][0]), float(points[(index + 1) % count][1])
        if _on_segment(x, y, x1, y1, x2, y2):
            return True
        if (y1 > y) != (y2 > y):
            cross_x = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < cross_x:
                inside = not inside
    return inside


def clip_polygon_to_rect(points: Sequence[Point], rect: Rect) -> list[list[float]]:
    """Sutherland–Hodgman：把多边形裁剪到矩形内，返回交集多边形。

    矩形是凸的，满足该算法的前提；围栏可以是任意简单多边形（含凹形）。
    返回空列表表示没有交集。
    """
    left, top, right, bottom = rect
    output = [[float(p[0]), float(p[1])] for p in points]

    for edge in ("left", "right", "top", "bottom"):
        if not output:
            return []
        source = output
        output = []
        previous = source[-1]
        for current in source:
            cur_in = _inside_edge(current, edge, left, top, right, bottom)
            prev_in = _inside_edge(previous, edge, left, top, right, bottom)
            if cur_in:
                if not prev_in:
                    output.append(_intersect_edge(previous, current, edge, left, top, right, bottom))
                output.append(current)
            elif prev_in:
                output.append(_intersect_edge(previous, current, edge, left, top, right, bottom))
            previous = current
    return output


def contains_ratio(box: Sequence[float], points: Sequence[Point]) -> float:
    """候选框落在围栏内的面积占该框面积的比例，取值 0..1。

    精确算法：框 ∩ 围栏多边形 → 鞋带公式求面积 / 框面积。
    比抽样法稳：细长围栏、斜向围栏下抽样会误判。
    """
    x1, y1, x2, y2 = (float(box[0]), float(box[1]), float(box[2]), float(box[3]))
    box_area = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if box_area <= 0:
        return 0.0
    clipped = clip_polygon_to_rect(points, (x1, y1, x2, y2))
    if len(clipped) < 3:
        return 0.0
    return min(1.0, polygon_area(clipped) / box_area)


def filter_boxes(
    boxes: Sequence[Sequence[float]], points: Sequence[Point], min_ratio: float = BOX_KEEP_RATIO
) -> list[list[float]]:
    """只保留属于围栏的候选框。

    规则（取并集，宁可多留）：交集占比 ≥ `min_ratio`，或框中心点在围栏内。
    只看中心点会漏掉「框很大、主体在围栏内但中心落在围栏外」的情况；
    只看占比会漏掉「框贴着围栏边界、大部分在围栏内」的情况。
    """
    kept: list[list[float]] = []
    for box in boxes:
        values = [float(v) for v in box]
        center_x = (values[0] + values[2]) / 2.0
        center_y = (values[1] + values[3]) / 2.0
        if point_in_polygon(center_x, center_y, points) or contains_ratio(values, points) >= min_ratio:
            kept.append(values)
    return kept


def mask_outside(image: Image.Image, points: Sequence[Point]) -> Image.Image:
    """把围栏外的像素填成中灰，尺寸保持不变。

    为什么不裁剪：裁剪会改变坐标原点，候选框与模型输出都得跟着做偏移映射；
    灰化保持画布尺寸不变，坐标体系零变动，而模型在物理上同样看不到围栏外内容。
    """
    mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(mask).polygon([(float(p[0]), float(p[1])) for p in points], fill=255)
    background = Image.new("RGB", image.size, MASK_FILL)
    return Image.composite(image, background, mask)


def box_to_fence_box(box: Sequence[float], offset_x: float, offset_y: float) -> list[float]:
    """把子图坐标下的候选框平移回原图坐标。裁剪推理后必须调用，否则整批框错位。"""
    return [
        round(float(box[0]) + offset_x, 2),
        round(float(box[1]) + offset_y, 2),
        round(float(box[2]) + offset_x, 2),
        round(float(box[3]) + offset_y, 2),
    ]


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------
def _drop_duplicate_points(points: list[list[float]]) -> list[list[float]]:
    """去掉相邻重合点与首尾重合点（前端双击闭合时常见），保持原有顺序。"""
    deduped: list[list[float]] = []
    for point in points:
        if deduped and _same_point(deduped[-1], point):
            continue
        deduped.append(point)
    while len(deduped) >= 2 and _same_point(deduped[0], deduped[-1]):
        deduped.pop()
    return deduped


def _same_point(a: Sequence[float], b: Sequence[float]) -> bool:
    return abs(float(a[0]) - float(b[0])) < 1e-6 and abs(float(a[1]) - float(b[1])) < 1e-6


def _on_segment(x: float, y: float, x1: float, y1: float, x2: float, y2: float) -> bool:
    """点是否落在线段上（含端点），用于把边界点算作“在围栏内”。"""
    cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
    if abs(cross) > 1e-9:
        return False
    return min(x1, x2) - 1e-9 <= x <= max(x1, x2) + 1e-9 and min(y1, y2) - 1e-9 <= y <= max(
        y1, y2
    ) + 1e-9


def _inside_edge(
    point: Sequence[float], edge: str, left: float, top: float, right: float, bottom: float
) -> bool:
    x, y = float(point[0]), float(point[1])
    if edge == "left":
        return x >= left
    if edge == "right":
        return x <= right
    if edge == "top":
        return y >= top
    return y <= bottom


def _intersect_edge(
    a: Sequence[float], b: Sequence[float], edge: str, left: float, top: float, right: float, bottom: float
) -> list[float]:
    """求线段与某条裁剪边界的交点。a 与 b 必有一个在边界内侧，不会平行。"""
    x1, y1 = float(a[0]), float(a[1])
    x2, y2 = float(b[0]), float(b[1])
    if edge in ("left", "right"):
        x = left if edge == "left" else right
        if abs(x2 - x1) < 1e-12:
            return [x, y1]
        return [x, y1 + (x - x1) * (y2 - y1) / (x2 - x1)]
    y = top if edge == "top" else bottom
    if abs(y2 - y1) < 1e-12:
        return [x1, y]
    return [x1 + (y - y1) * (x2 - x1) / (y2 - y1), y]
