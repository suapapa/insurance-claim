"""청구 파이프라인: 업로드 -> 분류(그룹핑) -> 이동 -> 정보 추출 -> summary.yaml."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import re
import shutil
import threading
import uuid
from pathlib import Path

import yaml
from PIL import Image, ImageOps
import pillow_heif

# HEIC/HEIF 이미지 포맷 자동 지원 등록
pillow_heif.register_heif_opener()

from . import config, kcd, prompts, vision

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".bmp", ".tif", ".tiff"}
THUMBNAIL_SIZE = (320, 320)
THUMBNAIL_QUALITY = 78

_jobs: dict[str, dict] = {}
_jobs_lock = threading.RLock()
_deleted_jobs: set[str] = set()

# 같은 배치 안에서 이름이 겹치는 청구 디렉터리에 붙이는 접미사 관리
_taken_names: set[str] = set()


class JobDeleted(Exception):
    """사용자가 처리 중인 작업을 삭제했을 때 파이프라인을 조용히 중단한다."""


# ---------------------------------------------------------------- 유틸

def convert_to_jpeg(src: Path, dest: Path, quality: int = 92) -> None:
    """모든 포맷을 EXIF 회전이 보정된 호환성 높은 JPEG로 변환 저장."""
    with Image.open(src) as img:
        img = ImageOps.exif_transpose(img)
        if "A" in img.getbands():
            rgba = img.convert("RGBA")
            background = Image.new("RGB", rgba.size, "white")
            background.paste(rgba, mask=rgba.getchannel("A"))
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, format="JPEG", quality=quality, optimize=True)


def thumbnail_path(src: Path, cache_dir: Path | None = None) -> Path:
    """원본 이름과 충돌하지 않는 JPEG 썸네일 캐시 경로를 반환한다."""
    return (cache_dir or src.parent / ".thumbnails") / f"{src.name}.jpg"


def create_thumbnail(src: Path, cache_dir: Path | None = None) -> Path:
    """작은 미리보기용 JPEG를 원본 비율로 생성하고 캐시한다."""
    dest = thumbnail_path(src, cache_dir)
    if dest.is_file():
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    temporary = dest.with_name(f".{dest.name}.{uuid.uuid4().hex}.tmp")
    try:
        with Image.open(src) as opened:
            img = ImageOps.exif_transpose(opened)
            img.thumbnail(THUMBNAIL_SIZE, Image.Resampling.LANCZOS)
            if "A" in img.getbands():
                rgba = img.convert("RGBA")
                background = Image.new("RGB", rgba.size, "white")
                background.paste(rgba, mask=rgba.getchannel("A"))
                img = background
            elif img.mode != "RGB":
                img = img.convert("RGB")
            img.save(
                temporary,
                format="JPEG",
                quality=THUMBNAIL_QUALITY,
                optimize=True,
            )
        temporary.replace(dest)
    finally:
        temporary.unlink(missing_ok=True)
    return dest


def ensure_job_thumbnails(job_id: str) -> None:
    """업로드 응답 전에 해당 작업의 모든 썸네일을 준비한다."""
    job = get_job(job_id)
    if not job:
        return
    cache_dir = _jobs_dir(job_id) / ".thumbnails"
    for image_path in image_paths_of(job):
        try:
            create_thumbnail(Path(image_path), cache_dir)
        except OSError:
            # 확장자는 이미지지만 손상된 파일은 기존 파이프라인에서 오류로 처리한다.
            continue


def _slug(text: str, max_len: int = 60) -> str:
    """디렉터리 이름에 안전한 형태로 정리."""
    text = (text or "알수없음").strip()
    text = re.sub(r'[\\/:*?"<>|\s]+', "_", text)
    text = re.sub(r"_{2,}", "_", text).strip("_")
    res = (text or "알수없음")[:max_len]
    return res.rstrip("_,(-")


def _norm_date(value, fallback: str | None = None) -> str | None:
    """YYYY-MM-DD (또는 앞부분) 추출. 실패 시 fallback."""
    for v in (value, fallback):
        if not v:
            continue
        m = re.search(r"(\d{4})[-./년\s]+(\d{1,2})[-./월\s]+(\d{1,2})", str(v))
        if m:
            return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def _claim_treatment_dates(claim: dict) -> tuple[str | None, str | None]:
    """카드용 치료 시작일/종료일을 구하고, 이전 잡은 summary.yaml로 보완한다."""
    start = _norm_date(claim.get("treatment_start"), claim.get("date"))
    end = _norm_date(claim.get("treatment_end"))

    if (not start or not end) and claim.get("dir"):
        summary_path = config.CLAIMS_DIR / claim["dir"] / "summary.yaml"
        if summary_path.is_file():
            try:
                summary = yaml.safe_load(summary_path.read_text(encoding="utf-8")) or {}
                period = str(summary.get("치료기간") or "")
                period_start, separator, period_end = period.partition("~")
                start = start or _norm_date(period_start)
                end = end or _norm_date(period_end if separator else period_start)
            except (OSError, yaml.YAMLError):
                pass

    return start, end


def _jobs_dir(job_id: str) -> Path:
    return config.UPLOADS_DIR / job_id


def _update_job(job_id: str, **fields) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            job.update(fields)
            (jobs_dir := _jobs_dir(job_id)).mkdir(parents=True, exist_ok=True)
            (jobs_dir / "job.json").write_text(
                json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8"
            )


def get_job(job_id: str) -> dict | None:
    """메모리에 없으면 디스크에서 복구 (서버 재시작 대비)."""
    with _jobs_lock:
        if job_id in _deleted_jobs:
            return None
        if job_id in _jobs:
            job = dict(_jobs[job_id])
        else:
            job = None
    if job is None:
        p = _jobs_dir(job_id) / "job.json"
        if p.exists():
            try:
                job = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return None
            # 재시작 중이던 잡은 interrupted로 표시
            if job.get("status") in ("classifying", "extracting", "queued"):
                job["status"] = "failed"
                job["error"] = "서버 재시작으로 중단되었습니다. 다시 업로드해 주세요."
                with _jobs_lock:
                    _jobs[job_id] = job
                p.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            return None

    # claims 내 질병코드, 치료기간, 이미지 목록 보완
    for c in job.get("claims", []):
        if c.get("diagnosis"):
            c["diagnosis"] = kcd.format_diagnosis(c["diagnosis"])
        treatment_start, treatment_end = _claim_treatment_dates(c)
        c["treatment_start"] = treatment_start
        c["treatment_end"] = treatment_end
        if not c.get("images") and c.get("dir"):
            cdir = config.CLAIMS_DIR / c["dir"]
            if cdir.is_dir():
                c["images"] = sorted([f.name for f in cdir.iterdir() if f.suffix.lower() in IMAGE_EXTS])
    return dict(job)


def list_jobs() -> list[dict]:
    out = []
    if config.UPLOADS_DIR.exists():
        for d in config.UPLOADS_DIR.iterdir():
            if d.is_dir():
                job = get_job(d.name)
                if job:
                    out.append(job)
    out.sort(key=lambda j: j.get("created_at", ""), reverse=True)
    return out


# ---------------------------------------------------------------- 업로드

def create_job(filename_map: list[dict]) -> dict:
    """업로드할 파일 목록으로 잡 생성. filename_map: [{saved, original}]"""
    job_id = uuid.uuid4().hex[:8]
    job = {
        "id": job_id,
        "status": "queued",  # queued -> classifying -> extracting -> done | failed
        "progress": "",
        "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "files": filename_map,
        "claims": [],  # 완료 후 카드용 요약
        "error": None,
    }
    _jobs_dir(job_id).mkdir(parents=True, exist_ok=True)
    with _jobs_lock:
        _deleted_jobs.discard(job_id)
        _jobs[job_id] = job
    _update_job(job_id)
    return job


def image_paths_of(job: dict) -> list[str]:
    d = _jobs_dir(job["id"])
    return [str(d / f["saved"]) for f in job["files"] if Path(f["saved"]).suffix.lower() in IMAGE_EXTS]


# ---------------------------------------------------------------- 1단계: 분류

async def _classify_chunk(job_id: str, paths: list[str], offset: int) -> list[dict]:
    result = await vision.ask_vision(
        prompts.CLASSIFY_PROMPT + "\n" + "\n".join(
            f"{i}. {Path(p).name}" for i, p in enumerate(paths, offset + 1)
        ),
        paths,
        start_index=offset + 1,
    )
    groups = result.get("groups") if isinstance(result, dict) else result
    if not isinstance(groups, list):
        raise ValueError(f"분류 응답 형식 오류: {result!r:.200}")
    out = []
    for g in groups:
        raw_nos = []
        for n in g.get("image_nos", []):
            m = re.search(r"\d+", str(n))
            if m:
                raw_nos.append(int(m.group()))
        # LLM이 offset을 무시하고 청크 내 상대 번호(1~len(paths))로 반환한 경우 보정
        if offset > 0 and raw_nos and all(1 <= x <= len(paths) for x in raw_nos):
            raw_nos = [x + offset for x in raw_nos]
        nos = [x for x in raw_nos if offset + 1 <= x <= offset + len(paths)]
        if not nos:
            continue
        out.append({
            "patient": str(g.get("patient") or "알수없음"),
            "claim_type": "상해" if str(g.get("claim_type", "")).startswith("상해") else "질병",
            "date": _norm_date(g.get("date")),
            "diagnosis": kcd.format_diagnosis(str(g.get("diagnosis") or "")),
            "image_nos": nos,
        })
    return out


async def classify(job: dict) -> list[dict]:
    """전체 사진을 환자+질병 기준 그룹으로 묶는다. 배치 분할 + 누락/중복 복구."""
    job_id = job["id"]
    paths = image_paths_of(job)
    if not paths:
        raise ValueError("유효한 이미지 파일이 없습니다.")

    all_groups: list[dict] = []
    seen: set[int] = set()
    n = len(paths)
    for start in range(0, n, config.MAX_IMAGES_PER_CALL):
        chunk = paths[start:start + config.MAX_IMAGES_PER_CALL]
        _update_job(job_id, status="classifying",
                    progress=f"서류 구분중 {min(start + len(chunk), n)}/{n}")
        groups = await _classify_chunk(job_id, chunk, start)
        for g in groups:
            fresh = [no for no in g["image_nos"] if no not in seen]
            if not fresh:
                continue
            g["image_nos"] = fresh
            seen.update(fresh)
            all_groups.append(g)

    # 응답에서 빠진 사진은 각자 빈 그룹으로 (extract 단계에서 재추출)
    missing = [i for i in range(1, n + 1) if i not in seen]
    if missing:
        all_groups.append({
            "patient": "알수없음", "claim_type": "질병", "date": None,
            "diagnosis": "", "image_nos": missing, "low_confidence": True,
        })
    return all_groups


# ---------------------------------------------------------------- 청구 디렉터리 생성

def _claim_dir_name(g: dict, seq: int) -> str:
    date = g.get("date") or dt.date.today().isoformat()
    base = f"{date}_{_slug(g['patient'])}_{_slug(g['diagnosis'], 40) or '미상'}"
    name = base
    i = 2
    with _jobs_lock:
        while name in _taken_names or (config.CLAIMS_DIR / name).exists():
            name = f"{base}({i})"
            i += 1
        _taken_names.add(name)
    return name


def materialize_claim(job_id: str, g: dict, seq: int) -> tuple[Path, list[str]]:
    """청구 디렉터리에 업로드 원본을 가리키는 상대 심볼릭 링크를 만든다."""
    with _jobs_lock:
        if job_id in _deleted_jobs or job_id not in _jobs:
            raise JobDeleted(job_id)

        dir_name = _claim_dir_name(g, seq)
        claim_dir = config.CLAIMS_DIR / dir_name
        claim_dir.mkdir(parents=True, exist_ok=True)
        linked = []
        used_names: set[str] = set()
        try:
            for no in g["image_nos"]:
                f = job_file(job_id, no)
                if not f or not f.exists():
                    continue
                candidate = f.name
                idx = 2
                while candidate in used_names or (claim_dir / candidate).exists():
                    candidate = f"{f.stem}_{idx}{f.suffix}"
                    idx += 1
                used_names.add(candidate)
                dest = claim_dir / candidate
                dest.symlink_to(Path(os.path.relpath(f.resolve(), claim_dir.resolve())))
                linked.append(str(dest))
        except Exception:
            shutil.rmtree(claim_dir, ignore_errors=True)
            _taken_names.discard(dir_name)
            raise
    return claim_dir, linked


def job_file(job_id: str, image_no: int) -> Path | None:
    """1-기준 사진 번호 -> uploads 내 실제 파일 경로."""
    with _jobs_lock:
        job = _jobs.get(job_id) or {}
    files = job.get("files", [])
    if 1 <= image_no <= len(files):
        return _jobs_dir(job_id) / files[image_no - 1]["saved"]
    return None


# ---------------------------------------------------------------- 2단계: 추출

def _fallback_extraction(g: dict) -> dict:
    d = g.get("date")
    return {
        "patient": g["patient"],
        "claim_type": g["claim_type"],
        "hospitalization": "통원",
        "treatment_start": d,
        "treatment_end": d,
        "diagnosis": g.get("diagnosis") or None,
        "incident_desc": None, "incident_place": None, "incident_datetime": None,
        "warnings": ["LLM 응답을 읽지 못해 분류 단계 힌트로만 채웠습니다. 수동 확인이 필요합니다."],
    }


def _sanitize(ex: dict, g: dict) -> dict:
    """LLM 추출 결과를 스키마에 맞게 정규화. 분류 단계 힌트로 보강."""
    claim_type = "상해" if str(ex.get("claim_type", "")).startswith("상해") else g["claim_type"]
    hosp = "입원" if str(ex.get("hospitalization", "")).startswith("입원") else "통원"
    start = _norm_date(ex.get("treatment_start"), g.get("date"))
    end = _norm_date(ex.get("treatment_end"), start)
    if start and end and end < start:
        start, end = end, start
    out = {
        "patient": str(ex.get("patient") or g["patient"] or "알수없음"),
        "claim_type": claim_type,
        "hospitalization": hosp,
        "treatment_start": start,
        "treatment_end": end,
        "diagnosis": kcd.format_diagnosis(ex.get("diagnosis") or g.get("diagnosis") or None),
    }
    if claim_type == "상해":
        dtv = None
        raw_dt = ex.get("incident_datetime")
        date_part = _norm_date(raw_dt)
        time_m = re.search(r"(\d{1,2}):(\d{2})", str(raw_dt or ""))
        if date_part:
            dtv = f"{date_part} {int(time_m.group(1)):02d}:{time_m.group(2)}" if time_m else date_part
        out["incident_desc"] = ex.get("incident_desc") or None
        out["incident_place"] = ex.get("incident_place") or None
        out["incident_datetime"] = dtv
    else:
        out["incident_desc"] = out["incident_place"] = out["incident_datetime"] = None
    return out


async def extract(claim_dir: Path, images: list[str], hint: dict) -> dict:
    if not images:
        ex = _fallback_extraction(hint)
        ex["warnings"] = (ex.get("warnings") or []) + ["이미지가 없어 분류 정보만 기록했습니다."]
        return ex
    prompt = prompts.EXTRACT_PROMPT.format(hint=json.dumps({
        "patient": hint["patient"], "claim_type": hint["claim_type"],
        "date": hint.get("date"), "diagnosis": hint.get("diagnosis"),
    }, ensure_ascii=False))
    try:
        result = await vision.ask_vision(prompt, images[: config.MAX_IMAGES_PER_CALL])
        if not isinstance(result, dict):
            raise ValueError("추출 응답이 객체가 아닙니다.")
        return _sanitize(result, hint)
    except Exception:
        return _fallback_extraction(hint)


def write_summary(claim_dir: Path, ex: dict, images: list[str], job_id: str) -> None:
    data = {
        # 사고 공통 + 질병 공통 필드를 한 스키마로 통합 (해당 없는 필드는 null)
        "환자": ex["patient"],
        "청구사유": ex["claim_type"],
        "입원구분": ex["hospitalization"],
        "치료기간": None if not (ex["treatment_start"] or ex["treatment_end"])
                    else f"{ex['treatment_start']}~{ex['treatment_end']}",
        "진단명(사고 상세내용)": ex["diagnosis"],
        "사고경위": ex["incident_desc"],
        "사고장소": ex["incident_place"],
        "사고일시": ex["incident_datetime"],
        "_meta": {
            "job_id": job_id,
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "images": [Path(p).name for p in images],
            "warnings": ex.get("warnings") or None,
        },
    }
    (claim_dir / "summary.yaml").write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


# ---------------------------------------------------------------- 파이프라인


def _summary_job_id(claim_dir: Path) -> str | None:
    summary = claim_dir / "summary.yaml"
    if not summary.is_file():
        return None
    try:
        data = yaml.safe_load(summary.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    meta = data.get("_meta") if isinstance(data, dict) else None
    return str(meta.get("job_id")) if isinstance(meta, dict) and meta.get("job_id") else None


def _claim_links_to_job(claim_dir: Path, job_dir: Path) -> bool:
    for entry in claim_dir.iterdir():
        if not entry.is_symlink():
            continue
        try:
            entry.resolve(strict=False).relative_to(job_dir.resolve())
            return True
        except (OSError, ValueError):
            continue
    return False


def delete_job(job_id: str) -> dict | None:
    """작업 원본과 썸네일, 이 작업에서 파생된 청구 디렉터리를 모두 삭제한다."""
    job_dir = _jobs_dir(job_id)
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            job_file_path = job_dir / "job.json"
            if not job_file_path.is_file():
                return None
            try:
                job = json.loads(job_file_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
        job = dict(job)
        _deleted_jobs.add(job_id)
        _jobs.pop(job_id, None)

    known_claims = {
        str(claim.get("dir"))
        for claim in job.get("claims", [])
        if claim.get("dir")
    }
    claim_dirs: list[Path] = []
    if config.CLAIMS_DIR.is_dir():
        for claim_dir in config.CLAIMS_DIR.iterdir():
            if not claim_dir.is_dir():
                continue
            if (
                claim_dir.name in known_claims
                or _summary_job_id(claim_dir) == job_id
                or _claim_links_to_job(claim_dir, job_dir)
            ):
                claim_dirs.append(claim_dir)

    for claim_dir in claim_dirs:
        shutil.rmtree(claim_dir)
    shutil.rmtree(job_dir, ignore_errors=True)

    with _jobs_lock:
        _taken_names.difference_update(claim_dir.name for claim_dir in claim_dirs)
    return {"job_id": job_id, "deleted_claims": len(claim_dirs)}

async def run_job(job_id: str) -> None:
    job = get_job(job_id)
    if not job:
        return
    try:
        groups = await classify(job)

        _update_job(job_id, status="extracting", progress=f"정보 추출중 0/{len(groups)}")
        claims_meta = []
        for seq, g in enumerate(groups, 1):
            claim_dir, images = materialize_claim(job_id, g, seq)
            _update_job(job_id, status="extracting",
                        progress=f"정보 추출중 {seq}/{len(groups)} ({claim_dir.name})")
            ex = await extract(claim_dir, images, g)
            write_summary(claim_dir, ex, images, job_id)
            claims_meta.append({
                "dir": claim_dir.name,
                "patient": ex["patient"],
                "claim_type": ex["claim_type"],
                "date": ex["treatment_start"] or g.get("date"),
                "treatment_start": ex["treatment_start"],
                "treatment_end": ex["treatment_end"],
                "diagnosis": ex["diagnosis"],
                "hospitalization": ex["hospitalization"],
                "images": [Path(p).name for p in images],
            })

        _update_job(job_id, status="done", progress="완료", claims=claims_meta)
    except JobDeleted:
        return
    except Exception as e:  # noqa: BLE001
        _update_job(job_id, status="failed", error=f"{type(e).__name__}: {e}")


def schedule_job(job_id: str) -> None:
    """백그라운드 스레드에서 asyncio 파이프라인 실행 (블로킹 없이)."""
    def _run():
        asyncio.run(run_job(job_id))
    threading.Thread(target=_run, daemon=True, name=f"claim-{job_id}").start()
