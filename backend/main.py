"""보험 청구 정리 웹앱 서버.

실행: uv run uvicorn backend.main:app --port 8321  (또는 uv run python backend/main.py)
"""
from __future__ import annotations

import datetime as dt
import mimetypes
import re
import tempfile
import uuid
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

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
    """원본 사진 미리보기 (경로 traversal 차단). HEIC는 JPEG로 자동 변환."""
    if not SAFE_ID.match(job_id):
        raise HTTPException(400, "잘못된 작업 ID입니다.")
    base_dir = pipeline._jobs_dir(job_id).resolve()
    p = (base_dir / Path(filename).name).resolve()
    if not str(p).startswith(str(base_dir)) or not p.is_file():
        raise HTTPException(404)
    if p.suffix.lower() in (".heic", ".heif"):
        cached_jpeg = base_dir / f"{p.stem}.preview.jpg"
        if not cached_jpeg.exists():
            pipeline.convert_to_jpeg(p, cached_jpeg)
        return FileResponse(cached_jpeg, media_type="image/jpeg")
    mt = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
    return FileResponse(p, media_type=mt)


def _claim_directory(claim_dir: str) -> Path:
    """청구 디렉터리를 안전하게 확인하고 절대 경로로 반환."""
    base_dir = config.CLAIMS_DIR.resolve()
    if Path(claim_dir).name != claim_dir:
        raise HTTPException(400, "잘못된 청구 디렉터리입니다.")
    target_dir = (base_dir / claim_dir).resolve()
    if target_dir.parent != base_dir or not target_dir.is_dir():
        raise HTTPException(404, "청구 디렉터리를 찾을 수 없습니다.")
    return target_dir


@app.get("/api/claims/{claim_dir}/download")
async def download_claim_archive(claim_dir: str):
    """청구 건의 JPEG 이미지와 summary.yaml을 하나의 ZIP으로 다운로드."""
    target_dir = _claim_directory(claim_dir)
    summary = target_dir / "summary.yaml"
    images = sorted(
        p for p in target_dir.iterdir()
        if p.is_file() and p.suffix.lower() in pipeline.IMAGE_EXTS
    )
    if not summary.is_file():
        raise HTTPException(409, "청구 정보가 아직 준비되지 않았습니다.")

    temp = tempfile.NamedTemporaryFile(prefix="insurance-claim-", suffix=".zip", delete=False)
    archive_path = Path(temp.name)
    temp.close()
    try:
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            folder = Path(claim_dir)
            for image in images:
                archive.write(image, arcname=str(folder / image.name))
            archive.write(summary, arcname=str(folder / summary.name))
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise

    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename=f"{claim_dir}.zip",
        background=BackgroundTask(archive_path.unlink, missing_ok=True),
    )


@app.get("/api/claims/{claim_dir}/{filename}")
async def get_claim_file(claim_dir: str, filename: str):
    """청구 디렉터리 내 JPEG 이미지, summary.yaml 등을 안전하게 서빙."""
    target_dir = _claim_directory(claim_dir)
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
