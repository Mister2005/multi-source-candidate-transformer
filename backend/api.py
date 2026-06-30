#!/usr/bin/env python3
"""
Minimal FastAPI surface over the candidate transformer pipeline.

Run from backend/:
    uvicorn api:app --reload --port 8000
"""
import logging
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from dotenv import load_dotenv
import requests

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from transformer.pipeline import TransformerPipeline
from transformer import storage

app = FastAPI(title="Candidate Data Transformer API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

LINKEDIN_REDIRECT_URI = "http://localhost:8000/auth/linkedin/callback"
# r_basicprofile is a separate legacy product from "Sign In with LinkedIn using
# OpenID Connect" and may not be grantable on newer apps. If LinkedIn rejects
# the full scope set with unauthorized_scope_error, drop it back to just
# "openid profile email" (still gives name/email/photo via /v2/userinfo).
LINKEDIN_SCOPES = os.environ.get("LINKEDIN_SCOPES", "openid profile email r_basicprofile")


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        raise HTTPException(500, "DATABASE_URL is not configured")
    return url


async def _save_upload(upload: UploadFile, suffix: str) -> str:
    data = await upload.read()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.write(data)
    tmp.close()
    return tmp.name


@app.post("/transform")
async def transform(
    csv_file: UploadFile | None = File(None),
    ats_json_file: UploadFile | None = File(None),
    resume_file: UploadFile | None = File(None),
    notes_file: UploadFile | None = File(None),
    github_url: str | None = Form(None),
    save_to_db: bool = Form(False),
):
    sources = []
    tmp_paths = []

    try:
        if csv_file is not None:
            path = await _save_upload(csv_file, ".csv")
            tmp_paths.append(path)
            sources.append({"type": "csv", "content": path})
        if ats_json_file is not None:
            path = await _save_upload(ats_json_file, ".json")
            tmp_paths.append(path)
            sources.append({"type": "ats_json", "content": path})
        if resume_file is not None:
            ext = Path(resume_file.filename or "").suffix.lower() or ".pdf"
            src_type = "resume_pdf" if ext == ".pdf" else "resume_docx"
            path = await _save_upload(resume_file, ext)
            tmp_paths.append(path)
            sources.append({"type": src_type, "content": path})
        if notes_file is not None:
            path = await _save_upload(notes_file, ".txt")
            tmp_paths.append(path)
            sources.append({"type": "recruiter_txt", "content": path})
        if github_url:
            sources.append({"type": "github_url", "content": github_url})

        if not sources:
            raise HTTPException(400, "No sources provided")

        pipeline = TransformerPipeline()
        result = pipeline.run(sources, {})

        if save_to_db:
            try:
                storage.save_candidate(result, _database_url())
            except Exception as e:
                logger.error("DB save failed: %s", e)
                result.setdefault("_warnings", []).append(f"DB save failed: {e}")

        return result
    finally:
        for p in tmp_paths:
            try:
                os.unlink(p)
            except OSError:
                pass


@app.get("/candidates")
def list_candidates():
    return storage.list_candidates(_database_url())


@app.get("/candidates/{candidate_id}")
def get_candidate(candidate_id: str):
    record = storage.get_candidate(candidate_id, _database_url())
    if not record:
        raise HTTPException(404, "Candidate not found")
    return record


@app.get("/auth/linkedin/login")
def linkedin_login():
    client_id = os.environ.get("LINKEDIN_CLIENT_ID", "")
    if not client_id:
        raise HTTPException(500, "LINKEDIN_CLIENT_ID is not configured")
    authorize_url = (
        "https://www.linkedin.com/oauth/v2/authorization"
        f"?response_type=code&client_id={client_id}"
        f"&redirect_uri={LINKEDIN_REDIRECT_URI}"
        f"&scope={LINKEDIN_SCOPES.replace(' ', '%20')}"
    )
    return RedirectResponse(authorize_url)


@app.get("/auth/linkedin/callback")
def linkedin_callback(code: str | None = None, error: str | None = None, save_to_db: bool = True):
    if error:
        raise HTTPException(400, f"LinkedIn OAuth error: {error}")
    if not code:
        raise HTTPException(400, "Missing authorization code")

    client_id = os.environ.get("LINKEDIN_CLIENT_ID", "")
    client_secret = os.environ.get("LINKEDIN_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise HTTPException(500, "LinkedIn OAuth credentials are not configured")

    token_resp = requests.post(
        "https://www.linkedin.com/oauth/v2/accessToken",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": LINKEDIN_REDIRECT_URI,
            "client_id": client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10,
    )
    if token_resp.status_code != 200:
        raise HTTPException(502, f"LinkedIn token exchange failed: {token_resp.status_code}")
    access_token = token_resp.json().get("access_token")

    profile_resp = requests.get(
        "https://api.linkedin.com/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    if profile_resp.status_code != 200:
        raise HTTPException(502, f"LinkedIn profile fetch failed: {profile_resp.status_code}")

    profile = profile_resp.json()

    # Run the fetched profile through the same pipeline as any other source,
    # so LinkedIn data actually merges into a canonical record instead of
    # just being returned raw.
    pipeline = TransformerPipeline()
    result = pipeline.run([{"type": "linkedin_url", "content": profile}], {})

    db_row_id = None
    if save_to_db:
        try:
            db_row_id = storage.save_candidate(result, _database_url())
        except Exception as e:
            logger.error("DB save failed: %s", e)
            result.setdefault("_warnings", []).append(f"DB save failed: {e}")

    return {"linkedin_profile_raw": profile, "canonical_record": result, "db_row_id": db_row_id}


@app.get("/health")
def health():
    return {"status": "ok"}
