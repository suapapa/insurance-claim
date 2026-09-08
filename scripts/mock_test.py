"""비전 LLM을 목으로 대체해 파이프라인(분류->복제->추출->summary.yaml)을 검증하는 스크립트.

사용: uv run python scripts/mock_test.py
"""
import asyncio
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config, pipeline, vision  # noqa: E402

# data/ 디렉터리 초기화
shutil.rmtree(config.DATA_DIR, ignore_errors=True)
config.UPLOADS_DIR.mkdir(parents=True)
config.CLAIMS_DIR.mkdir(parents=True)

FAKE_CLASSIFY = {"groups": [
    {"patient": "김철수", "claim_type": "상해", "date": "2026-08-08",
     "diagnosis": "요추 염좌", "image_nos": [1, 2]},
    {"patient": "박영희", "claim_type": "질병", "date": "2026-07-02",
     "diagnosis": "급성 기관지염", "image_nos": [3]},
]}
FAKE_EXTRACT = {
    "patient": "김철수", "claim_type": "상해", "hospitalization": "통원",
    "treatment_start": "2026-08-08", "treatment_end": "2026-08-20",
    "diagnosis": "요추 염좌",
    "incident_desc": "회사 계단에서 미끄러져 넘어져 허리를 다침",
    "incident_place": "서울 강남구 테헤란로 123",
    "incident_datetime": "2026-08-08 14:30",
}


async def fake_ask_vision(prompt, image_paths, max_tokens=4096):
    return FAKE_EXTRACT if "보험금 청구 데이터를 추출" in prompt else FAKE_CLASSIFY


async def main():
    vision.ask_vision = fake_ask_vision  # monkeypatch (pipeline은 모듈 속성을 참조)

    files = [{"saved": f"doc{i}.jpg", "original": f"doc{i}.jpg"} for i in range(1, 4)]
    job = pipeline.create_job(files)
    d = pipeline._jobs_dir(job["id"])
    for i in (1, 2, 3):
        shutil.copy(f"/tmp/test_docs/{['diag_kim','rx_kim','diag_park'][i-1]}.jpg", d / f"doc{i}.jpg")

    await pipeline.run_job(job["id"])

    final = pipeline.get_job(job["id"])
    print("STATUS:", final["status"], "| error:", final.get("error"))
    print("CLAIMS:", json.dumps(final["claims"], ensure_ascii=False, indent=1))
    for c in final["claims"]:
        p = config.CLAIMS_DIR / c["dir"] / "summary.yaml"
        print(f"\n===== {p} =====")
        print(p.read_text(encoding="utf-8"))
        imgs = sorted(x.name for x in (config.CLAIMS_DIR / c["dir"]).iterdir() if x.suffix == ".jpg")
        print("IMAGES:", imgs)
    assert final["status"] == "done", "잡이 완료되지 않았습니다"
    assert len(final["claims"]) == 2, "청구 건수가 2가 아닙니다"
    print("\nMOCK PIPELINE TEST PASSED")


asyncio.run(main())
