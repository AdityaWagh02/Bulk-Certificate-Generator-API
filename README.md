# Bulk Certificate Generator (Backend)

A REST API that accepts **one request containing many recipients**, generates a PDF
certificate for every valid recipient from a single predefined template, tracks the
progress of the job, and lets the client download the results.

**Stack:** Python 3.10+, Flask, SQLite (relational DB, via the built-in `sqlite3` module), ReportLab (PDF).

---

## 1. Project structure

```
bulk_certificate_generator/
├── app/
│   ├── __init__.py       # Flask app factory
│   ├── config.py         # settings (db path, limits, worker threads)
│   ├── db.py             # SQLite schema + connection helper
│   ├── validators.py     # request / recipient validation
│   ├── certificate.py    # PDF template (ReportLab)
│   ├── service.py        # create job, process job, status queries, thread pool
│   └── routes.py         # HTTP endpoints
├── tests/test_api.py     # 25 tests
├── samples/sample_request.json
├── run.py                # entry point
└── requirements.txt
```

## 2. Setup

```bash
# 1. (optional but recommended) virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 2. install dependencies
pip install -r requirements.txt
```

No database server is needed. The SQLite file and the generated PDFs are created
automatically in the `instance/` folder on first start.

## 3. Run the application

```bash
python run.py
```

The API is now available at `http://127.0.0.1:5000`  (health check: `GET /health`).

Optional environment variables: `PORT`, `WORKER_THREADS` (default 2),
`MAX_RECIPIENTS_PER_JOB` (default 1000), `CERT_DB_PATH`, `CERT_STORAGE_DIR`.

## 4. Run the tests

```bash
python -m unittest discover -v
# or, if you have pytest installed:
pytest -v
```

The tests use a temporary database/folder, so they never touch real data.

## 5. API usage

### 5.1 Submit a bulk generation request

```bash
curl -X POST http://127.0.0.1:5000/api/jobs \
     -H "Content-Type: application/json" \
     -d @samples/sample_request.json
```

Request body:

| Field        | Required | Notes                                         |
|--------------|----------|-----------------------------------------------|
| `event_name` | yes      | printed on the certificate                    |
| `issued_by`  | yes      | organisation / signatory                      |
| `issue_date` | no       | `YYYY-MM-DD`, defaults to today               |
| `recipients` | yes      | list of 1..1000 objects: `name`, `email` (required), `course` (optional) |

Response `202 Accepted`:

```json
{
  "job_id": "1dbc990d9e9d4d0cab1e1be7d3903a5e",
  "status": "PENDING",
  "total": 4, "successful": 0, "failed": 1, "pending": 3,
  "progress_percent": 25.0,
  "status_url": "/api/jobs/1dbc990d...",
  "certificates_url": "/api/jobs/1dbc990d.../certificates"
}
```

### 5.2 Check progress

```bash
curl http://127.0.0.1:5000/api/jobs/<job_id>
```

```json
{
  "job_id": "1dbc990d...",
  "status": "COMPLETED_WITH_ERRORS",
  "total": 4, "successful": 3, "failed": 1, "pending": 0,
  "progress_percent": 100.0,
  "created_at": "2026-10-08T16:48:55+00:00",
  "completed_at": "2026-10-08T16:48:55+00:00"
}
```

Job status values:

| Status                  | Meaning                                           |
|-------------------------|---------------------------------------------------|
| `PENDING`               | accepted, waiting for a worker                    |
| `PROCESSING`            | a worker is generating certificates               |
| `COMPLETED`             | every certificate succeeded                       |
| `COMPLETED_WITH_ERRORS` | some succeeded, some failed                       |
| `FAILED`                | nothing could be generated                        |

### 5.3 List certificates of a job (with per-recipient result)

```bash
curl http://127.0.0.1:5000/api/jobs/<job_id>/certificates
curl "http://127.0.0.1:5000/api/jobs/<job_id>/certificates?status=FAILED"   # only failures
```

Each item contains `certificate_id`, `position` (index in the original request),
`name`, `email`, `status` (`SUCCESS` / `FAILED` / `PENDING`), `error` (reason when
failed) and `download_url` (only when successful).

### 5.4 Retrieve generated certificates

```bash
# one certificate (PDF)
curl -o amit.pdf http://127.0.0.1:5000/api/certificates/<certificate_id>/download

# all successful certificates of a job as a ZIP
curl -o certificates.zip http://127.0.0.1:5000/api/jobs/<job_id>/download
```

### 5.5 Error responses

| Code | When                                                                 |
|------|----------------------------------------------------------------------|
| 400  | body is not JSON, job-level validation failed, bad `status` filter   |
| 404  | unknown job / certificate id                                         |
| 409  | certificate failed or not generated yet / no certificates in the job |
| 410  | PDF file was removed from disk                                       |

## 6. Design decisions

**Asynchronous (background) processing.**
`POST /api/jobs` validates the request, saves everything to the database and returns
`202 Accepted` immediately. A `ThreadPoolExecutor` (2 workers by default) generates the
PDFs afterwards, and the client polls `GET /api/jobs/<id>`.
*Why:* a job may contain hundreds or thousands of recipients; doing it inside the HTTP
request would be slow and risk timeouts. A thread pool needs no extra infrastructure
(Celery + Redis would be the next step for production). ReportLab is CPU-light so threads
are good enough for this scope.

**Two levels of validation.**
1. *Request level* (missing `event_name`, empty list, more than 1000 recipients, bad
   date): the whole request is rejected with `400` and a list of problems.
2. *Recipient level* (missing name, invalid email, duplicate email in the same job): the
   job is still accepted, the bad recipient is stored as `FAILED` with a readable reason,
   and valid recipients are generated normally.

**Failure isolation.** Each certificate is generated inside its own `try/except` and its
result is committed to the database straight away. One failure never stops the others,
and it also makes the progress endpoint show live numbers. If every recipient fails the
job becomes `FAILED`, otherwise `COMPLETED_WITH_ERRORS`.

**Database.** Two tables: `jobs` and `certificates` (one row per recipient, foreign key to
the job). The row stores status, error message and the file path. SQLite keeps the setup
simple; the SQL is standard so moving to PostgreSQL/MySQL only needs a different driver.
A new connection is opened per operation so request threads and worker threads never
share one connection.

**PDF safety.** A PDF is first written to a `.tmp` file and then renamed, so a crash cannot
leave a half-written certificate that looks valid. Long names/event titles automatically
shrink the font so they stay inside the border.

**Single template.** One landscape A4 design is hard-coded in `app/certificate.py`, as the
assignment says no template editor is needed.

**Email uniqueness** is checked per job (case-insensitive), to catch accidental duplicate rows
in the submitted list.

## 7. Known limitations / possible improvements

- If the server is stopped while a job is `PROCESSING`, that job is not resumed automatically
  on restart (a startup "re-queue unfinished jobs" step would fix this).
- Names with characters outside the standard Latin set (for example Devanagari) cannot be
  drawn with the built-in Helvetica font and are reported as `FAILED` for that recipient. Registering
  a Unicode TTF font in ReportLab would solve this.
- No authentication or rate limiting.
- Sending the certificates by email, and a database migration tool, were left out on purpose
  to keep the required functionality simple.
