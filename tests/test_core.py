"""핵심 파이프라인 및 비전 모듈 단위 테스트."""
import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from PIL import Image

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

    def test_convert_to_webp(self):
        """임의의 이미지를 WebP로 정상 변환하는지 검증."""
        tmp = Path(tempfile.mkdtemp())
        try:
            src = tmp / "test.png"
            img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 128))
            img.save(src, "PNG")

            dest = tmp / "converted.webp"
            pipeline.convert_to_webp(src, dest)

            self.assertTrue(dest.exists())
            with Image.open(dest) as out_img:
                self.assertEqual(out_img.format, "WEBP")
                self.assertEqual(out_img.size, (100, 100))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_materialize_claim_converts_to_webp(self):
        """materialize_claim이 모든 원본 이미지를 .webp로 변환하여 claim_dir에 저장하는지 검증."""
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
            for path_str in moved:
                p = Path(path_str)
                self.assertTrue(p.exists())
                self.assertEqual(p.suffix, ".webp")
                with Image.open(p) as loaded:
                    self.assertEqual(loaded.format, "WEBP")
        finally:
            config.CLAIMS_DIR = orig_claims_dir
            shutil.rmtree(tmp, ignore_errors=True)
            shutil.rmtree(pipeline._jobs_dir("test_mat_job"), ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
