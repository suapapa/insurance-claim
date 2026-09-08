"""보험 청구 정리 웹앱 서버.

실행: uv run uvicorn backend.main:app --port 8321  (또는 uv run python backend/main.py)
"""
from __future__ import annotations

import datetime as dt
import mimetypes
import re
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config, pipeline

app = FastAPI(title="insurance-claim")

SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


@app.post("/api/jobs")
async def create_job(files: list[UploadFile] = File(...)):
    """사진 묶음을 받아 잡을 만들고 백그라운드 파이프라인을 시작."""
    if not files:
        raise HTTPException(400, "파일이 없습니다.")
    filename_map = []
    job = pipeline.create_job(filename_map)  # 임시: 아래에서 파일을 채운 뒤 갱신
    dest_dir = pipeline._jobs_dir(job["id"])

    saved = 0
    for f in files:
        suffix = Path(f.filename or "").suffix.lower()
        if suffix not in pipeline.IMAGE_EXTS:
            continue
        safe = f"{dt.datetime.now():%H%M%S}_{saved:02d}_{SAFE_NAME.sub('_', Path(f.filename).stem)[:40]}{suffix}"
        data = await f.read()
        if not data:
            continue
        (dest_dir / safe).write_bytes(data)
        filename_map.append({"saved": safe, "original": f.filename})
        saved += 1

    if not filename_map:
        pipeline._update_job(job["id"], status="failed", error="이미지 파일이 없습니다.")
        return JSONResponse({"error": "이미지 파일이 없습니다."}, status_code=400)

    pipeline._update_job(job["id"], files=filename_map)
    pipeline.schedule_job(job["id"])
    return {"job_id": job["id"]}


@app.get("/api/jobs")
async def list_jobs():
    return {"jobs": pipeline.list_jobs()}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    if not SAFE_ID.match(job_id):
        raise HTTPException(400, "잘못된 작업 ID입니다.")
    job = pipeline.get_job(job_id)
    if not job:
        raise HTTPException(404, "잡을 찾을 수 없습니다.")
    return job


@app.get("/api/images/{job_id}/{filename}")
async def get_image(job_id: str, filename: str):
    """원본 사진 미리보기 (경로 traversal 차단). HEIC는 웹 호환 WebP로 자동 변환."""
    if not SAFE_ID.match(job_id):
        raise HTTPException(400, "잘못된 작업 ID입니다.")
    base_dir = pipeline._jobs_dir(job_id).resolve()
    p = (base_dir / Path(filename).name).resolve()
    if not str(p).startswith(str(base_dir)) or not p.is_file():
        raise HTTPException(404)
    if p.suffix.lower() in (".heic", ".heif"):
        cached_webp = base_dir / f"{p.stem}.webp"
        if not cached_webp.exists():
            pipeline.convert_to_webp(p, cached_webp)
        return FileResponse(cached_webp, media_type="image/webp")
    mt = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
    return FileResponse(p, media_type=mt)


@app.get("/api/claims/{claim_dir}/{filename}")
async def get_claim_file(claim_dir: str, filename: str):
    """청구 디렉터리 내 파일(변환된 webp 이미지, summary.yaml 등) 서빙 (경로 traversal 차단)."""
    base_dir = config.CLAIMS_DIR.resolve()
    target_dir = (base_dir / Path(claim_dir).name).resolve()
    if not str(target_dir).startswith(str(base_dir)) or not target_dir.is_dir():
        raise HTTPException(404, "청구 디렉터리를 찾을 수 없습니다.")
    p = (target_dir / Path(filename).name).resolve()
    if not str(p).startswith(str(target_dir)) or not p.is_file():
        raise HTTPException(404, "파일을 찾을 수 없습니다.")
    mt = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
    return FileResponse(p, media_type=mt)


# 프론트엔드 정적 서빙 (API 라우트 뒤에 마운트)
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    config.UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    config.CLAIMS_DIR.mkdir(parents=True, exist_ok=True)
    uvicorn.run(app, host="0.0.0.0", port=8321)
