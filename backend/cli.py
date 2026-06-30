#!/usr/bin/env python3
"""
Multi-Source Candidate Data Transformer — CLI
Usage: python cli.py --help
"""
import json
import logging
import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv

# .env lives at the project root, one directory up from backend/
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)


def _print_banner():
    click.echo(click.style("\n  Eightfold Candidate Data Transformer v1.0", fg="cyan", bold=True), err=True)
    click.echo(click.style("  " + "─" * 50, fg="cyan"), err=True)


def _print_sources(sources: list[dict]):
    click.echo(click.style("\n  Sources:", fg="yellow", bold=True), err=True)
    for s in sources:
        label = s.get("type", "?").ljust(18)
        content = str(s.get("content", ""))[:60]
        click.echo(f"    ✓ {label} → {content}", err=True)


def _save_result_to_db(result: dict) -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        click.echo(click.style("  [ERROR] --save-to-db set but DATABASE_URL is not configured.", fg="red"), err=True)
        return
    from transformer.storage import save_candidate
    row_id = save_candidate(result, database_url)
    click.echo(click.style(f"  ✓ Saved to Postgres (row id={row_id})", fg="green"), err=True)


def _build_sources_for_folder(folder: Path) -> list[dict]:
    """Convention-based source discovery for a single candidate folder in batch mode."""
    sources = []
    csv_path = folder / "data.csv"
    ats_path = folder / "ats.json"
    resume_pdf = folder / "resume.pdf"
    resume_docx = folder / "resume.docx"
    notes_path = folder / "notes.txt"

    if csv_path.exists():
        sources.append({"type": "csv", "content": str(csv_path)})
    if ats_path.exists():
        sources.append({"type": "ats_json", "content": str(ats_path)})
    if resume_pdf.exists():
        sources.append({"type": "resume_pdf", "content": str(resume_pdf)})
    elif resume_docx.exists():
        sources.append({"type": "resume_docx", "content": str(resume_docx)})
    if notes_path.exists():
        sources.append({"type": "recruiter_txt", "content": str(notes_path)})
    return sources


def _run_batch(batch_dir: str, config: dict, save_to_db: bool) -> None:
    from transformer.pipeline import TransformerPipeline

    batch_path = Path(batch_dir)
    candidate_folders = sorted([p for p in batch_path.iterdir() if p.is_dir()])

    if not candidate_folders:
        click.echo(click.style(f"  [ERROR] No candidate subfolders found in {batch_dir}", fg="red"), err=True)
        sys.exit(2)

    click.echo(click.style(f"\n  Batch mode: {len(candidate_folders)} candidate folder(s) found", fg="yellow", bold=True), err=True)

    pipeline = TransformerPipeline()
    summary = {"batch_dir": str(batch_path), "total": len(candidate_folders), "results": []}

    for folder in candidate_folders:
        sources = _build_sources_for_folder(folder)
        entry = {"folder": folder.name}
        if not sources:
            entry["status"] = "skipped"
            entry["reason"] = "no recognized source files (data.csv/ats.json/resume.pdf|docx/notes.txt)"
            click.echo(click.style(f"    ⚠ {folder.name}: no sources found, skipped", fg="yellow"), err=True)
            summary["results"].append(entry)
            continue

        try:
            result = pipeline.run(sources, config)
        except Exception as e:
            entry["status"] = "error"
            entry["reason"] = str(e)
            click.echo(click.style(f"    ✗ {folder.name}: pipeline error: {e}", fg="red"), err=True)
            summary["results"].append(entry)
            continue

        errors = result.get("_errors", [])
        entry["status"] = "error" if errors else "ok"
        entry["candidate_id"] = result.get("candidate_id")
        entry["overall_confidence"] = result.get("overall_confidence")
        if errors:
            entry["errors"] = errors

        out_file = folder / "canonical_output.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        entry["output_file"] = str(out_file)

        if save_to_db and not errors:
            try:
                database_url = os.environ.get("DATABASE_URL", "")
                if database_url:
                    from transformer.storage import save_candidate
                    row_id = save_candidate(result, database_url)
                    entry["db_row_id"] = row_id
                else:
                    entry["db_error"] = "DATABASE_URL not configured"
            except Exception as e:
                entry["db_error"] = str(e)

        status_color = "green" if entry["status"] == "ok" else "red"
        click.echo(click.style(f"    {'✓' if entry['status'] == 'ok' else '✗'} {folder.name}: {entry['status']}", fg=status_color), err=True)

        summary["results"].append(entry)

    summary_path = batch_path / "batch_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    ok_count = sum(1 for r in summary["results"] if r["status"] == "ok")
    click.echo(click.style(f"\n  Batch complete: {ok_count}/{len(candidate_folders)} succeeded", fg="cyan", bold=True), err=True)
    click.echo(click.style(f"  Summary written to: {summary_path}", fg="cyan"), err=True)


@click.command()
@click.option("--csv", "csv_file", type=click.Path(exists=True), default=None, help="Recruiter CSV file")
@click.option("--ats-json", "ats_json_file", type=click.Path(exists=True), default=None, help="ATS JSON export file")
@click.option("--github", "github_url", default=None, help="GitHub profile URL (e.g. https://github.com/username)")
@click.option("--resume", "resume_file", type=click.Path(exists=True), default=None, help="Resume file (PDF or DOCX)")
@click.option("--notes", "notes_file", type=click.Path(exists=True), default=None, help="Recruiter notes (.txt)")
@click.option("--config", "config_file", type=click.Path(exists=True), default=None, help="Output config JSON file")
@click.option("--output", "output_file", default=None, help="Output file path (default: stdout)")
@click.option("--verbose", is_flag=True, default=False, help="Enable debug logging")
@click.option("--save-to-db", is_flag=True, default=False, help="Save result(s) to Postgres (reads DATABASE_URL from .env)")
@click.option("--batch", "batch_dir", type=click.Path(exists=True, file_okay=False), default=None,
              help="Process every candidate subfolder in this directory (data.csv/ats.json/resume.pdf|docx/notes.txt convention)")
def main(csv_file, ats_json_file, github_url, resume_file, notes_file, config_file, output_file, verbose, save_to_db, batch_dir):
    """
    Transform candidate data from multiple sources into a single canonical profile.

    \b
    Examples:
      # Basic run with CSV + resume
      python cli.py --csv recruiter.csv --resume resume.pdf --output out.json

      # Full run with custom config
      python cli.py --csv recruiter.csv --ats-json ats.json --resume resume.pdf \\
                    --github https://github.com/username --notes notes.txt \\
                    --config config.json --output out.json

      # Save result to Postgres
      python cli.py --csv recruiter.csv --resume resume.pdf --save-to-db

      # Batch process a folder of candidate subfolders
      python cli.py --batch path/to/batch_folder --save-to-db
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    _print_banner()

    # Load config (shared by single-run and batch modes)
    config = {}
    if config_file:
        with open(config_file, encoding="utf-8") as f:
            config = json.load(f)
        click.echo(click.style(f"\n  Config: {config_file}", fg="yellow"), err=True)

    if batch_dir:
        _run_batch(batch_dir, config, save_to_db)
        return

    # Build source list
    sources = []
    if csv_file:
        sources.append({"type": "csv", "content": csv_file})
    if ats_json_file:
        sources.append({"type": "ats_json", "content": ats_json_file})
    if github_url:
        sources.append({"type": "github_url", "content": github_url})
    if resume_file:
        ext = Path(resume_file).suffix.lower()
        src_type = "resume_pdf" if ext == ".pdf" else "resume_docx"
        sources.append({"type": src_type, "content": resume_file})
    if notes_file:
        sources.append({"type": "recruiter_txt", "content": notes_file})

    if not sources:
        click.echo(click.style("  [ERROR] No sources provided. Use --help for usage.", fg="red"), err=True)
        sys.exit(2)

    _print_sources(sources)

    # Run pipeline
    click.echo(click.style("\n  Running pipeline...", fg="yellow", bold=True), err=True)
    from transformer.pipeline import TransformerPipeline
    pipeline = TransformerPipeline()
    result = pipeline.run(sources, config)

    # Output
    output_json = json.dumps(result, indent=2, ensure_ascii=False)

    if output_file:
        Path(output_file).parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(output_json)
        click.echo(click.style(f"\n  ✓ Output written to: {output_file}", fg="green", bold=True), err=True)
    else:
        click.echo(output_json)

    if save_to_db:
        _save_result_to_db(result)

    # Summary
    confidence = result.get("overall_confidence") or result.get("_confidence", 0)
    name = result.get("full_name", "[MASKED]") or "[no name]"
    errors = result.get("_errors", [])
    warnings = result.get("_warnings", [])

    click.echo(click.style("\n  " + "─" * 50, fg="cyan"), err=True)
    if errors:
        click.echo(click.style(f"  ⚠ Errors: {len(errors)}", fg="red"), err=True)
        for e in errors:
            click.echo(f"    • {e}", err=True)
    if warnings:
        click.echo(click.style(f"  ⚠ Warnings: {len(warnings)}", fg="yellow"), err=True)
        for w in warnings:
            click.echo(f"    • {w}", err=True)

    click.echo(
        click.style(f"  Candidate: [MASKED] | Confidence: {confidence:.0%}", fg="green"),
        err=True,
    )
    click.echo("", err=True)

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
