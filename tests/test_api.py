"""FastAPI 엔드포인트 보안 및 기능 단위 테스트."""
import unittest
from fastapi.testclient import TestClient
from backend.main import app


class TestAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_job_id_validation(self):
        """job_id에 특수문자나 상위 경로 참조가 포함되었을 때 400 차단 검증."""
        resp = self.client.get("/api/jobs/bad..id")
        self.assertEqual(resp.status_code, 400)

        resp = self.client.get("/api/jobs/bad$id")
        self.assertEqual(resp.status_code, 400)

        resp = self.client.get("/api/images/bad..id/test.jpg")
        self.assertEqual(resp.status_code, 400)

    def test_list_jobs_endpoint(self):
        """잡 목록 조회 정상 응답 확인."""
        resp = self.client.get("/api/jobs")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("jobs", data)
        self.assertIsInstance(data["jobs"], list)


    def test_claim_file_endpoint(self):
        """청구 디렉터리 내 파일 서빙 및 경로 traversal 방지 검증."""
        from backend import config
        from PIL import Image

        claim_dir = config.CLAIMS_DIR / "test_claim_dir"
        claim_dir.mkdir(parents=True, exist_ok=True)
        try:
            img = Image.new("RGB", (30, 30), color="white")
            img.save(claim_dir / "test.webp", "WEBP")

            # 1. 정상 파일 서빙
            resp = self.client.get("/api/claims/test_claim_dir/test.webp")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers.get("content-type"), "image/webp")

            # 2. 존재하지 않는 파일 404
            resp = self.client.get("/api/claims/test_claim_dir/none.webp")
            self.assertEqual(resp.status_code, 404)

            # 3. 존재하지 않는 디렉터리 404
            resp = self.client.get("/api/claims/not_exist_dir/test.webp")
            self.assertEqual(resp.status_code, 404)
        finally:
            import shutil
            shutil.rmtree(claim_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
