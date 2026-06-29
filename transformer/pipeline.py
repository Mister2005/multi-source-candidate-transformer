import logging
from pathlib import Path
from typing import Any

from transformer.models import SourceItem, RawRecord, CanonicalRecord
from transformer.extractors.csv_extractor import CSVExtractor
from transformer.extractors.ats_json_extractor import ATSJsonExtractor
from transformer.extractors.github_extractor import GitHubExtractor
from transformer.extractors.resume_extractor import ResumeExtractor
from transformer.extractors.txt_extractor import TxtExtractor
from transformer import merger, confidence, projector, validator

logger = logging.getLogger(__name__)

EXTRACTORS = {
    "csv": CSVExtractor(),
    "ats_json": ATSJsonExtractor(),
    "github_url": GitHubExtractor(),
    "resume_pdf": ResumeExtractor(),
    "resume_docx": ResumeExtractor(),
    "recruiter_txt": TxtExtractor(),
}


def detect_source_type(path_or_url: str) -> str | None:
    """Detect source type from file extension or URL pattern."""
    s = str(path_or_url).strip()
    if s.startswith("https://github.com") or s.startswith("http://github.com"):
        return "github_url"
    if s.startswith("https://linkedin.com") or "linkedin.com/in/" in s:
        return "linkedin_url"  # not yet implemented, but detected
    ext = Path(s).suffix.lower()
    return {
        ".csv": "csv",
        ".json": "ats_json",
        ".pdf": "resume_pdf",
        ".docx": "resume_docx",
        ".doc": "resume_docx",
        ".txt": "recruiter_txt",
    }.get(ext)


class TransformerPipeline:
    def __init__(self, ats_field_map: dict | None = None):
        if ats_field_map:
            EXTRACTORS["ats_json"] = ATSJsonExtractor(field_map=ats_field_map)

    def run(
        self,
        sources: list[dict[str, Any]],  # [{"type": ..., "content": ...}]
        config: dict | None = None,
    ) -> dict:
        """
        Run the full pipeline.

        sources: list of dicts with keys:
            - "type": source type string (optional — auto-detected if omitted)
            - "content": file path, URL, or raw content

        config: output projection config (optional — full canonical output if omitted)

        Returns: projected + validated output dict
        """
        warnings: list[str] = []
        errors: list[str] = []

        # --- Stage 1: Detect + build SourceItems ---
        source_items: list[SourceItem] = []
        for s in sources:
            content = s.get("content", "")
            src_type = s.get("type") or detect_source_type(str(content))
            if not src_type:
                logger.warning("Could not detect source type for: %s", str(content)[:60])
                warnings.append(f"Unknown source type: {str(content)[:60]}")
                continue
            if src_type == "linkedin_url":
                logger.info("LinkedIn URL detected — skipping (descoped: requires OAuth/scraping)")
                warnings.append(
                    "LinkedIn source skipped — descoped in v1 (requires authenticated scraping "
                    "or OAuth; violates LinkedIn ToS without it). URL preserved in links if found in other sources."
                )
                continue
            source_items.append(SourceItem(type=src_type, raw_content=content))

        if not source_items:
            logger.error("No usable sources provided")
            return {"error": "No usable sources", "warnings": warnings}

        # --- Stage 2: Extract ---
        raw_records: list[RawRecord] = []
        for item in source_items:
            extractor = EXTRACTORS.get(item.type)
            if not extractor:
                logger.warning("No extractor for type: %s", item.type)
                warnings.append(f"No extractor for type: {item.type}")
                continue
            logger.info("Extracting from source: %s", item.type)
            try:
                record = extractor.extract(item)
                raw_records.append(record)
                logger.info("  → extracted record from %s", item.type)
            except Exception as e:
                logger.error("Extractor %s failed: %s", item.type, e)
                errors.append(f"Extractor {item.type} failed: {e}")

        if not raw_records:
            return {"error": "All extractors failed", "errors": errors, "warnings": warnings}

        # --- Stages 3+4: Normalize + Merge (merger handles normalization internally) ---
        logger.info("Merging %d source records...", len(raw_records))
        canonical: CanonicalRecord = merger.merge(raw_records)

        # --- Stage 5: Confidence scoring ---
        logger.info("Scoring confidence...")
        canonical = confidence.score(canonical)
        logger.info("  → overall_confidence: %.3f", canonical.overall_confidence)

        # --- Stage 6: Project ---
        logger.info("Projecting output...")
        output, proj_errors = projector.project(canonical, config or {})
        if proj_errors:
            errors.extend(proj_errors)

        # --- Stage 7: Validate ---
        logger.info("Validating output...")
        ok, val_errors = validator.validate(output, config)
        if not ok:
            for e in val_errors:
                logger.error("Validation: %s", e)
            errors.extend(val_errors)

        if warnings:
            output["_warnings"] = warnings
        if errors:
            output["_errors"] = errors

        return output
