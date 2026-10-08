"""Bulk Certificate Generator - Flask application factory."""
import logging
import os

from flask import Flask

from .config import Config
from .db import init_db
from .service import JobRunner


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    os.makedirs(app.config["CERTIFICATE_DIR"], exist_ok=True)
    init_db(app.config["DATABASE"])

    app.extensions["job_runner"] = JobRunner(
        db_path=app.config["DATABASE"],
        certificate_dir=app.config["CERTIFICATE_DIR"],
        workers=app.config["WORKER_THREADS"],
        sync=app.config["PROCESS_SYNC"],
    )

    from .routes import bp
    app.register_blueprint(bp)

    return app
