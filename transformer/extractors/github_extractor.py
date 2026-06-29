import logging
import os
import re
import time
from urllib.parse import urlparse

import requests

from transformer.extractors.base import BaseExtractor
from transformer.models import SourceItem, RawRecord

logger = logging.getLogger(__name__)

ALLOWED_DOMAINS = {"github.com", "api.github.com"}
GITHUB_API = "https://api.github.com"


def _validate_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme == "https" and parsed.netloc in ALLOWED_DOMAINS
    except Exception:
        return False


def _extract_username(url: str) -> str | None:
    m = re.search(r"github\.com/([^/?#]+)", url)
    if m:
        username = m.group(1).rstrip("/")
        if username and username not in ("login", "signup", "explore"):
            return username
    return None


def _github_get(path: str, token: str | None, retry: bool = True) -> dict | list | None:
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{GITHUB_API}{path}"
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code in (403, 429) and retry:
            logger.warning("GitHub rate limit hit, retrying once")
            time.sleep(1)
            return _github_get(path, token, retry=False)
        if resp.status_code == 404:
            logger.warning("GitHub profile not found (404)")
            return None
        logger.warning("GitHub API returned %s", resp.status_code)
        return None
    except requests.RequestException as e:
        logger.warning("GitHub API request failed: %s", e)
        return None


class GitHubExtractor(BaseExtractor):
    def extract(self, source: SourceItem) -> RawRecord:
        record = RawRecord(source_type="github_url")
        url = str(source.raw_content).strip()

        if not _validate_url(url):
            logger.warning("GitHub URL failed domain validation")
            return record

        username = _extract_username(url)
        if not username:
            logger.warning("Could not extract GitHub username from URL")
            return record

        token = os.environ.get("GITHUB_TOKEN")

        user_data = _github_get(f"/users/{username}", token)
        if not user_data or not isinstance(user_data, dict):
            return record

        record.full_name = user_data.get("name")
        record.headline = user_data.get("bio")
        record.location_raw = user_data.get("location")
        record.github_url = url

        email = user_data.get("email")
        if email:
            record.emails = [email]

        blog = user_data.get("blog")
        if blog and blog.strip():
            blog = blog.strip()
            if not blog.startswith("http"):
                blog = "https://" + blog
            record.portfolio_url = blog

        # Languages from repos
        repos_data = _github_get(f"/users/{username}/repos?per_page=30&sort=updated", token)
        if repos_data and isinstance(repos_data, list):
            lang_counts: dict[str, int] = {}
            for repo in repos_data:
                lang = repo.get("language")
                if lang:
                    lang_counts[lang] = lang_counts.get(lang, 0) + 1
            # Top 10 languages by repo count → skills
            top_langs = sorted(lang_counts, key=lambda k: lang_counts[k], reverse=True)[:10]
            record.skills_raw = top_langs

        return record
