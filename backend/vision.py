"""OpenAI 호환 채팅 API에 이미지를 보내고 JSON을 받아오는 비전 클라이언트."""
from __future__ import annotations

import base64
import io
import json
import re

import httpx
from PIL import Image, ImageOps
import pillow_heif

# HEIC/HEIF 이미지 포맷 자동 지원 등록
pillow_heif.register_heif_opener()

from . import config

_MAX_SIDE = 1568  # 토큰 대비 안전한 최대 변 길이
_JSON_FENCE = re.compile(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", re.S)


def image_to_data_url(path: str) -> str:
    """이미지를 읽어 정사각 비례 축소 후 base64 data URL로 변환."""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    if max(img.size) > _MAX_SIDE:
        img.thumbnail((_MAX_SIDE, _MAX_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def extract_json(text: str):
    """LLM 응답 텍스트에서 첫 번째 JSON 객체/배열을 파싱."""
    # DeepSeek, Qwen 등 추론 모델의 <think>...</think> 블록 제거
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    m = _JSON_FENCE.search(text)
    if m:
        text = m.group(1)
    else:
        # 앞뒤 잡글 제거: 첫 {또는 [에서 마지막 }또는 ]까지
        starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
        ends = [i for i in (text.rfind("}"), text.rfind("]")) if i >= 0]
        if starts and ends:
            text = text[min(starts): max(ends) + 1]
    return json.loads(text)


async def ask_vision(
    prompt: str,
    image_paths: list[str],
    max_tokens: int = 4096,
    start_index: int = 1,
) -> dict | list:
    """사진 목록 + 프롬프트를 보내고 JSON 구조화된 응답을 반환."""
    content: list[dict] = [{"type": "text", "text": prompt}]
    for i, p in enumerate(image_paths, start_index):
        content.append({"type": "text", "text": f"[사진 {i}]"})
        content.append({"type": "image_url", "image_url": {"url": image_to_data_url(p)}})

    payload = {
        "model": config.VISION_MODEL,
        "messages": [{"role": "user", "content": content}],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    headers = {"Authorization": f"Bearer {config.LLM_API_KEY}"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0)) as client:
        r = await client.post(f"{config.LLM_BASE_URL}/chat/completions", json=payload, headers=headers)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
    return extract_json(text)
