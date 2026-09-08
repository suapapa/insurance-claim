# syntax=docker/dockerfile:1
#
# 백엔드(FastAPI) 이미지. 빌드 컨텍스트는 레포 루트여야 한다:
#   docker build -f backend/Dockerfile .
#   (또는 docker-compose.yml의 backend 서비스)

# ---------- 1단계: uv로 의존성 설치 ----------
FROM python:3.12-slim AS build

# uv.lock과 동일한 캐시/빌드 동작을 위해 uv 바이너리를 공식 이미지에서 가져온다
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# virtual 프로젝트(uv.lock의 source = { virtual = "." })이므로 의존성만 설치된다
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# 의존성 레이어를 코드 수정과 무관하게 캐시
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---------- 2단계: 런타임 ----------
FROM python:3.12-slim AS runtime

# 업로드/추출 결과를 기록하는 볼륨 마운트 지점
ENV INSURANCE_DATA_DIR=/data \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

RUN useradd --create-home --uid 1000 appuser

WORKDIR /app

COPY --from=build /opt/venv /opt/venv
COPY backend ./backend
# main.py가 StaticFiles로 마운트하는 경로 — 디렉터리가 없으면 기동 자체가 실패하므로
# 프론트엔드 이미지가 따로 있어도 빈 디렉터리가 아닌 실제 파일로 함께 넣는다.
COPY frontend ./frontend
RUN mkdir -p /data && chown -R appuser:appuser /app /data

USER appuser

EXPOSE 8321

# data 하위 디렉터리를 미리 만들어 마운트 볼륨이 쓰기 불가한 경우 기동 시점에 알린다
CMD ["sh", "-c", "mkdir -p \"$INSURANCE_DATA_DIR/uploads\" \"$INSURANCE_DATA_DIR/claims\" \
    && exec uvicorn backend.main:app --host 0.0.0.0 --port 8321"]
