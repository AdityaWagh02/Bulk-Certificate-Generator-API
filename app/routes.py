"""HTTP API."""
import io
import os
import zipfile

from flask import Blueprint, current_app, jsonify, request, send_file, url_for

from . import service
from .validators import PayloadError, validate_job_payload

bp = Blueprint("api", __name__)


def _db():
    return current_app.config["DATABASE"]


def _error(message, status, details=None):
    body = {"error": message}
    if details:
        body["details"] = details
    return jsonify(body), status


@bp.get("/health")
def health():
    return jsonify({"status": "ok"})


@bp.post("/api/jobs")
def create_job():
    data = request.get_json(silent=True)
    if data is None:
        return _error("Request body must be valid JSON", 400)

    try:
        payload = validate_job_payload(data, current_app.config["MAX_RECIPIENTS_PER_JOB"])
    except PayloadError as exc:
        return _error("Validation failed", 400, exc.errors)

    job_id, status = service.create_job(_db(), payload)

    # nothing valid -> nothing to process
    if status == service.PENDING:
        current_app.extensions["job_runner"].submit(job_id)

    info = service.get_job_status(_db(), job_id)
    info["status_url"] = url_for("api.job_status", job_id=job_id)
    info["certificates_url"] = url_for("api.job_certificates", job_id=job_id)
    return jsonify(info), 202


@bp.get("/api/jobs/<job_id>")
def job_status(job_id):
    info = service.get_job_status(_db(), job_id)
    if info is None:
        return _error("Job not found", 404)
    return jsonify(info)


@bp.get("/api/jobs/<job_id>/certificates")
def job_certificates(job_id):
    status = request.args.get("status")
    if status is not None:
        status = status.upper()
        if status not in (service.CERT_PENDING, service.CERT_SUCCESS, service.CERT_FAILED):
            return _error("status filter must be one of PENDING, SUCCESS, FAILED", 400)

    certs = service.list_certificates(_db(), job_id, status)
    if certs is None:
        return _error("Job not found", 404)

    items = []
    for c in certs:
        item = {
            "certificate_id": c["id"],
            "position": c["position"],
            "name": c["name"],
            "email": c["email"],
            "course": c["course"],
            "status": c["status"],
            "error": c["error"],
        }
        if c["status"] == service.CERT_SUCCESS:
            item["download_url"] = url_for("api.download_certificate", certificate_id=c["id"])
        items.append(item)
    return jsonify({"job_id": job_id, "count": len(items), "certificates": items})


@bp.get("/api/certificates/<certificate_id>/download")
def download_certificate(certificate_id):
    cert = service.get_certificate(_db(), certificate_id)
    if cert is None:
        return _error("Certificate not found", 404)
    if cert["status"] != service.CERT_SUCCESS or not cert["file_path"]:
        return _error("Certificate is not available (status: %s)" % cert["status"], 409)
    if not os.path.exists(cert["file_path"]):
        return _error("Certificate file is missing on the server", 410)

    safe_name = "".join(ch if ch.isalnum() else "_" for ch in cert["name"]).strip("_") or "certificate"
    return send_file(cert["file_path"], mimetype="application/pdf",
                     as_attachment=True, download_name=f"{safe_name}_certificate.pdf")


@bp.get("/api/jobs/<job_id>/download")
def download_job_zip(job_id):
    """Download every successfully generated certificate of the job as one ZIP."""
    certs = service.list_certificates(_db(), job_id, service.CERT_SUCCESS)
    if certs is None:
        return _error("Job not found", 404)
    if not certs:
        return _error("No certificates are available for this job yet", 409)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for c in certs:
            if c["file_path"] and os.path.exists(c["file_path"]):
                safe_name = "".join(ch if ch.isalnum() else "_" for ch in c["name"]).strip("_") or "certificate"
                zf.write(c["file_path"], arcname=f"{c['position'] + 1:04d}_{safe_name}.pdf")
    buffer.seek(0)
    return send_file(buffer, mimetype="application/zip", as_attachment=True,
                     download_name=f"certificates_{job_id}.zip")


@bp.app_errorhandler(404)
def not_found(_e):
    return _error("Not found", 404)
