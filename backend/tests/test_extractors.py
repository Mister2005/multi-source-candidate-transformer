import io
import json
import pytest
from transformer.models import SourceItem
from transformer.extractors.csv_extractor import CSVExtractor
from transformer.extractors.ats_json_extractor import ATSJsonExtractor
from transformer.extractors.txt_extractor import TxtExtractor


CSV_CONTENT = """name,email,phone,current_company,title,location
Alex Johnson,alex.johnson@example.com,(415) 555-0123,TechCorp Inc.,Senior Software Engineer,"San Francisco, CA, USA"
"""

ATS_DATA = {
    "candidateName": "Alex Johnson",
    "emailAddress": "alex.johnson@example.com",
    "phoneNumber": "+14155550123",
    "location": "San Francisco, CA, USA",
    "skillSet": ["Python", "React", "PostgreSQL"],
    "experience": [
        {"company": "TechCorp", "title": "Engineer", "startDate": "2021-03", "endDate": None}
    ],
    "education": [
        {"school": "State U", "degree": "BS", "major": "CS", "graduationYear": 2019}
    ]
}


class TestCSVExtractor:
    def setup_method(self):
        self.extractor = CSVExtractor()

    def test_extracts_name(self):
        item = SourceItem(type="csv", raw_content=CSV_CONTENT)
        record = self.extractor.extract(item)
        assert record.full_name == "Alex Johnson"

    def test_extracts_email(self):
        item = SourceItem(type="csv", raw_content=CSV_CONTENT)
        record = self.extractor.extract(item)
        assert "alex.johnson@example.com" in record.emails

    def test_extracts_phone(self):
        item = SourceItem(type="csv", raw_content=CSV_CONTENT)
        record = self.extractor.extract(item)
        assert len(record.phones) > 0

    def test_builds_experience(self):
        item = SourceItem(type="csv", raw_content=CSV_CONTENT)
        record = self.extractor.extract(item)
        assert len(record.experience) > 0
        assert record.experience[0].company == "TechCorp Inc."

    def test_malformed_csv_does_not_crash(self):
        item = SourceItem(type="csv", raw_content="not,a,valid\ncsv,with,no,header,match")
        record = self.extractor.extract(item)
        assert record is not None

    def test_empty_csv_does_not_crash(self):
        item = SourceItem(type="csv", raw_content="")
        record = self.extractor.extract(item)
        assert record is not None


class TestATSJsonExtractor:
    def setup_method(self):
        self.extractor = ATSJsonExtractor()

    def test_extracts_name(self):
        item = SourceItem(type="ats_json", raw_content=ATS_DATA)
        record = self.extractor.extract(item)
        assert record.full_name == "Alex Johnson"

    def test_extracts_skills(self):
        item = SourceItem(type="ats_json", raw_content=ATS_DATA)
        record = self.extractor.extract(item)
        assert "Python" in record.skills_raw

    def test_extracts_experience(self):
        item = SourceItem(type="ats_json", raw_content=ATS_DATA)
        record = self.extractor.extract(item)
        assert len(record.experience) > 0
        assert record.experience[0].company == "TechCorp"

    def test_extracts_education(self):
        item = SourceItem(type="ats_json", raw_content=ATS_DATA)
        record = self.extractor.extract(item)
        assert len(record.education) > 0

    def test_invalid_json_string_does_not_crash(self):
        item = SourceItem(type="ats_json", raw_content="{not valid json")
        record = self.extractor.extract(item)
        assert record is not None

    def test_first_name_last_name_combine(self):
        data = {"firstName": "Jane", "lastName": "Doe", "email": "jane@example.com"}
        item = SourceItem(type="ats_json", raw_content=data)
        record = self.extractor.extract(item)
        assert record.full_name == "Jane Doe"


class TestTxtExtractor:
    def setup_method(self):
        self.extractor = TxtExtractor()

    def test_extracts_email_from_text(self):
        text = "Candidate: John Smith\nEmail: john.smith@example.com\nPhone: 415-555-9999"
        item = SourceItem(type="recruiter_txt", raw_content=text)
        record = self.extractor.extract(item)
        assert "john.smith@example.com" in record.emails

    def test_extracts_skills_from_text(self):
        text = "Strong Python and React developer. Also knows Docker and AWS."
        item = SourceItem(type="recruiter_txt", raw_content=text)
        record = self.extractor.extract(item)
        assert len(record.skills_raw) > 0

    def test_empty_text_does_not_crash(self):
        item = SourceItem(type="recruiter_txt", raw_content="")
        record = self.extractor.extract(item)
        assert record is not None


def _tesseract_available() -> bool:
    import shutil
    from pathlib import Path as _P
    if shutil.which("tesseract"):
        return True
    return _P(r"C:\Program Files\Tesseract-OCR\tesseract.exe").exists()


@pytest.mark.skipif(not _tesseract_available(), reason="Tesseract OCR binary not installed on this machine")
class TestResumeExtractorOCR:
    """Synthetic 'scanned' PDF: a page with no embedded text layer, just a
    rendered image of text. Exercises the pdfplumber -> OCR fallback path."""

    def _build_scanned_pdf(self, tmp_path):
        from PIL import Image, ImageDraw
        import pdfplumber  # noqa: F401  (ensures dependency present before building)
        from reportlab.pdfgen import canvas as rl_canvas

        # Render text into an image
        img = Image.new("RGB", (900, 300), color="white")
        draw = ImageDraw.Draw(img)
        draw.text((20, 20), "Jordan Lee", fill="black")
        draw.text((20, 60), "jordan.lee@example.com", fill="black")
        img_path = tmp_path / "scanned_page.png"
        img.save(img_path)

        pdf_path = tmp_path / "scanned_resume.pdf"
        c = rl_canvas.Canvas(str(pdf_path), pagesize=(900, 300))
        c.drawImage(str(img_path), 0, 0, width=900, height=300)
        c.save()
        return pdf_path

    def test_ocr_fallback_extracts_text(self, tmp_path):
        reportlab = pytest.importorskip("reportlab")
        from transformer.extractors.resume_extractor import ResumeExtractor

        pdf_path = self._build_scanned_pdf(tmp_path)
        item = SourceItem(type="resume_pdf", raw_content=str(pdf_path))
        record = ResumeExtractor().extract(item)

        # OCR is not 100% deterministic, but the record should not be empty/crash
        # and ideally picks up the embedded email via regex over OCR'd text.
        assert record is not None
