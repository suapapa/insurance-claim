"""환경 변수로 조절하는 전역 설정."""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """repo 루트의 .env 를 간단 파싱 (이미 set된 환경변수는 우선)."""
    p = REPO_ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

DATA_DIR = Path(os.environ.get("INSURANCE_DATA_DIR", REPO_ROOT / "data")).resolve()
UPLOADS_DIR = DATA_DIR / "uploads"
CLAIMS_DIR = DATA_DIR / "claims"

# OpenAI 호환 게이트웨이 (LiteLLM 등)
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://172.16.0.200:4000/v1").rstrip("/")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
VISION_MODEL = os.environ.get("VISION_MODEL", "DeepSeek/deepseek-v4-flash-vision-exp")

# 한 번의 분류/추출 호출에 보낼 최대 이미지 수
MAX_IMAGES_PER_CALL = int(os.environ.get("MAX_IMAGES_PER_CALL", "10"))

# reasoning + JSON이 같이 깎이지 않도록 기본 16k (Qwen3.8 thinking 권장)
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "16384"))

# Qwen3.8 등: thinking 유지(기본 ON). OFF면 chat_template_kwargs.enable_thinking=false
ENABLE_THINKING = os.environ.get("ENABLE_THINKING", "true").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# xhigh|medium|low — thinking 유지 시 기본 low (JSON 잘림 완화)
REASONING_EFFORT = os.environ.get("REASONING_EFFORT", "low").strip().lower() or "low"
