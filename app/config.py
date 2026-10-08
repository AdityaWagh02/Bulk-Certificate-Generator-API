"""Application configuration.

Values can be overridden with environment variables or by passing a dict
to create_app() (the tests do this).
"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")


class Config:
    DATABASE = os.environ.get("CERT_DB_PATH", os.path.join(INSTANCE_DIR, "certificates.db"))
    CERTIFICATE_DIR = os.environ.get("CERT_STORAGE_DIR", os.path.join(INSTANCE_DIR, "certificates"))

    # A single request can carry at most this many recipients.
    MAX_RECIPIENTS_PER_JOB = int(os.environ.get("MAX_RECIPIENTS_PER_JOB", 1000))

    # Number of background worker threads (one job is processed by one worker).
    WORKER_THREADS = int(os.environ.get("WORKER_THREADS", 2))

    # If True the job is processed inside the request itself.
    # Only used by the tests so results are deterministic.
    PROCESS_SYNC = False

    TESTING = False
