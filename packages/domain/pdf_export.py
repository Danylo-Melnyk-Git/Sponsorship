"""Generate downloadable, Cyrillic-capable PDF reports from Markdown."""
from html import escape
from io import BytesIO
from pathlib import Path
import re


class PDFUnavailable(RuntimeError):
    pass


def _font_path():
    paths = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
    ]
    return next((path for path in paths if path.is_file()), None)


def _inline(text):
    value = escape(text, quote=False)
    value = re.sub(r"\[([^\]]+)\]\((https?://[^ )]+)\)", r"\1 — \2", value)
    value = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"`([^`]+)`", r"<font name='SponsorMono'>\1</font>", value)
    return value


def pdf_bytes(markdown, title="Отчёт Sponsorship"):
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except ImportError as error:
        raise PDFUnavailable("Для PDF установите зависимости: pip install -r requirements-pdf.txt") from error

    font_path = _font_path()
    if font_path is None:
        raise PDFUnavailable("Не найден шрифт с поддержкой кириллицы (Arial или DejaVu Sans)")
    if "SponsorSans" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("SponsorSans", str(font_path)))
    pdfmetrics.registerFontFamily("SponsorSans", normal="SponsorSans", bold="SponsorSans", italic="SponsorSans", boldItalic="SponsorSans")
    if "SponsorMono" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("SponsorMono", str(font_path)))

    base = getSampleStyleSheet()
    normal = ParagraphStyle("SponsorBody", parent=base["BodyText"], fontName="SponsorSans", fontSize=9,
                            leading=13, textColor=colors.HexColor("#26352e"), spaceAfter=6)
    heading = ParagraphStyle("SponsorHeading", parent=base["Heading1"], fontName="SponsorSans", fontSize=18,
                             leading=23, textColor=colors.HexColor("#173e35"), spaceBefore=13, spaceAfter=9)
    subheading = ParagraphStyle("SponsorSubheading", parent=base["Heading2"], fontName="SponsorSans", fontSize=12,
                                leading=16, textColor=colors.HexColor("#245449"), spaceBefore=9, spaceAfter=5)
    small_heading = ParagraphStyle("SponsorSmallHeading", parent=subheading, fontSize=10, leading=14)
    bullet = ParagraphStyle("SponsorBullet", parent=normal, leftIndent=14, firstLineIndent=-9)
    code = ParagraphStyle("SponsorCode", parent=normal, fontSize=8, leading=11, backColor=colors.HexColor("#f1f3ef"),
                          borderPadding=5, leftIndent=6, rightIndent=6)
    styles = {1: heading, 2: subheading, 3: small_heading}
    story, fenced = [], False
    for raw in markdown.splitlines():
        line = raw.strip()
        if line.startswith("```"):
            fenced = not fenced
            continue
        if not line:
            story.append(Spacer(1, 3))
        elif fenced:
            story.append(Paragraph(_inline(line), code))
        elif re.fullmatch(r"[-*_]{3,}", line):
            story.append(Spacer(1, 5))
        elif line.startswith("#"):
            level = min(len(line) - len(line.lstrip("#")), 3)
            story.append(Paragraph(_inline(line[level:].strip()), styles[level]))
        elif line.startswith(("- ", "* ")):
            story.append(Paragraph("• " + _inline(line[2:]), bullet))
        elif re.match(r"^\d+[.)]\s", line):
            story.append(Paragraph(_inline(line), bullet))
        elif line.startswith("|"):
            if re.fullmatch(r"[|\s:-]+", line):
                story.append(Spacer(1, 2))
            else:
                cells = [cell.strip() for cell in line.strip("|").split("|")]
                story.append(Paragraph("&nbsp;&nbsp;|&nbsp;&nbsp;".join(_inline(cell) for cell in cells), normal))
        else:
            story.append(Paragraph(_inline(line), normal))

    output = BytesIO()
    document = SimpleDocTemplate(output, pagesize=A4, title=title, author="Sponsorship Activation",
                                 leftMargin=48, rightMargin=48, topMargin=58, bottomMargin=46)

    def page_marks(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#173e35"))
        canvas.setFont("SponsorSans", 8)
        canvas.drawString(48, A4[1] - 34, "SPONSORSHIP  /  ИССЛЕДОВАТЕЛЬСКИЙ ОТЧЁТ")
        canvas.setStrokeColor(colors.HexColor("#d8e0d8"))
        canvas.line(48, A4[1] - 42, A4[0] - 48, A4[1] - 42)
        canvas.setFillColor(colors.HexColor("#69756f"))
        canvas.drawRightString(A4[0] - 48, 27, f"{doc.page}")
        canvas.restoreState()

    if not story:
        story.append(Paragraph("Отчёт пуст.", normal))
    document.build(story, onFirstPage=page_marks, onLaterPages=page_marks)
    return output.getvalue()
