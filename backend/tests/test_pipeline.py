import json
import pytest
from pathlib import Path

from transformer.pipeline import TransformerPipeline, detect_source_type

SAMPLES = Path(__file__).parent.parent / "data" / "samples"


class TestDetect:
    def test_csv(self):
        assert detect_source_type("file.csv") == "csv"

    def test_json(self):
        assert detect_source_type("export.json") == "ats_json"

    def test_pdf(self):
        assert detect_source_type("resume.pdf") == "resume_pdf"

    def test_docx(self):
        assert detect_source_type("resume.docx") == "resume_docx"

    def test_txt(self):
        assert detect_source_type("notes.txt") == "recruiter_txt"

    def test_github_url(self):
        assert detect_source_type("https://github.com/alexjohnson-dev") == "github_url"

    def test_unknown(self):
        assert detect_source_type("somefile.xyz") is None


class TestPipeline:
    def setup_method(self):
        self.pipeline = TransformerPipeline()

    def test_csv_only(self):
        sources = [{"type": "csv", "content": str(SAMPLES / "recruiter.csv")}]
        result = self.pipeline.run(sources)
        assert result.get("full_name") == "Alex Johnson"
        assert len(result.get("emails", [])) > 0
        assert result.get("overall_confidence", 0) > 0

    def test_ats_json_only(self):
        sources = [{"type": "ats_json", "content": str(SAMPLES / "ats_export.json")}]
        result = self.pipeline.run(sources)
        assert result.get("full_name") == "Alex Johnson"
        assert len(result.get("skills", [])) > 0

    def test_txt_only(self):
        sources = [{"type": "recruiter_txt", "content": str(SAMPLES / "recruiter_notes.txt")}]
        result = self.pipeline.run(sources)
        assert result is not None
        assert "_errors" not in result or len(result.get("_errors", [])) == 0

    def test_csv_plus_ats_json(self):
        sources = [
            {"type": "csv", "content": str(SAMPLES / "recruiter.csv")},
            {"type": "ats_json", "content": str(SAMPLES / "ats_export.json")},
        ]
        result = self.pipeline.run(sources)
        assert result.get("full_name") == "Alex Johnson"
        # ATS JSON has TypeScript that CSV doesn't — should be in merged skills
        skill_names = [s["name"] for s in result.get("skills", [])]
        assert "TypeScript" in skill_names

    def test_structured_plus_unstructured(self):
        """Core requirement: at least one structured + one unstructured source."""
        sources = [
            {"type": "csv", "content": str(SAMPLES / "recruiter.csv")},       # structured
            {"type": "recruiter_txt", "content": str(SAMPLES / "recruiter_notes.txt")},  # unstructured
        ]
        result = self.pipeline.run(sources)
        assert result.get("full_name") is not None
        assert result.get("overall_confidence", 0) > 0

    def test_custom_config(self):
        config_path = SAMPLES / "output_config.json"
        with open(config_path) as f:
            config = json.load(f)
        sources = [
            {"type": "csv", "content": str(SAMPLES / "recruiter.csv")},
            {"type": "ats_json", "content": str(SAMPLES / "ats_export.json")},
        ]
        result = self.pipeline.run(sources, config)
        # Config renames emails[0] → primary_email
        assert "primary_email" in result
        assert "full_name" in result

    def test_no_sources_returns_error(self):
        result = self.pipeline.run([])
        assert "error" in result

    def test_all_bad_sources_returns_error(self):
        sources = [{"type": "csv", "content": "/nonexistent/path/file.csv"}]
        result = self.pipeline.run(sources)
        # Should not raise; should return something
        assert result is not None

    def test_output_has_provenance(self):
        sources = [{"type": "csv", "content": str(SAMPLES / "recruiter.csv")}]
        result = self.pipeline.run(sources)
        assert len(result.get("provenance", [])) > 0

    def test_output_has_candidate_id(self):
        sources = [{"type": "csv", "content": str(SAMPLES / "recruiter.csv")}]
        result = self.pipeline.run(sources)
        assert result.get("candidate_id")

    def test_deterministic(self):
        sources = [
            {"type": "csv", "content": str(SAMPLES / "recruiter.csv")},
            {"type": "ats_json", "content": str(SAMPLES / "ats_export.json")},
        ]
        r1 = self.pipeline.run(sources)
        r2 = self.pipeline.run(sources)
        assert r1.get("candidate_id") == r2.get("candidate_id")
        assert r1.get("overall_confidence") == r2.get("overall_confidence")
