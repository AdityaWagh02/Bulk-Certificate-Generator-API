"""Certificate rendering using ReportLab.

There is only ONE predefined template (a landscape A4 page with a double
border). Only the recipient specific text changes.
"""
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

PAGE_W, PAGE_H = landscape(A4)
DARK_BLUE = colors.HexColor("#1F3A5F")
GOLD = colors.HexColor("#B8860B")
GREY = colors.HexColor("#555555")


def _fit_font_size(text, font, max_size, max_width, min_size=14):
    """Reduce the font size until the text fits in max_width."""
    size = max_size
    while size > min_size and stringWidth(text, font, size) > max_width:
        size -= 1
    return size


def generate_certificate(output_path, name, event_name, issued_by, issue_date, course=None):
    """Create one certificate PDF at output_path.

    Raises an exception if the PDF cannot be produced (for example when the
    name has characters the built in font cannot draw). The caller handles
    the exception so that one bad certificate does not stop the whole job.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # write to a temp file first so we never leave a half written PDF behind
    tmp_path = output_path + ".tmp"
    try:
        c = canvas.Canvas(tmp_path, pagesize=(PAGE_W, PAGE_H))
        c.setTitle(f"Certificate - {name}")
        c.setAuthor(issued_by)

        # --- double border ---
        c.setStrokeColor(DARK_BLUE)
        c.setLineWidth(6)
        c.rect(25, 25, PAGE_W - 50, PAGE_H - 50)
        c.setStrokeColor(GOLD)
        c.setLineWidth(2)
        c.rect(38, 38, PAGE_W - 76, PAGE_H - 76)

        center = PAGE_W / 2
        max_text_width = PAGE_W - 160

        # --- heading ---
        c.setFillColor(DARK_BLUE)
        c.setFont("Helvetica-Bold", 38)
        c.drawCentredString(center, PAGE_H - 120, "CERTIFICATE OF COMPLETION")

        c.setFillColor(GREY)
        c.setFont("Helvetica", 16)
        c.drawCentredString(center, PAGE_H - 170, "This is to certify that")

        # --- recipient name (font shrinks for long names) ---
        size = _fit_font_size(name, "Helvetica-Bold", 40, max_text_width)
        c.setFillColor(GOLD)
        c.setFont("Helvetica-Bold", size)
        c.drawCentredString(center, PAGE_H - 235, name)
        name_width = stringWidth(name, "Helvetica-Bold", size)
        c.setStrokeColor(GOLD)
        c.setLineWidth(1)
        c.line(center - name_width / 2 - 20, PAGE_H - 245, center + name_width / 2 + 20, PAGE_H - 245)

        # --- body ---
        c.setFillColor(GREY)
        c.setFont("Helvetica", 16)
        c.drawCentredString(center, PAGE_H - 285, "has successfully participated in")

        event_size = _fit_font_size(event_name, "Helvetica-Bold", 26, max_text_width)
        c.setFillColor(DARK_BLUE)
        c.setFont("Helvetica-Bold", event_size)
        c.drawCentredString(center, PAGE_H - 325, event_name)

        if course:
            course_size = _fit_font_size(course, "Helvetica-Oblique", 18, max_text_width)
            c.setFillColor(GREY)
            c.setFont("Helvetica-Oblique", course_size)
            c.drawCentredString(center, PAGE_H - 355, f"Course / Track: {course}")

        # --- footer ---
        c.setFillColor(GREY)
        c.setFont("Helvetica", 13)
        c.drawString(90, 95, f"Date: {issue_date}")
        c.drawRightString(PAGE_W - 90, 95, f"Issued by: {issued_by}")
        c.line(PAGE_W - 290, 110, PAGE_W - 90, 110)

        c.showPage()
        c.save()
        os.replace(tmp_path, output_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
