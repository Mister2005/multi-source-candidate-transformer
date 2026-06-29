import pytest
from transformer.normalizers.phone import normalize_phone, normalize_phones
from transformer.normalizers.email import normalize_email, normalize_emails, extract_emails_from_text
from transformer.normalizers.date import normalize_date
from transformer.normalizers.skill import canonicalize_skill, canonicalize_skills
from transformer.normalizers.location import normalize_location


class TestPhone:
    def test_e164_passthrough(self):
        assert normalize_phone("+14155550123") == "+14155550123"

    def test_us_format(self):
        assert normalize_phone("(415) 555-0123") == "+14155550123"

    def test_dashes(self):
        assert normalize_phone("415-555-0123") == "+14155550123"

    def test_dots(self):
        assert normalize_phone("415.555.0123") == "+14155550123"

    def test_invalid_returns_none(self):
        assert normalize_phone("not-a-phone") is None

    def test_empty_returns_none(self):
        assert normalize_phone("") is None

    def test_dedup(self):
        result = normalize_phones(["(415) 555-0123", "+14155550123", "415-555-0123"])
        assert result == ["+14155550123"]


class TestEmail:
    def test_lowercase(self):
        assert normalize_email("Alex.JOHNSON@Example.COM") == "alex.johnson@example.com"

    def test_invalid_returns_none(self):
        assert normalize_email("not-an-email") is None

    def test_empty_returns_none(self):
        assert normalize_email("") is None

    def test_dedup(self):
        result = normalize_emails(["Alex@example.com", "alex@example.com"])
        assert result == ["alex@example.com"]

    def test_extract_from_text(self):
        text = "Contact me at alex.johnson@example.com or at work: work@techcorp.io"
        emails = extract_emails_from_text(text)
        assert "alex.johnson@example.com" in emails
        assert "work@techcorp.io" in emails


class TestDate:
    def test_yyyy_mm(self):
        assert normalize_date("2021-03") == "2021-03"

    def test_month_year(self):
        assert normalize_date("March 2021") == "2021-03"

    def test_abbreviated_month(self):
        assert normalize_date("Mar 2021") == "2021-03"

    def test_slash_format(self):
        assert normalize_date("03/2021") == "2021-03"

    def test_year_only(self):
        assert normalize_date("2019") == "2019-01"

    def test_present_returns_none(self):
        assert normalize_date("Present") is None
        assert normalize_date("current") is None

    def test_empty_returns_none(self):
        assert normalize_date("") is None


class TestSkill:
    def test_python_variants(self):
        assert canonicalize_skill("python") == "Python"
        assert canonicalize_skill("py") == "Python"
        assert canonicalize_skill("Python3") == "Python"

    def test_js_variants(self):
        assert canonicalize_skill("js") == "JavaScript"
        assert canonicalize_skill("javascript") == "JavaScript"

    def test_unknown_skill_title_cased(self):
        result = canonicalize_skill("some rare tool")
        assert result  # not empty

    def test_dedup_in_list(self):
        result = canonicalize_skills(["python", "Python", "py"])
        assert result.count("Python") == 1


class TestLocation:
    def test_full_location(self):
        loc = normalize_location("San Francisco, CA, USA")
        assert loc["city"] == "San Francisco"
        assert loc["country"] == "US"

    def test_two_part(self):
        loc = normalize_location("London, UK")
        assert loc["city"] == "London"
        assert loc["country"] == "GB"

    def test_none_input(self):
        assert normalize_location(None) is None

    def test_empty_input(self):
        assert normalize_location("") is None
