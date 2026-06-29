#!/usr/bin/env python3
"""
Multi-Source Candidate Data Transformer — CLI
Usage: python cli.py --help
"""
import json
import logging
import sys
from pathlib import Path

import click
from dotenv import load_dotenv

load_dotenv()

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


@click.command()
@click.option("--csv", "csv_file", type=click.Path(exists=True), default=None, help="Recruiter CSV file")
@click.option("--ats-json", "ats_json_file", type=click.Path(exists=True), default=None, help="ATS JSON export file")
@click.option("--github", "github_url", default=None, help="GitHub profile URL (e.g. https://github.com/username)")
@click.option("--resume", "resume_file", type=click.Path(exists=True), default=None, help="Resume file (PDF or DOCX)")
@click.option("--notes", "notes_file", type=click.Path(exists=True), default=None, help="Recruiter notes (.txt)")
@click.option("--config", "config_file", type=click.Path(exists=True), default=None, help="Output config JSON file")
@click.option("--output", "output_file", default=None, help="Output file path (default: stdout)")
@click.option("--verbose", is_flag=True, default=False, help="Enable debug logging")
def main(csv_file, ats_json_file, github_url, resume_file, notes_file, config_file, output_file, verbose):
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
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    _print_banner()

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

    # Load config
    config = {}
    if config_file:
        with open(config_file, encoding="utf-8") as f:
            config = json.load(f)
        click.echo(click.style(f"\n  Config: {config_file}", fg="yellow"), err=True)

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
