import logging
import re
from pathlib import Path

from transformer.extractors.base import BaseExtractor
from transformer.models import SourceItem, RawRecord, ExperienceEntry, EducationEntry
from transformer.normalizers.email import extract_emails_from_text
from transformer.normalizers.date import normalize_date, MONTH_MAP
from transformer.normalizers.phone import normalize_phone

logger = logging.getLogger(__name__)

PHONE_RE = re.compile(r"[\+\(]?[\d\s\-\(\)\.]{7,20}\d")
URL_RE = re.compile(r"https?://[^\s]+|www\.[^\s]+", re.IGNORECASE)
LINKEDIN_RE = re.compile(r"linkedin\.com/in/([\w\-]+)", re.IGNORECASE)
GITHUB_RE = re.compile(r"github\.com/([\w\-]+)(?:/[\w\-]*)?", re.IGNORECASE)

# A bare local-format phone number (no leading "+") is ambiguous — phonenumbers
# needs a default region to parse it against. Resumes rarely state a dialing
# code explicitly, but the country is often inferable from an address/location
# line elsewhere in the document. This is a coarse heuristic covering common
# cases, not a full geocoder.
_COUNTRY_PHONE_REGION_HINTS = {
    "india": "IN", "mumbai": "IN", "delhi": "IN", "bangalore": "IN", "bengaluru": "IN",
    "united states": "US", "usa": "US",
    "united kingdom": "GB", "uk": "GB", "london": "GB",
    "canada": "CA",
    "australia": "AU",
}


def _guess_phone_region(text: str) -> str:
    """Best-effort default region for parsing a phone number with no country code."""
    text_lower = text.lower()
    for hint, region in _COUNTRY_PHONE_REGION_HINTS.items():
        if hint in text_lower:
            return region
    return "US"

# Simple heuristic: lines containing these words likely are section headers
SECTION_HEADERS = {
    "experience": ["experience", "work history", "employment", "career"],
    "education": ["education", "academic", "qualification", "university", "college"],
    "skills": ["skills", "technologies", "tools", "expertise", "competencies", "technical"],
}


_TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def _ocr_page(page) -> str:
    """OCR a scanned (text-less) PDF page via its rendered image."""
    try:
        import pytesseract
        if Path(_TESSERACT_PATH).exists():
            pytesseract.pytesseract.tesseract_cmd = _TESSERACT_PATH
        image = page.to_image(resolution=300).original
        return pytesseract.image_to_string(image) or ""
    except Exception as e:
        logger.warning("OCR fallback failed for page: %s", e)
        return ""


def _extract_text_pdf(path: str) -> str:
    try:
        import pdfplumber
        pages = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                # x_tolerance=1 avoids word-fusion ("VedantInternationalSchool")
                # on PDFs exported with fonts that omit real space glyphs and
                # rely on character positioning alone.
                text = page.extract_text(x_tolerance=1, x_tolerance_ratio=None)
                if not text or len(text.strip()) < 10:
                    # Likely a scanned/image-only page — fall back to OCR
                    ocr_text = _ocr_page(page)
                    if ocr_text.strip():
                        pages.append(ocr_text)
                        continue
                if text:
                    pages.append(text)
        return "\n".join(pages)
    except Exception as e:
        logger.error("PDF extraction failed: %s", e)
        return ""


def _extract_text_docx(path: str) -> str:
    try:
        from docx import Document
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception as e:
        logger.error("DOCX extraction failed: %s", e)
        return ""


def _is_section_header(line: str, keywords: list[str]) -> bool:
    ll = line.strip().lower()
    return any(kw in ll for kw in keywords) and len(line.strip()) < 60


def _parse_experience_blocks(lines: list[str]) -> list[ExperienceEntry]:
    entries = []
    in_section = False
    current: dict = {}

    for line in lines:
        line = line.strip()
        if not line:
            if current:
                entries.append(ExperienceEntry(**{k: v for k, v in current.items() if k in ExperienceEntry.model_fields}))
                current = {}
            continue

        # Only treat as the section-opening header when not already inside
        # the section (see same fix in _parse_education_blocks) — otherwise
        # a company/role line containing a keyword like "career" gets
        # misread as a fresh header and silently dropped.
        if not in_section and _is_section_header(line, SECTION_HEADERS["experience"]):
            in_section = True
            if current:
                entries.append(ExperienceEntry(**{k: v for k, v in current.items() if k in ExperienceEntry.model_fields}))
                current = {}
            continue

        if in_section and _is_section_header(line, SECTION_HEADERS["education"] + SECTION_HEADERS["skills"]):
            in_section = False
            if current:
                entries.append(ExperienceEntry(**{k: v for k, v in current.items() if k in ExperienceEntry.model_fields}))
                current = {}
            continue

        if not in_section:
            continue

        # Try to extract date range on the line
        date_range = re.search(
            r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*\d{4}|\d{4})"
            r"\s*[–\-—to]+\s*"
            r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s*\d{4}|\d{4}|[Pp]resent|[Cc]urrent)",
            line,
        )
        if date_range:
            # A date-range line marks the start of a new role. If the
            # current entry already has dates, it's a completed prior
            # entry sitting in `current` with no blank line to flush it
            # (a common resume layout) — flush it now before starting the
            # new one, instead of silently overwriting its dates.
            if current.get("start") is not None:
                entries.append(ExperienceEntry(**{k: v for k, v in current.items() if k in ExperienceEntry.model_fields}))
                current = {}

            current["start"] = normalize_date(date_range.group(1))
            end_raw = date_range.group(2)
            current["end"] = None if end_raw.lower() in ("present", "current") else normalize_date(end_raw)

            # Capture any title text on the same line, before the date
            # (e.g. "Python Developer Intern March 2026 - Present").
            title_part = line[: date_range.start()].strip(" -|–—")
            if title_part:
                current["title"] = title_part
        elif not current.get("company"):
            # Assume first non-date line is company/title
            if "|" in line:
                parts = line.split("|")
                current["title"] = parts[0].strip()
                current["company"] = parts[1].strip() if len(parts) > 1 else None
            elif "at " in line.lower():
                m = re.match(r"(.+?)\s+at\s+(.+)", line, re.IGNORECASE)
                if m:
                    current["title"] = m.group(1).strip()
                    current["company"] = m.group(2).strip()
            elif "," in line:
                parts = line.split(",", 1)
                current["title"] = parts[0].strip()
                current["company"] = parts[1].strip()
            else:
                current["company"] = line
        else:
            # Bullet/description text under an already-identified role —
            # fold it into the summary instead of discarding it.
            snippet = line.lstrip("•-* ").strip()
            if snippet:
                current["summary"] = (current.get("summary", "") + " " + snippet).strip()

    if current:
        entries.append(ExperienceEntry(**{k: v for k, v in current.items() if k in ExperienceEntry.model_fields}))

    return entries


def _parse_education_blocks(lines: list[str]) -> list[EducationEntry]:
    entries = []
    in_section = False
    current: dict = {}
    # Resumes overwhelmingly list education as alternating pairs of lines:
    # an institution line, then a degree/detail line (degree, GPA, dates —
    # or for a pre-university entry, a board/grade line with no degree
    # keyword at all, e.g. "CBSE Class XII: 86.8% ... 2021 - 2023"). Track
    # which half of that pair we expect next instead of relying on blank
    # lines or a degree-keyword match to decide where one entry ends and
    # the next begins — those signals don't reliably appear between
    # consecutive entries with no separating blank line.
    expecting_detail = False

    DEGREE_KEYWORDS = ["bachelor", "master", "phd", "b.s", "m.s", "b.e", "m.e", "b.tech", "m.tech", "mba", "b.a", "m.a", "associate"]

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Only treat a line as the section-opening header when we are not
        # already inside the section — otherwise an institution name that
        # happens to contain a keyword (e.g. "...College of Engineering...")
        # gets misread as a fresh header and silently dropped.
        if not in_section and _is_section_header(line, SECTION_HEADERS["education"]):
            in_section = True
            if current:
                entries.append(EducationEntry(**{k: v for k, v in current.items() if k in EducationEntry.model_fields}))
                current = {}
                expecting_detail = False
            continue

        if in_section and _is_section_header(line, SECTION_HEADERS["experience"] + SECTION_HEADERS["skills"]):
            in_section = False
            if current:
                entries.append(EducationEntry(**{k: v for k, v in current.items() if k in EducationEntry.model_fields}))
                current = {}
                expecting_detail = False
            continue

        if not in_section:
            continue

        ll = line.lower()
        # Word-boundary match — a plain substring check misclassifies lines
        # like "...Mumbai, India" as a degree line because "mba" (the MBA
        # keyword) is a substring of "Mumbai".
        has_degree = any(re.search(r"\b" + re.escape(kw) + r"\b", ll) for kw in DEGREE_KEYWORDS)

        if not expecting_detail:
            # Start of a new entry — flush whatever completed entry is
            # currently buffered first.
            if current:
                entries.append(EducationEntry(**{k: v for k, v in current.items() if k in EducationEntry.model_fields}))
                current = {}
            current["institution"] = line.split(",")[0].strip()
            expecting_detail = True
            continue

        # This is the detail line for the institution captured above —
        # degree text if it has a degree keyword, otherwise still treated
        # as the descriptive detail (e.g. a high-school board/grade line).
        current["degree"] = line.split(",")[0].strip()
        if has_degree and "," in line:
            current["field"] = line.split(",", 1)[1].strip()

        # The graduation/end year is whichever 4-digit year appears LAST
        # on the line — "Aug 2023 - June 2027" and "2021 - 2023" both end
        # with the correct end year, whereas taking the FIRST match (the
        # previous behavior) grabbed the start year instead.
        years = re.findall(r"\b((?:19|20)\d{2})\b", line)
        if years:
            current["end_year"] = int(years[-1])

        expecting_detail = False

    if current:
        entries.append(EducationEntry(**{k: v for k, v in current.items() if k in EducationEntry.model_fields}))

    return entries


def _extract_skills_from_text(text: str) -> list[str]:
    """Load skill keywords from data/skill_synonyms.json and match against text."""
    from transformer.normalizers.skill import _get_synonyms
    synonyms = _get_synonyms()
    found = []
    text_lower = text.lower()
    for keyword in synonyms:
        pattern = r'\b' + re.escape(keyword) + r'\b'
        if re.search(pattern, text_lower):
            found.append(synonyms[keyword])
    # Deduplicate
    seen = set()
    result = []
    for s in found:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result


def _extract_name_heuristic(lines: list[str]) -> str | None:
    """Try spaCy first; fall back to first non-empty line heuristic."""
    try:
        import spacy
        nlp = spacy.load("en_core_web_sm")
        # Try first 500 chars
        snippet = " ".join(lines[:10])[:500]
        doc = nlp(snippet)
        for ent in doc.ents:
            if ent.label_ == "PERSON" and len(ent.text.split()) >= 2:
                return ent.text
    except Exception:
        pass

    # Fallback: first short line that looks like a name (2-4 title-cased words)
    for line in lines[:5]:
        line = line.strip()
        words = line.split()
        if 2 <= len(words) <= 4 and all(w[0].isupper() for w in words if w):
            # Not an obvious section header or company name
            if not any(kw in line.lower() for kw in ["experience", "education", "skills", "resume", "curriculum"]):
                return line
    return None


class ResumeExtractor(BaseExtractor):
    def extract(self, source: SourceItem) -> RawRecord:
        src_type = source.type  # resume_pdf or resume_docx
        record = RawRecord(source_type=src_type)
        path = str(source.raw_content)

        if src_type == "resume_pdf":
            text = _extract_text_pdf(path)
        else:
            text = _extract_text_docx(path)

        if not text.strip():
            logger.warning("Resume: no text extracted from %s", Path(path).name)
            return record

        lines = text.split("\n")

        # Name
        record.full_name = _extract_name_heuristic(lines)

        # Emails
        record.emails = extract_emails_from_text(text)

        # Phones — pre-normalize to E.164 here using a region guessed from the
        # resume's own text, since a bare local number (no "+") is otherwise
        # parsed against the merger's hardcoded US default and silently
        # mis-tagged with the wrong country code for non-US candidates.
        phone_candidates = PHONE_RE.findall(text)
        region = _guess_phone_region(text)
        normalized_phones = []
        for p in phone_candidates:
            p = p.strip()
            if len(p) < 7:
                continue
            normalized = normalize_phone(p, default_region=region)
            normalized_phones.append(normalized if normalized else p)
        record.phones = normalized_phones[:5]

        # URLs
        for m in LINKEDIN_RE.finditer(text):
            record.linkedin_url = f"https://linkedin.com/in/{m.group(1)}"
            break
        for m in GITHUB_RE.finditer(text):
            uname = m.group(1)
            if uname.lower() not in ("com", "orgs", "topics", "trending"):
                record.github_url = f"https://github.com/{uname}"
                break
        for url_m in URL_RE.finditer(text):
            url = url_m.group(0)
            if "linkedin" not in url and "github" not in url:
                record.portfolio_url = url
                break

        # Skills
        record.skills_raw = _extract_skills_from_text(text)

        # Experience
        record.experience = _parse_experience_blocks(lines)

        # Education
        record.education = _parse_education_blocks(lines)

        # Years of experience heuristic from date ranges
        total_months = 0
        for exp in record.experience:
            if exp.start:
                try:
                    sy, sm = map(int, exp.start.split("-"))
                    if exp.end:
                        ey, em = map(int, exp.end.split("-"))
                    else:
                        from datetime import date
                        today = date.today()
                        ey, em = today.year, today.month
                    total_months += (ey - sy) * 12 + (em - sm)
                except Exception:
                    pass
        if total_months > 0:
            record.years_experience = round(total_months / 12, 1)

        return record
