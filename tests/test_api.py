"""FastAPI 엔드포인트 보안 및 기능 단위 테스트."""
import io
import shutil
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
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
        """청구 파일과 썸네일 서빙, ZIP의 링크 역참조를 검증."""
        from backend import config, pipeline
        from PIL import Image

        claim_dir = config.CLAIMS_DIR / "test_claim_dir"
        upload_dir = config.UPLOADS_DIR / "test_claim_source"
        claim_dir.mkdir(parents=True, exist_ok=True)
        upload_dir.mkdir(parents=True, exist_ok=True)
        try:
            img = Image.new("RGB", (900, 450), color="white")
            source = upload_dir / "test.jpg"
            img.save(source, "JPEG", quality=95)
            (claim_dir / "test.jpg").symlink_to(source)
            (claim_dir / "summary.yaml").write_text("청구사유: 질병\n", encoding="utf-8")

            # 1. 정상 파일 서빙
            resp = self.client.get("/api/claims/test_claim_dir/test.jpg")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers.get("content-type"), "image/jpeg")

            # 2. 목록용 썸네일은 작은 JPEG와 장기 캐시 헤더를 반환
            resp = self.client.get("/api/claims/test_claim_dir/test.jpg?thumbnail=true")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers.get("content-type"), "image/jpeg")
            self.assertIn("immutable", resp.headers.get("cache-control", ""))
            with Image.open(io.BytesIO(resp.content)) as thumbnail:
                self.assertEqual(thumbnail.size, pipeline.THUMBNAIL_SIZE[:1] + (160,))

            # 3. 존재하지 않는 파일 404
            resp = self.client.get("/api/claims/test_claim_dir/none.jpg")
            self.assertEqual(resp.status_code, 404)

            # 4. 존재하지 않는 디렉터리 404
            resp = self.client.get("/api/claims/not_exist_dir/test.jpg")
            self.assertEqual(resp.status_code, 404)

            # 5. ZIP에는 링크가 아닌 원본 이미지 바이트와 청구 정보가 포함
            resp = self.client.get("/api/claims/test_claim_dir/download")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers.get("content-type"), "application/zip")
            with zipfile.ZipFile(io.BytesIO(resp.content)) as archive:
                self.assertEqual(
                    archive.namelist(),
                    ["test_claim_dir/test.jpg", "test_claim_dir/summary.yaml"],
                )
                self.assertEqual(archive.read("test_claim_dir/test.jpg"), source.read_bytes())
                archived_mode = archive.getinfo("test_claim_dir/test.jpg").external_attr >> 16
                self.assertFalse(stat.S_ISLNK(archived_mode))
                self.assertIn("청구사유: 질병", archive.read("test_claim_dir/summary.yaml").decode())
        finally:
            shutil.rmtree(claim_dir, ignore_errors=True)
            shutil.rmtree(upload_dir, ignore_errors=True)

    def test_delete_job_removes_uploads_thumbnails_and_claims(self):
        """작업 삭제 API는 파생 데이터까지 통째로 지운다."""
        from backend import config, pipeline
        from PIL import Image

        tmp = Path(tempfile.mkdtemp())
        original_uploads = config.UPLOADS_DIR
        original_claims = config.CLAIMS_DIR
        config.UPLOADS_DIR = tmp / "uploads"
        config.CLAIMS_DIR = tmp / "claims"
        config.UPLOADS_DIR.mkdir()
        config.CLAIMS_DIR.mkdir()
        job_id = "delete01"
        try:
            job_dir = config.UPLOADS_DIR / job_id
            job_dir.mkdir()
            source = job_dir / "document.jpg"
            Image.new("RGB", (640, 480), color="blue").save(source, "JPEG")
            pipeline.create_thumbnail(source)

            claim_dir = config.CLAIMS_DIR / "delete-claim"
            claim_dir.mkdir()
            (claim_dir / source.name).symlink_to(source)
            (claim_dir / "summary.yaml").write_text(
                f"_meta:\n  job_id: {job_id}\n",
                encoding="utf-8",
            )
            job = {
                "id": job_id,
                "status": "done",
                "created_at": "2026-09-09T00:00:00",
                "files": [{"saved": source.name, "original": source.name}],
                "claims": [{"dir": claim_dir.name}],
            }
            with pipeline._jobs_lock:
                pipeline._jobs[job_id] = job
            (job_dir / "job.json").write_text("{}", encoding="utf-8")

            response = self.client.delete(f"/api/jobs/{job_id}")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["deleted_claims"], 1)
            self.assertFalse(job_dir.exists())
            self.assertFalse(claim_dir.exists())
            self.assertIsNone(pipeline.get_job(job_id))
            with self.assertRaises(pipeline.JobDeleted):
                pipeline.materialize_claim(
                    job_id,
                    {
                        "patient": "삭제됨",
                        "diagnosis": "",
                        "date": "2026-09-09",
                        "image_nos": [1],
                    },
                    1,
                )
        finally:
            with pipeline._jobs_lock:
                pipeline._jobs.pop(job_id, None)
                pipeline._deleted_jobs.discard(job_id)
            config.UPLOADS_DIR = original_uploads
            config.CLAIMS_DIR = original_claims
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
