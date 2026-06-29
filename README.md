# Multi-Source Candidate Data Transformer
**Eightfold Engineering Intern Assignment — Varun Gupta**

Transforms messy, multi-source candidate data into one clean canonical profile with provenance tracking and confidence scoring.

---

## Setup

```bash
# 1. Create and activate virtual environment
python -m venv venv
venv\Scripts\activate       # Windows
# source venv/bin/activate  # Mac/Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Download spaCy model (for resume/notes NLP)
python -m spacy download en_core_web_sm

# 4. (Optional) GitHub token for higher API rate limits
copy .env.example .env
# Edit .env and add your GITHUB_TOKEN
```

---

## Run

### Quick start with sample data

```bash
# Default canonical schema output
python cli.py --csv data/samples/recruiter.csv --ats-json data/samples/ats_export.json --notes data/samples/recruiter_notes.txt --output output/canonical.json

# With custom output config (field renaming, selection)
python cli.py --csv data/samples/recruiter.csv --ats-json data/samples/ats_export.json --config data/samples/output_config.json --output output/custom.json
```

### With a GitHub profile

```bash
python cli.py --csv data/samples/recruiter.csv --github https://github.com/<username> --output output/with_github.json
```

### With a resume PDF

```bash
python cli.py --resume path/to/resume.pdf --output output/from_resume.json
```

### Full run (all sources)

```bash
python cli.py \
  --csv data/samples/recruiter.csv \
  --ats-json data/samples/ats_export.json \
  --resume path/to/resume.pdf \
  --notes data/samples/recruiter_notes.txt \
  --github https://github.com/<username> \
  --config data/samples/output_config.json \
  --output output/full.json
```

---

## Run Tests

```bash
pytest tests/ -v
```

---

## Pipeline Architecture

```
Inputs → Detect → Extract → Normalize → Merge → Confidence → Project → Validate → Output
```

**Stage 1 — Detect:** Identifies each input's source type (csv, ats_json, github_url, resume_pdf, resume_docx, recruiter_txt) from file extension or URL pattern.

**Stage 2 — Extract:** Per-source extractors pull raw field bags. Structured sources (CSV, ATS JSON) use direct column/field mapping. Unstructured sources (resume, notes) use spaCy NER + regex. GitHub uses the public REST API.

**Stage 3 — Normalize (inside Merge):** Phones → E.164, emails → lowercase, dates → YYYY-MM, skills → canonical names via synonym map, location → ISO-3166 country code.

**Stage 4 — Merge:** Priority-based conflict resolution (ats_json > csv > github > resume > txt). Scalar fields: highest-priority source wins. Array fields (emails, phones, skills): union + dedup. All sources recorded in provenance.

**Stage 5 — Confidence:** Per-field confidence based on source type and extraction method. Multi-source agreement = bonus. overall_confidence = weighted mean across fields.

**Stage 6 — Project:** Runtime output config reshapes the canonical record — select fields, rename paths, apply normalization overrides, handle missing values (null/omit/error).

**Stage 7 — Validate:** jsonschema validates output against the requested schema before returning.

---

## Output Config

The `--config` flag accepts a JSON file that controls output shape without code changes:

```json
{
  "fields": [
    { "path": "full_name", "type": "string", "required": true },
    { "path": "primary_email", "from": "emails[0]", "type": "string", "required": true },
    { "path": "phone", "from": "phones[0]", "type": "string", "normalize": "E164" },
    { "path": "top_skills", "from": "skills[].name", "type": "string[]" }
  ],
  "include_confidence": true,
  "on_missing": "null"
}
```

- `path`: output key name
- `from`: source path in canonical record (dot-notation + `[0]` / `[].field` array access)
- `normalize`: `E164`, `canonical`, or `lowercase`
- `on_missing`: `null` (default), `omit`, or `error`
- `include_confidence`: include `_confidence` and `_provenance` in output

---

## Supported Sources

| Source | Flag | Type |
|---|---|---|
| Recruiter CSV | `--csv` | Structured |
| ATS JSON export | `--ats-json` | Structured |
| GitHub profile URL | `--github` | Unstructured |
| Resume (PDF) | `--resume file.pdf` | Unstructured |
| Resume (DOCX) | `--resume file.docx` | Unstructured |
| Recruiter notes (.txt) | `--notes` | Unstructured |

---

## Edge Cases Handled

| Scenario | Behavior |
|---|---|
| Source file not found | Logged + skipped; pipeline continues |
| GitHub 404 or rate limit | Skipped gracefully with warning |
| Phone not normalizable | Stored as null; logged |
| Same candidate in multiple sources with different name spellings | Highest-priority source wins; all recorded in provenance |
| ATS JSON with non-standard field names | Mapped via configurable field map |
| All sources empty | Returns empty canonical record, confidence = 0 |
| Conflicting emails | Unioned; all kept |

---

## Assumptions

- One candidate per CLI run (single-candidate pipeline by design; see Descoped for batch notes)
- spaCy NER for name extraction from resumes has best-effort accuracy; structured sources are more reliable
- GitHub token is optional; without it, unauthenticated rate limit applies (60 req/hr)
- Resume PDF must be text-based (not scanned images); scanned PDFs return empty text

## Descoped

### LinkedIn profile scraping
Detected and gracefully skipped with an explanatory warning. Scraping LinkedIn without authentication violates their ToS, and their official API requires approval. The LinkedIn URL is preserved in `links.linkedin` if it appears in any other source (CSV, ATS JSON, notes). Full implementation would require an approved OAuth integration.

### Batch / multi-candidate mode
The pipeline processes **one candidate per CLI invocation** by design — this keeps provenance and confidence reasoning clean and per-candidate. The underlying engine runs at ~3ms/candidate, so a thin batch wrapper (iterate a folder, call `pipeline.run()` per candidate) is straightforward to add. Descoped here to keep the CLI surface focused.

### OCR for scanned PDF resumes
`pdfplumber` extracts text from text-based PDFs only. Scanned image PDFs return empty text; the pipeline degrades gracefully (skips the source, continues with others). OCR via Tesseract would be the next step.

### Persistent storage / database
The pipeline is intentionally stateless — output JSON is the only artifact. No database layer in scope.

### Web UI
CLI is the primary surface per assignment guidelines. A minimal FastAPI wrapper is straightforward to add on top of the existing `pipeline.run()` API.
