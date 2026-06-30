import logging

from transformer.extractors.base import BaseExtractor
from transformer.models import SourceItem, RawRecord

logger = logging.getLogger(__name__)


class LinkedInExtractor(BaseExtractor):
    """
    Extracts from an OAuth-fetched LinkedIn profile dict (passed in as
    source.raw_content), not from scraping a bare URL.

    Only fields available via LinkedIn's self-serve OAuth scopes
    (openid, profile, email, r_basicprofile) are populated: name, email,
    headline, public profile URL. Experience/education/skills are NOT
    available without LinkedIn's Marketing Developer Platform partnership,
    so those fields are intentionally left empty.
    """

    def extract(self, source: SourceItem) -> RawRecord:
        profile = source.raw_content
        record = RawRecord(source_type="linkedin_url")

        if not isinstance(profile, dict):
            logger.warning("LinkedIn extractor expected a profile dict, got %s", type(profile))
            return record

        full_name = profile.get("name") or " ".join(
            filter(None, [profile.get("given_name"), profile.get("family_name")])
        ).strip()
        if full_name:
            record.full_name = full_name

        email = profile.get("email")
        if email:
            record.emails = [email]

        headline = profile.get("headline") or profile.get("localizedHeadline")
        if headline:
            record.headline = headline

        profile_url = profile.get("public_profile_url") or profile.get("profile_url")
        if profile_url:
            record.linkedin_url = profile_url

        return record
