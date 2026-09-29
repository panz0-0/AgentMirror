# -*- coding: utf-8 -*-
"""
阿里云百炼 — Qwen Image Edit API (DashScope 原生协议)

替代 OpenAI images.edit, 用于 qwen-image-2.0-pro 等图像编辑模型。
文档: https://help.aliyun.com/zh/model-studio/qwen-image-edit-api
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import requests

from app.pipeline.image_utils import encode_image
from app.pipeline.logging_setup import LOG

# qwen-image-2.0 系列: 总像素 512*512 ~ 2048*2048
_DASHSCOPE_SIZE_PRESETS: dict[str, str] = {
    "1024x1024": "1024*1024",
    "1536x1536": "1536*1536",
    "1024x1536": "1024*1536",
    "1536x1024": "1536*1024",
    "768x1152": "768*1152",
    "1152x768": "1152*768",
    "2048x2048": "2048*2048",
    "2048x1152": "2048*1152",
    "1152x2048": "1152*2048",
    "3840x2160": "1920*1080",
    "2160x3840": "1080*1920",
}


def to_dashscope_size(size: str) -> str:
    """把 OpenAI 尺寸 (1024x1024) 转为百炼格式 (1024*1024), 并限制在合法范围。"""
    normalized = size.strip().lower().replace("*", "x")
    if normalized in _DASHSCOPE_SIZE_PRESETS:
        return _DASHSCOPE_SIZE_PRESETS[normalized]

    m = re.match(r"^(\d+)x(\d+)$", normalized)
    if not m:
        LOG.warning("无法解析尺寸 %s, 回退 1024*1024", size)
        return "1024*1024"

    w, h = int(m.group(1)), int(m.group(2))
    pixels = w * h
    min_pixels = 512 * 512
    max_pixels = 2048 * 2048

    if pixels > max_pixels:
        scale = (max_pixels / pixels) ** 0.5
        w = max(512, int(w * scale) // 16 * 16)
        h = max(512, int(h * scale) // 16 * 16)
    elif pixels < min_pixels:
        scale = (min_pixels / max(pixels, 1)) ** 0.5
        w = min(2048, max(512, int(w * scale) // 16 * 16))
        h = min(2048, max(512, int(h * scale) // 16 * 16))

    return f"{w}*{h}"


def _image_to_dashscope_ref(image_path: Path) -> str:
    """本地图片 → DashScope 可接受的 base64 data URL。"""
    return encode_image(str(image_path))


def dashscope_image_edit(
    *,
    api_key: str,
    model: str,
    image_path: Path,
    prompt: str,
    size: str = "1024x1024",
    api_url: str,
    timeout: float = 600.0,
    watermark: bool = False,
    prompt_extend: bool = True,
) -> bytes:
    """调用百炼 Qwen Image Edit API, 返回 PNG 字节。

    Args:
        api_key: 百炼 API Key (Bearer token)。
        model: 模型名, 如 qwen-image-2.0-pro-2026-06-22。
        image_path: 本地底图路径。
        prompt: 编辑指令 (英文)。
        size: OpenAI 风格尺寸, 内部会转换。
        api_url: multimodal-generation 端点 URL。
        timeout: HTTP 超时 (秒)。
        watermark: 是否添加 Qwen-Image 水印。
        prompt_extend: 是否开启提示词智能改写。

    Returns:
        生成图片的 PNG 字节。

    Raises:
        RuntimeError: API 返回错误或无法下载结果图。
    """
    ds_size = to_dashscope_size(size)
    image_ref = _image_to_dashscope_ref(image_path)

    payload: dict[str, Any] = {
        "model": model,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"image": image_ref},
                        {"text": prompt},
                    ],
                }
            ]
        },
        "parameters": {
            "n": 1,
            "negative_prompt": " ",
            "prompt_extend": prompt_extend,
            "watermark": watermark,
            "size": ds_size,
        },
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }

    LOG.debug(
        "DashScope image edit: model=%s size=%s prompt_len=%d",
        model, ds_size, len(prompt),
    )

    resp = requests.post(api_url, json=payload, headers=headers, timeout=timeout)
    data = resp.json()

    if resp.status_code != 200:
        code = data.get("code", resp.status_code)
        message = data.get("message", resp.text)
        raise RuntimeError(f"DashScope API 错误 [{code}]: {message}")

    if data.get("code"):
        raise RuntimeError(
            f"DashScope API 错误 [{data.get('code')}]: {data.get('message', data)}"
        )

    image_url = _extract_image_url(data)
    if not image_url:
        raise RuntimeError(f"DashScope 响应无图片 URL: {data}")

    img_resp = requests.get(image_url, timeout=120)
    img_resp.raise_for_status()
    return img_resp.content


def _extract_image_url(data: dict) -> str | None:
    """从百炼 multimodal-generation 响应中提取图片 URL。"""
    try:
        choices = data["output"]["choices"]
        content = choices[0]["message"]["content"]
        for item in content:
            if isinstance(item, dict) and item.get("image"):
                return item["image"]
    except (KeyError, IndexError, TypeError):
        pass
    return None
