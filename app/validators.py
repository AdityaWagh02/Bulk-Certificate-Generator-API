"""Validation of the incoming request body.

Two levels:
  1. validate_job_payload()  -> problems with the request itself (whole request is rejected, HTTP 400)
  2. validate_recipient()    -> problems with a single recipient (only that recipient is marked FAILED)
"""
import re
from datetime import date, datetime

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

MAX_NAME_LEN = 100
MAX_FIELD_LEN = 150


class PayloadError(Exception):
    """Raised when the whole request is invalid."""

    def __init__(self, errors):
        super().__init__("Invalid request")
        self.errors = errors


def _clean(value):
    return value.strip() if isinstance(value, str) else value


def validate_job_payload(data, max_recipients):
    """Validate job-level fields and return a cleaned dict."""
    errors = []

    if not isinstance(data, dict):
        raise PayloadError(["Request body must be a JSON object"])

    event_name = _clean(data.get("event_name"))
    issued_by = _clean(data.get("issued_by"))
    issue_date = _clean(data.get("issue_date"))
    recipients = data.get("recipients")

    if not event_name or not isinstance(event_name, str):
        errors.append("event_name is required")
    elif len(event_name) > MAX_FIELD_LEN:
        errors.append(f"event_name must be at most {MAX_FIELD_LEN} characters")

    if not issued_by or not isinstance(issued_by, str):
        errors.append("issued_by is required")
    elif len(issued_by) > MAX_FIELD_LEN:
        errors.append(f"issued_by must be at most {MAX_FIELD_LEN} characters")

    # issue_date is optional, defaults to today
    if issue_date in (None, ""):
        issue_date = date.today().isoformat()
    else:
        try:
            issue_date = datetime.strptime(str(issue_date), "%Y-%m-%d").date().isoformat()
        except ValueError:
            errors.append("issue_date must be in YYYY-MM-DD format")

    if not isinstance(recipients, list):
        errors.append("recipients must be a list")
    elif len(recipients) == 0:
        errors.append("recipients must contain at least one recipient")
    elif len(recipients) > max_recipients:
        errors.append(f"A single job can contain at most {max_recipients} recipients")

    if errors:
        raise PayloadError(errors)

    return {
        "event_name": event_name,
        "issued_by": issued_by,
        "issue_date": issue_date,
        "recipients": recipients,
    }


def validate_recipient(recipient, seen_emails):
    """Validate one recipient.

    Returns (cleaned_recipient, error_message). error_message is None when valid.
    `seen_emails` is a set used to detect duplicates inside the same job.
    """
    if not isinstance(recipient, dict):
        return {"name": None, "email": None, "course": None}, "Recipient must be an object"

    name = _clean(recipient.get("name"))
    email = _clean(recipient.get("email"))
    course = _clean(recipient.get("course"))

    cleaned = {
        "name": name if isinstance(name, str) else None,
        "email": email.lower() if isinstance(email, str) else None,
        "course": course if isinstance(course, str) and course else None,
    }

    problems = []

    if not name or not isinstance(name, str):
        problems.append("name is required")
    elif len(name) > MAX_NAME_LEN:
        problems.append(f"name must be at most {MAX_NAME_LEN} characters")

    if not email or not isinstance(email, str):
        problems.append("email is required")
    elif not EMAIL_RE.match(email):
        problems.append("email is not valid")
    elif email.lower() in seen_emails:
        problems.append("duplicate email in this job")

    if course is not None and course != "":
        if not isinstance(course, str):
            problems.append("course must be a string")
        elif len(course) > MAX_FIELD_LEN:
            problems.append(f"course must be at most {MAX_FIELD_LEN} characters")

    if problems:
        return cleaned, "; ".join(problems)

    seen_emails.add(cleaned["email"])
    return cleaned, None
