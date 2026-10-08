"""Tests for the Bulk Certificate Generator.

Run with either:
    python -m unittest discover -v
    pytest -v
Jobs are processed synchronously in the tests (PROCESS_SYNC=True) so the
results can be checked right after the POST request.
"""
import os
import shutil
import tempfile
import unittest
import zipfile
import io
from unittest import mock

from app import create_app
from app import certificate as certificate_module

VALID_PAYLOAD = {
    "event_name": "Python Bootcamp 2026",
    "issued_by": "CDAC Pune",
    "issue_date": "2026-10-01",
    "recipients": [
        {"name": "Amit Sharma", "email": "amit@example.com", "course": "Backend"},
        {"name": "Priya Patil", "email": "priya@example.com"},
    ],
}


def make_payload(**overrides):
    payload = {**VALID_PAYLOAD, "recipients": [dict(r) for r in VALID_PAYLOAD["recipients"]]}
    payload.update(overrides)
    return payload


class BaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.app = create_app({
            "TESTING": True,
            "PROCESS_SYNC": True,
            "DATABASE": os.path.join(self.tmp, "test.db"),
            "CERTIFICATE_DIR": os.path.join(self.tmp, "certs"),
            "MAX_RECIPIENTS_PER_JOB": 50,
        })
        self.client = self.app.test_client()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def post_job(self, payload):
        return self.client.post("/api/jobs", json=payload)


class TestCreateJob(BaseTest):
    def test_create_job_returns_202_and_job_info(self):
        resp = self.post_job(make_payload())
        self.assertEqual(resp.status_code, 202)
        body = resp.get_json()
        self.assertIn("job_id", body)
        self.assertEqual(body["total"], 2)
        self.assertTrue(body["status_url"].endswith(body["job_id"]))

    def test_job_is_processed_and_completed(self):
        body = self.post_job(make_payload()).get_json()
        status = self.client.get(f"/api/jobs/{body['job_id']}").get_json()
        self.assertEqual(status["status"], "COMPLETED")
        self.assertEqual(status["successful"], 2)
        self.assertEqual(status["failed"], 0)

    def test_issue_date_defaults_to_today(self):
        payload = make_payload()
        del payload["issue_date"]
        body = self.post_job(payload).get_json()
        self.assertRegex(body["issue_date"], r"^\d{4}-\d{2}-\d{2}$")


class TestValidation(BaseTest):
    def test_non_json_body_rejected(self):
        resp = self.client.post("/api/jobs", data="not json", content_type="text/plain")
        self.assertEqual(resp.status_code, 400)

    def test_missing_job_fields_rejected(self):
        resp = self.post_job({"recipients": [{"name": "A", "email": "a@b.com"}]})
        self.assertEqual(resp.status_code, 400)
        details = resp.get_json()["details"]
        self.assertTrue(any("event_name" in d for d in details))
        self.assertTrue(any("issued_by" in d for d in details))

    def test_empty_recipient_list_rejected(self):
        resp = self.post_job(make_payload(recipients=[]))
        self.assertEqual(resp.status_code, 400)

    def test_recipients_must_be_list(self):
        resp = self.post_job(make_payload(recipients="amit"))
        self.assertEqual(resp.status_code, 400)

    def test_too_many_recipients_rejected(self):
        many = [{"name": f"User {i}", "email": f"user{i}@example.com"} for i in range(51)]
        resp = self.post_job(make_payload(recipients=many))
        self.assertEqual(resp.status_code, 400)

    def test_bad_date_rejected(self):
        resp = self.post_job(make_payload(issue_date="01-10-2026"))
        self.assertEqual(resp.status_code, 400)

    def test_invalid_recipients_marked_failed_but_valid_ones_generated(self):
        recipients = [
            {"name": "Good One", "email": "good@example.com"},
            {"name": "", "email": "noname@example.com"},
            {"name": "Bad Email", "email": "not-an-email"},
            {"email": "missing-name@example.com"},
            {"name": "Good One Again", "email": "GOOD@example.com"},  # duplicate (case-insensitive)
            "not an object",
        ]
        body = self.post_job(make_payload(recipients=recipients)).get_json()
        status = self.client.get(f"/api/jobs/{body['job_id']}").get_json()
        self.assertEqual(status["status"], "COMPLETED_WITH_ERRORS")
        self.assertEqual(status["successful"], 1)
        self.assertEqual(status["failed"], 5)

        certs = self.client.get(f"/api/jobs/{body['job_id']}/certificates").get_json()["certificates"]
        errors = {c["position"]: c["error"] for c in certs if c["status"] == "FAILED"}
        self.assertIn("name is required", errors[1])
        self.assertIn("email is not valid", errors[2])
        self.assertIn("duplicate", errors[4])

    def test_all_recipients_invalid_gives_failed_job(self):
        body = self.post_job(make_payload(recipients=[{"name": "x"}, {"email": "y"}])).get_json()
        self.assertEqual(body["status"], "FAILED")
        self.assertEqual(body["failed"], 2)


class TestCertificateGeneration(BaseTest):
    def test_pdf_is_created_with_recipient_data(self):
        out = os.path.join(self.tmp, "single.pdf")
        certificate_module.generate_certificate(
            out, name="Amit Sharma", event_name="Python Bootcamp",
            issued_by="CDAC Pune", issue_date="2026-10-01", course="Backend")
        with open(out, "rb") as f:
            data = f.read()
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 1000)
        self.assertFalse(os.path.exists(out + ".tmp"))

    def test_very_long_name_still_generates(self):
        out = os.path.join(self.tmp, "long.pdf")
        certificate_module.generate_certificate(
            out, name="A" * 100, event_name="E" * 120,
            issued_by="CDAC", issue_date="2026-10-01")
        self.assertTrue(os.path.exists(out))

    def test_one_file_per_valid_recipient(self):
        body = self.post_job(make_payload()).get_json()
        job_dir = os.path.join(self.app.config["CERTIFICATE_DIR"], body["job_id"])
        self.assertEqual(len(os.listdir(job_dir)), 2)


class TestJobStatus(BaseTest):
    def test_unknown_job_returns_404(self):
        self.assertEqual(self.client.get("/api/jobs/doesnotexist").status_code, 404)

    def test_status_fields_and_progress(self):
        body = self.post_job(make_payload()).get_json()
        status = self.client.get(f"/api/jobs/{body['job_id']}").get_json()
        for key in ("job_id", "status", "total", "successful", "failed", "pending",
                    "progress_percent", "created_at", "completed_at"):
            self.assertIn(key, status)
        self.assertEqual(status["progress_percent"], 100.0)
        self.assertEqual(status["pending"], 0)
        self.assertIsNotNone(status["completed_at"])


class TestIndividualFailure(BaseTest):
    def test_one_failing_certificate_does_not_stop_the_others(self):
        recipients = [
            {"name": "First Person", "email": "first@example.com"},
            {"name": "Explode Me", "email": "boom@example.com"},
            {"name": "Third Person", "email": "third@example.com"},
        ]
        real = certificate_module.generate_certificate

        def flaky(output_path, name, *args, **kwargs):
            if name == "Explode Me":
                raise RuntimeError("simulated rendering error")
            return real(output_path, name, *args, **kwargs)

        with mock.patch("app.certificate.generate_certificate", side_effect=flaky):
            body = self.post_job(make_payload(recipients=recipients)).get_json()

        status = self.client.get(f"/api/jobs/{body['job_id']}").get_json()
        self.assertEqual(status["status"], "COMPLETED_WITH_ERRORS")
        self.assertEqual(status["successful"], 2)
        self.assertEqual(status["failed"], 1)

        certs = self.client.get(f"/api/jobs/{body['job_id']}/certificates").get_json()["certificates"]
        failed = [c for c in certs if c["status"] == "FAILED"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["name"], "Explode Me")
        self.assertIn("simulated rendering error", failed[0]["error"])
        self.assertNotIn("download_url", failed[0])

        # the failed certificate cannot be downloaded
        resp = self.client.get(f"/api/certificates/{failed[0]['certificate_id']}/download")
        self.assertEqual(resp.status_code, 409)

    def test_all_certificates_failing_marks_job_failed(self):
        with mock.patch("app.certificate.generate_certificate", side_effect=RuntimeError("down")):
            body = self.post_job(make_payload()).get_json()
        status = self.client.get(f"/api/jobs/{body['job_id']}").get_json()
        self.assertEqual(status["status"], "FAILED")
        self.assertEqual(status["failed"], 2)


class TestRetrieval(BaseTest):
    def setUp(self):
        super().setUp()
        self.job_id = self.post_job(make_payload()).get_json()["job_id"]

    def test_list_certificates(self):
        data = self.client.get(f"/api/jobs/{self.job_id}/certificates").get_json()
        self.assertEqual(data["count"], 2)
        self.assertEqual(data["certificates"][0]["name"], "Amit Sharma")
        self.assertIn("download_url", data["certificates"][0])

    def test_status_filter(self):
        data = self.client.get(f"/api/jobs/{self.job_id}/certificates?status=failed").get_json()
        self.assertEqual(data["count"], 0)
        resp = self.client.get(f"/api/jobs/{self.job_id}/certificates?status=bogus")
        self.assertEqual(resp.status_code, 400)

    def test_download_single_certificate(self):
        certs = self.client.get(f"/api/jobs/{self.job_id}/certificates").get_json()["certificates"]
        resp = self.client.get(certs[0]["download_url"])
        self.addCleanup(resp.close)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "application/pdf")
        self.assertTrue(resp.data.startswith(b"%PDF"))
        self.assertIn("Amit_Sharma", resp.headers["Content-Disposition"])

    def test_download_zip(self):
        resp = self.client.get(f"/api/jobs/{self.job_id}/download")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.mimetype, "application/zip")
        with zipfile.ZipFile(io.BytesIO(resp.data)) as zf:
            self.assertEqual(len(zf.namelist()), 2)

    def test_unknown_ids_return_404(self):
        self.assertEqual(self.client.get("/api/jobs/nope/certificates").status_code, 404)
        self.assertEqual(self.client.get("/api/certificates/nope/download").status_code, 404)
        self.assertEqual(self.client.get("/api/jobs/nope/download").status_code, 404)

    def test_zip_with_no_successful_certificates(self):
        job = self.post_job(make_payload(recipients=[{"name": "x"}])).get_json()
        resp = self.client.get(f"/api/jobs/{job['job_id']}/download")
        self.assertEqual(resp.status_code, 409)


class TestBackgroundProcessing(unittest.TestCase):
    """Uses the real thread pool (PROCESS_SYNC=False) and polls the status."""

    def test_job_finishes_in_background(self):
        import time
        tmp = tempfile.mkdtemp()
        try:
            app = create_app({
                "TESTING": True, "PROCESS_SYNC": False,
                "DATABASE": os.path.join(tmp, "bg.db"),
                "CERTIFICATE_DIR": os.path.join(tmp, "certs"),
            })
            client = app.test_client()
            recipients = [{"name": f"User {i}", "email": f"user{i}@example.com"} for i in range(20)]
            job_id = client.post("/api/jobs", json=make_payload(recipients=recipients)).get_json()["job_id"]

            status = None
            for _ in range(100):
                status = client.get(f"/api/jobs/{job_id}").get_json()
                if status["status"] not in ("PENDING", "PROCESSING"):
                    break
                time.sleep(0.1)
            self.assertEqual(status["status"], "COMPLETED")
            self.assertEqual(status["successful"], 20)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
