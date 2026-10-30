"""任务目录：七个 VLX-Seek 任务的分组、默认参数、提示词模板、已知坑。

这是任务的**唯一数据源**，通过 `/api/meta` 下发给前端，前端不再硬编码任何任务信息。
加任务 = 这里加一条 + `task_runner.py` 的派发表加一行，前端零改动。
"""
from __future__ import annotations

from typing import Any, Optional

# 分组顺序即页面左侧导航的顺序
GROUPS: list[str] = ["开放问答", "检测与定位", "区域理解"]

ALL_TASKS: list[dict[str, Any]] = [
    {
        "id": "vqa",
        "name": "通用图文问答",
        "group": "开放问答",
        "badge": "无需候选框",
        "summary": "问什么答什么，text 原样作为 question 送入，不做模板包装。",
        "text_label": "问题（text）",
        "text_placeholder": "What fruits are in this image?",
        "default_text": "What fruits are in this image?",
        "needs_bbox": False,
        "needs_index": False,
        "default_lang": "en",
        "default_max_new_tokens": 512,
        "default_temperature": 0.0,
        "templates": {
            "en": "（不套模板，text 原样作为 question）",
            "zh": "（不套模板，text 原样作为 question）",
        },
        "call": "worker.predict(image, text, bbox_list=None)",
        "tips": [
            "唯一不需要候选框的任务，result_bbox_list 恒为空。",
            "传候选框后可用 <obj3> 指代某个框，但 prompt_tokens 会从 ~210 涨到 ~415。",
        ],
    },
    {
        "id": "detection",
        "name": "多类别检测",
        "group": "检测与定位",
        "badge": "需要候选框",
        "summary": "给定类别名，把图里属于这些类的候选框全部挑出来并归类，最常用的主力接口。",
        "text_label": "类别名（多个用 ; 分隔）",
        "text_placeholder": "orange; apple",
        "default_text": "orange; apple",
        "needs_bbox": True,
        "needs_index": False,
        "default_lang": "zh",
        "default_max_new_tokens": 1024,
        "default_temperature": 0.0,
        "templates": {
            "en": "Detect all the instances of: {}.",
            "zh": "识别每个：{}。",
        },
        "call": "worker.detect(image, bbox_list, text, lang=lang)",
        "tips": [
            "多类别返回多条 <ground>…</ground><objects>…</objects>，result_bbox_list 可直接按 label 分组看。",
            "官方 CLI 里这个任务被写成 range(10) 测速循环、time: 会污染 stdout；本框架直接调 Python API，无此问题。",
        ],
    },
    {
        "id": "grounding_single",
        "name": "单目标指代定位",
        "group": "检测与定位",
        "badge": "需要候选框",
        "summary": "用一句描述定位一个目标，只返回最匹配的那一个。",
        "text_label": "目标描述",
        "text_placeholder": "最左边的橙子",
        "default_text": "最左边的橙子",
        "needs_bbox": True,
        "needs_index": False,
        "default_lang": "zh",
        "default_max_new_tokens": 512,
        "default_temperature": 0.0,
        "templates": {
            "en": "Detect a single instance of: {}.",
            "zh": "检测单个目标：{}。",
        },
        "call": "worker.ground(image, bbox_list, text, lang=lang)",
        "tips": [
            "label 字段是你传入的描述原文，不是模型识别出的类别。",
            "图里没有符合描述的目标时仍会强行返回 1 个框，需要判断“有没有”请用 detection。",
        ],
    },
    {
        "id": "counting",
        "name": "计数",
        "group": "检测与定位",
        "badge": "需要候选框",
        "summary": "数出某类目标的个数并给出每个的编号。",
        "text_label": "类别名或描述",
        "text_placeholder": "橙子",
        "default_text": "橙子",
        "needs_bbox": True,
        "needs_index": False,
        "default_lang": "zh",
        "default_max_new_tokens": 512,
        "default_temperature": 0.0,
        "templates": {
            "en": "Find and count all {} in the image. Provide the object indexes along with the total number.",
            "zh": "在图片中识别并计数： {}。返回目标数量以及索引。",
        },
        "call": "worker.count(image, bbox_list, text, lang=lang)",
        "tips": [
            "要数字请数 len(result_bbox_list)，不要解析 answer 里的自然语言。",
            "label 是自由文本（可能被翻译或带前导空格），不要做精确字符串匹配。",
        ],
    },
    {
        "id": "reasoning_detection",
        "name": "带思考链的检测",
        "group": "检测与定位",
        "badge": "需要候选框 · 慢 10 倍",
        "summary": "先逐个分析候选区域，再给结论，输出 <think> + <answer>。",
        "text_label": "类别名（多个用 ; 分隔）",
        "text_placeholder": "orange; apple",
        "default_text": "orange; apple",
        "needs_bbox": True,
        "needs_index": False,
        "default_lang": "zh",
        "default_max_new_tokens": 2048,
        "default_temperature": 0.0,
        "templates": {
            "en": "First thinks about the reasoning process in the mind and then provides the user with the answer. …Find the following in this picture: {}.",
            "zh": "首先思考思维过程，然后向用户提供答案。…在图像中识别{}。",
        },
        "call": "worker.reasoning_detect(image, bbox_list, text, lang=lang, max_new_tokens=2048)",
        "tips": [
            "实测约 20s，思考链要 382 token；max_new_tokens 低于 1024 有被硬截断的风险。",
            "result_bbox_list 的 label 会把多个类别合并成一段，无法区分哪个框是哪类——要分类用 detection。",
        ],
    },
    {
        "id": "brief_region_caption",
        "name": "指定区域描述",
        "group": "区域理解",
        "badge": "需要候选框 + 索引",
        "summary": "已知框在哪，让模型说说每个选中区域里是什么。",
        "text_label": "目标区域索引（由候选框点选生成）",
        "text_placeholder": "点击左侧图上的候选框来选区域",
        "default_text": "",
        "needs_bbox": True,
        "needs_index": True,
        "default_lang": "zh",
        "default_max_new_tokens": 512,
        "default_temperature": 0.0,
        "templates": {
            "en": "Give a brief description of {}.",
            "zh": "给出这些区域的简要描述：{}。",
        },
        "call": "worker.describe_region(image, bbox_list, target_region_indexes, lang=lang)",
        "tips": [
            "target_region_indexes 必须是 list[int]，空列表或越界都会抛 ValueError。",
            "返回的是“区域 → 描述”映射，可直接做 dict(object_index → label)。",
        ],
    },
    {
        "id": "region_ocr",
        "name": "区域文字识别",
        "group": "区域理解",
        "badge": "需要候选框 + 索引",
        "summary": "读出指定区域内的文字。",
        "text_label": "目标区域索引（由候选框点选生成）",
        "text_placeholder": "点击左侧图上的候选框来选区域",
        "default_text": "",
        "needs_bbox": True,
        "needs_index": True,
        "default_lang": "zh",
        "default_max_new_tokens": 512,
        "default_temperature": 0.0,
        "templates": {
            "en": "Please provide the ocr results of {} in the image.",
            "zh": "请提供该区域内的 OCR 结果：{}。",
        },
        "call": "worker.read_region_text(image, bbox_list, target_region_indexes, lang=lang)",
        "tips": [
            "无法判断“区域内到底有没有文字”，没有文字时会把物体名当答案返回。",
            "输出可能是 <ground>文字</ground><objects>…</objects>，也可能直接是文字，解析要容错。",
        ],
    },
]

# 需要候选框 / 需要区域索引的任务集合：从数据派生，避免两处手写漂移
BBOX_TASK_IDS: set[str] = {t["id"] for t in ALL_TASKS if t["needs_bbox"]}
REGION_TASK_IDS: set[str] = {t["id"] for t in ALL_TASKS if t["needs_index"]}

_BY_ID: dict[str, dict[str, Any]] = {t["id"]: t for t in ALL_TASKS}


def get_task(task_id: str) -> Optional[dict[str, Any]]:
    """按 id 取任务定义。

    返回：命中返回任务 dict（只读，调用方不要修改）；未命中返回 None（不抛异常）。
    """
    return _BY_ID.get(task_id)
