"""핵심 파이프라인 및 비전 모듈 단위 테스트."""
import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from PIL import Image
import yaml

from backend import config, pipeline, vision


class TestCore(unittest.TestCase):
    def test_heic_registered(self):
        """pillow-heif가 PIL에 등록되었는지 확인."""
        self.assertIn(".heic", Image.registered_extensions())
        self.assertIn(".heif", Image.registered_extensions())

    def test_extract_json(self):
        """마크다운 펜스, 대화체 문구, <think> 태그 제거 후 JSON 파싱 검증."""
        # 1. 일반 JSON
        self.assertEqual(vision.extract_json('{"key": "value"}'), {"key": "value"})

        # 2. 마크다운 코드펜스
        fence = '```json\n{"groups": [{"patient": "홍길동"}]}\n```'
        self.assertEqual(vision.extract_json(fence), {"groups": [{"patient": "홍길동"}]})

        # 3. DeepSeek 등의 <think> 태그 내 가짜 JSON이 포함된 경우
        think_text = """<think>
사용자가 JSON을 요청했다.
예시: {"fake": 123}
</think>
```json
{"patient": "김철수", "diagnosis": "요추 염좌"}
```"""
        parsed = vision.extract_json(think_text)
        self.assertEqual(parsed["patient"], "김철수")
        self.assertEqual(parsed["diagnosis"], "요추 염좌")

        # 4. 잡담이 섞인 텍스트
        chatter = '결과는 다음과 같습니다: {"result": "ok"} 참고하세요.'
        self.assertEqual(vision.extract_json(chatter), {"result": "ok"})

    def test_norm_date(self):
        """다양한 날짜 표기 형식(대시, 슬래시, 점, 한글) 정규화 검증."""
        self.assertEqual(pipeline._norm_date("2026-08-10"), "2026-08-10")
        self.assertEqual(pipeline._norm_date("2026/08/10"), "2026-08-10")
        self.assertEqual(pipeline._norm_date("2026.8.5"), "2026-08-05")
        self.assertEqual(pipeline._norm_date("2026년 8월 10일"), "2026-08-10")
        self.assertEqual(pipeline._norm_date("2026년08월10일"), "2026-08-10")
        self.assertEqual(pipeline._norm_date(None, fallback="2026-07-01"), "2026-07-01")
        self.assertIsNone(pipeline._norm_date("날짜 없음"))

    def test_claim_treatment_dates_uses_current_metadata(self):
        """새 잡의 카드 메타데이터에서 치료 시작일과 종료일을 그대로 사용한다."""
        claim = {
            "date": "2026-01-01",
            "treatment_start": "2026-01-02",
            "treatment_end": "2026-02-03",
        }
        self.assertEqual(
            pipeline._claim_treatment_dates(claim),
            ("2026-01-02", "2026-02-03"),
        )

    def test_claim_treatment_dates_recovers_legacy_job_from_summary(self):
        """기간 필드가 없는 이전 잡은 summary.yaml의 치료기간으로 보완한다."""
        tmp = Path(tempfile.mkdtemp())
        orig_claims_dir = config.CLAIMS_DIR
        config.CLAIMS_DIR = tmp
        try:
            claim_dir = tmp / "legacy-claim"
            claim_dir.mkdir()
            (claim_dir / "summary.yaml").write_text(
                "치료기간: 2025-11-15~2026-02-02\n",
                encoding="utf-8",
            )

            self.assertEqual(
                pipeline._claim_treatment_dates({
                    "dir": "legacy-claim",
                    "date": "2025-11-15",
                }),
                ("2025-11-15", "2026-02-02"),
            )
        finally:
            config.CLAIMS_DIR = orig_claims_dir
            shutil.rmtree(tmp, ignore_errors=True)

    def test_claim_dir_name_collision(self):
        """디스크에 이미 존재하는 디렉터리 및 메모리 중복 시 (2) 접미사 자동 부여 검증."""
        tmp = Path(tempfile.mkdtemp())
        orig_claims_dir = config.CLAIMS_DIR
        config.CLAIMS_DIR = tmp
        try:
            g = {"date": "2026-08-10", "patient": "홍길동", "diagnosis": "골절"}
            dir1 = pipeline._claim_dir_name(g, 1)
            (tmp / dir1).mkdir(parents=True, exist_ok=True)

            dir2 = pipeline._claim_dir_name(g, 2)
            self.assertEqual(dir2, f"{dir1}(2)")
        finally:
            config.CLAIMS_DIR = orig_claims_dir
            shutil.rmtree(tmp, ignore_errors=True)

    def test_classify_chunk_image_nos_and_offset(self):
        """2번째 청크(offset > 0)에서 LLM이 상대 번호를 주었을 때의 오프셋 보정 검증."""
        async def fake_vision(prompt, paths, start_index=1, **kwargs):
            self.assertEqual(start_index, 11)
            return {"groups": [{"patient": "이영희", "image_nos": [1, 2]}]}

        orig_ask = vision.ask_vision
        vision.ask_vision = fake_vision
        try:
            paths = [f"dummy_{i}.jpg" for i in range(11, 14)]
            res = asyncio.run(pipeline._classify_chunk("test_job", paths, offset=10))
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0]["image_nos"], [11, 12])
        finally:
            vision.ask_vision = orig_ask

    def test_kcd_resolution(self):
        """KCD 코드 조회 및 진단명 한국어 병기 검증."""
        from backend import kcd

        # 질병코드 단독 조회
        self.assertEqual(kcd.resolve_disease_code("H368"), "기타 망막장애")
        self.assertEqual(kcd.resolve_disease_code("H400"), "녹내장의증")
        self.assertEqual(kcd.resolve_disease_code("H40.0"), "녹내장의증")
        self.assertEqual(kcd.resolve_disease_code("J209"), "급성 기관지염")
        self.assertEqual(kcd.resolve_disease_code("S335"), "요추의 염좌 및 긴장(요추 염좌)")

        # 진단명 서식화 (코드 단독 -> 설명 병기)
        self.assertEqual(
            kcd.format_diagnosis("H368, H400"),
            "H368(기타 망막장애), H400(녹내장의증)"
        )
        self.assertEqual(kcd.format_diagnosis("H368"), "H368(기타 망막장애)")

        # 이미 한글 진단명이 있거나 설명이 포함된 경우는 원문 보존
        self.assertEqual(kcd.format_diagnosis("요추 염좌"), "요추 염좌")
        self.assertEqual(kcd.format_diagnosis("요추 염좌 (S33.5)"), "요추 염좌 (S33.5)")
        self.assertEqual(
            kcd.format_diagnosis("H368(기타 망막장애), H400(녹내장의증)"),
            "H368(기타 망막장애), H400(녹내장의증)"
        )

    def test_convert_to_jpeg(self):
        """투명도가 있는 이미지를 흰 배경의 JPEG로 정상 변환하는지 검증."""
        tmp = Path(tempfile.mkdtemp())
        try:
            src = tmp / "test.png"
            img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 128))
            img.save(src, "PNG")

            dest = tmp / "converted.jpg"
            pipeline.convert_to_jpeg(src, dest)

            self.assertTrue(dest.exists())
            with Image.open(dest) as out_img:
                self.assertEqual(out_img.format, "JPEG")
                self.assertEqual(out_img.mode, "RGB")
                self.assertEqual(out_img.size, (100, 100))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_create_thumbnail_preserves_ratio_and_limits_size(self):
        """썸네일은 작은 JPEG로 생성되고 원본 비율과 최대 크기를 지킨다."""
        tmp = Path(tempfile.mkdtemp())
        try:
            src = tmp / "large.png"
            Image.new("RGBA", (1200, 600), color=(255, 0, 0, 128)).save(src, "PNG")

            thumbnail = pipeline.create_thumbnail(src)

            self.assertEqual(thumbnail.parent.name, ".thumbnails")
            self.assertLess(thumbnail.stat().st_size, src.stat().st_size)
            with Image.open(thumbnail) as loaded:
                self.assertEqual(loaded.format, "JPEG")
                self.assertEqual(loaded.mode, "RGB")
                self.assertEqual(loaded.size, (320, 160))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_materialize_claim_creates_relative_symlinks(self):
        """materialize_claim은 형식을 유지한 상대 링크로 업로드 원본을 참조한다."""
        tmp = Path(tempfile.mkdtemp())
        orig_claims_dir = config.CLAIMS_DIR
        config.CLAIMS_DIR = tmp
        try:
            job_id = "test_mat_job"
            job_dir = pipeline._jobs_dir(job_id)
            job_dir.mkdir(parents=True, exist_ok=True)

            # 테스트 원본 파일 생성 (jpg, png)
            img1 = Image.new("RGB", (60, 60), color="blue")
            img1.save(job_dir / "doc1.jpg", "JPEG")
            img2 = Image.new("RGB", (60, 60), color="green")
            img2.save(job_dir / "doc2.png", "PNG")

            with pipeline._jobs_lock:
                pipeline._jobs[job_id] = {
                    "id": job_id,
                    "files": [
                        {"saved": "doc1.jpg", "original": "doc1.jpg"},
                        {"saved": "doc2.png", "original": "doc2.png"},
                    ]
                }

            g = {
                "patient": "홍길동",
                "diagnosis": "H368, H400",
                "date": "2026-09-08",
                "image_nos": [1, 2]
            }

            claim_dir, moved = pipeline.materialize_claim(job_id, g, 1)
            self.assertTrue(claim_dir.is_dir())
            self.assertEqual(len(moved), 2)
            self.assertEqual([Path(path).suffix for path in moved], [".jpg", ".png"])
            for path_str, expected_name in zip(moved, ("doc1.jpg", "doc2.png")):
                p = Path(path_str)
                self.assertTrue(p.exists())
                self.assertTrue(p.is_symlink())
                self.assertFalse(p.readlink().is_absolute())
                self.assertEqual(p.resolve(), (job_dir / expected_name).resolve())
                with Image.open(p) as loaded:
                    self.assertEqual(loaded.size, (60, 60))
        finally:
            config.CLAIMS_DIR = orig_claims_dir
            shutil.rmtree(tmp, ignore_errors=True)
            shutil.rmtree(pipeline._jobs_dir("test_mat_job"), ignore_errors=True)

    def test_write_summary_places_patient_at_top_level(self):
        """환자명은 내부 메타데이터가 아니라 청구 정보의 최상위 필드로 기록한다."""
        tmp = Path(tempfile.mkdtemp())
        try:
            ex = {
                "patient": "이용관",
                "claim_type": "질병",
                "hospitalization": "통원",
                "treatment_start": "2025-11-15",
                "treatment_end": "2026-02-02",
                "diagnosis": "H368(기타 망막장애), H400(녹내장의증)",
                "incident_desc": None,
                "incident_place": None,
                "incident_datetime": None,
                "warnings": None,
            }

            pipeline.write_summary(tmp, ex, ["/tmp/IMG_6005.jpg"], "dd4404da")
            summary = yaml.safe_load((tmp / "summary.yaml").read_text(encoding="utf-8"))

            self.assertEqual(summary["환자"], "이용관")
            self.assertNotIn("환자", summary["_meta"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
