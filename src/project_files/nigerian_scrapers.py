"""
Nigerian job board scrapers for Jobberman, MyJobMag, NgCareers, and HotNigerianJobs.
Performs direct HTML scraping using httpx and BeautifulSoup.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import random
import re
import urllib.parse
from datetime import datetime, timezone
from typing import List

from bs4 import BeautifulSoup
import httpx
from loguru import logger

from src.config import settings
from src.project_files.exceptions import BotBlockError, RateLimitError
from src.project_files.field_normalizer import extract_labeled_fields, normalize_fields, parse_datetime
from src.project_files.models import JobListing, SearchParams

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

BOT_BLOCK_KEYWORDS = ["captcha", "robot", "access denied", "unusual traffic"]


def _make_scraped_id(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]


def _check_bot_block(html: str, site: str) -> None:
    lower_html = html.lower()
    for kw in BOT_BLOCK_KEYWORDS:
        if kw in lower_html:
            raise BotBlockError(site)


def _extract_card_metadata(card: BeautifulSoup) -> dict:
    """Extract only metadata explicitly present in a Nigerian listing card."""
    text = card.get_text(" ", strip=True)
    labeled = extract_labeled_fields(text)
    date_value = None
    date_node = card.select_one("time[datetime], time, [data-posted], [data-date-posted]")
    if date_node:
        date_value = date_node.get("datetime") or date_node.get("data-posted") or date_node.get("data-date-posted") or date_node.get_text(" ", strip=True)
    if not date_value:
        date_match = re.search(r"(?:posted|published)\s*(?:on)?\s*[:\-]?\s*(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE)
        date_value = date_match.group(1) if date_match else None

    json_ld = None
    for script in card.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(script.string or script.get_text())
        except (TypeError, json.JSONDecodeError):
            continue
        values = payload if isinstance(payload, list) else [payload]
        json_ld = next((item for item in values if isinstance(item, dict) and item.get("@type") == "JobPosting"), None)
        if json_ld:
            break

    if json_ld:
        labeled = {**labeled, **extract_labeled_fields(json.dumps(json_ld))}
        if json_ld.get("employmentType"):
            labeled["employment_type"] = json_ld["employmentType"]
        if json_ld.get("jobLocationType"):
            labeled["work_model"] = json_ld["jobLocationType"]
        if json_ld.get("datePosted"):
            date_value = json_ld["datePosted"]
        if json_ld.get("department"):
            labeled["department"] = json_ld["department"] if isinstance(json_ld["department"], str) else json_ld["department"].get("name")

    fields = normalize_fields(
        title=None,
        snippet=text,
        location=labeled.get("location"),
        employment_type=labeled.get("employment_type"),
        work_model=labeled.get("work_model") or text,
        department=labeled.get("department"),
    )
    return {
        "employment_type": fields["employment_type"],
        "work_model": fields["work_model"],
        "department": fields["department"],
        "is_remote": fields["is_remote"],
        "posted_at": parse_datetime(date_value),
    }


class BaseScraper:
    site_name: str
    base_url: str

    def get_headers(self) -> dict[str, str]:
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Referer": self.base_url,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    async def fetch_html(self, client: httpx.AsyncClient, url: str) -> str:
        headers = self.get_headers()
        timeout = httpx.Timeout(settings.scraper_request_timeout_seconds)
        response = await client.get(url, headers=headers, timeout=timeout, follow_redirects=True)
        if response.status_code == 429:
            raise RateLimitError(self.site_name)
        response.raise_for_status()
        html = response.text
        _check_bot_block(html, self.site_name)
        return html

    async def search(
        self,
        client: httpx.AsyncClient,
        params: SearchParams,
    ) -> list[JobListing]:
        raise NotImplementedError


class JobbermanScraper(BaseScraper):
    site_name: str = "jobberman"
    base_url: str = "https://www.jobberman.com"

    async def search(
        self,
        client: httpx.AsyncClient,
        params: SearchParams,
    ) -> list[JobListing]:
        listings: list[JobListing] = []
        query_param = urllib.parse.quote_plus(params.job_title)
        url = f"{self.base_url}/jobs?q={query_param}"
        if params.location:
            url += f"&l={urllib.parse.quote_plus(params.location)}"

        html = ""
        try:
            html = await self.fetch_html(client, url)
        except RateLimitError:
            logger.warning(f"[{self.site_name}] HTTP 429 encountered. Waiting 5s for single retry.")
            await asyncio.sleep(5)
            try:
                html = await self.fetch_html(client, url)
            except Exception as e:
                logger.warning(f"[{self.site_name}] Retry failed: {e}")
                return listings
        except BotBlockError as e:
            logger.warning(f"[{self.site_name}] Bot block detected: {e}")
            return listings
        except Exception as e:
            logger.warning(f"[{self.site_name}] Scraping error: {e}")
            return listings

        try:
            soup = BeautifulSoup(html, "lxml")
            cards = soup.select("article, div[data-cy='listing-cards-components'], div.mx-5, div.flex-grow")
            now = datetime.now(timezone.utc)

            for card in cards:
                title_elem = card.select_one("a[href*='/listings/'], h3 a, h2 a, a[data-cy='listing-title']")
                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)
                href = title_elem.get("href", "")
                if not href or not title:
                    continue
                apply_url = urllib.parse.urljoin(self.base_url, href)

                company_elem = card.select_one("p.text-sm.text-link-500, a[href*='/employer/'], span[class*='company'], p.text-gray-500")
                company = company_elem.get_text(strip=True) if company_elem else "Unknown Company"

                loc_elem = card.select_one("span[class*='location'], span[class*='badge'], span.text-gray-500")
                loc = loc_elem.get_text(strip=True) if loc_elem else params.location
                metadata = _extract_card_metadata(card)

                listing_id = _make_scraped_id(apply_url)
                listings.append(
                    JobListing(
                        id=listing_id,
                        provider=self.site_name,
                        data_source="scrape",
                        title=title,
                        company=company,
                        company_slug=None,
                        location=loc,
                        is_remote=metadata["is_remote"],
                        employment_type=metadata["employment_type"],
                        work_model=metadata["work_model"],
                        department=metadata["department"],
                        posted_at=metadata["posted_at"],
                        scraped_at=now,
                        apply_url=apply_url,
                        source_url=apply_url,
                        query_used=params.job_title,
                        ats_source=self.site_name,
                    )
                )
        except Exception as e:
            logger.warning(f"[{self.site_name}] Parsing error: {e}")

        return listings


class MyJobMagScraper(BaseScraper):
    site_name: str = "myjobmag"
    base_url: str = "https://www.myjobmag.com"

    async def search(
        self,
        client: httpx.AsyncClient,
        params: SearchParams,
    ) -> list[JobListing]:
        listings: list[JobListing] = []
        query_param = urllib.parse.quote_plus(params.job_title)
        url = f"{self.base_url}/jobs/search?q={query_param}"

        try:
            html = await self.fetch_html(client, url)
            soup = BeautifulSoup(html, "lxml")
            items = soup.select("li.job-info, li.job-item, li[class*='job']")
            now = datetime.now(timezone.utc)

            for item in items:
                title_elem = item.select_one("h2 a, h3 a, a[href*='/job/']")
                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)
                href = title_elem.get("href", "")
                if not href or not title:
                    continue
                apply_url = urllib.parse.urljoin(self.base_url, href)

                company_elem = item.select_one("li.job-details a, a[href*='/jobs-at/'], span.company-name")
                company = company_elem.get_text(strip=True) if company_elem else "Unknown Company"

                loc_elem = item.select_one("li.job-details span[id*='location'], span.location")
                loc = loc_elem.get_text(strip=True) if loc_elem else params.location
                metadata = _extract_card_metadata(item)

                listing_id = _make_scraped_id(apply_url)
                listings.append(
                    JobListing(
                        id=listing_id,
                        provider=self.site_name,
                        data_source="scrape",
                        title=title,
                        company=company,
                        company_slug=None,
                        location=loc,
                        is_remote=metadata["is_remote"],
                        employment_type=metadata["employment_type"],
                        work_model=metadata["work_model"],
                        department=metadata["department"],
                        posted_at=metadata["posted_at"],
                        scraped_at=now,
                        apply_url=apply_url,
                        source_url=apply_url,
                        query_used=params.job_title,
                        ats_source=self.site_name,
                    )
                )
        except BotBlockError as e:
            logger.warning(f"[{self.site_name}] Bot block detected: {e}")
        except Exception as e:
            logger.warning(f"[{self.site_name}] Scraper error: {e}")

        return listings


class NgCareersScraper(BaseScraper):
    site_name: str = "ngcareers"
    base_url: str = "https://ngcareers.com"

    async def search(
        self,
        client: httpx.AsyncClient,
        params: SearchParams,
    ) -> list[JobListing]:
        listings: list[JobListing] = []
        query_param = urllib.parse.quote_plus(params.job_title)
        url = f"{self.base_url}/jobs/search?keywords={query_param}"

        try:
            html = await self.fetch_html(client, url)
            soup = BeautifulSoup(html, "lxml")
            items = soup.select(".job-item, article, div.job-box, div[class*='job-listing']")
            now = datetime.now(timezone.utc)

            for item in items:
                title_elem = item.select_one("a[href*='/job/'], h2 a, h3 a")
                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)
                href = title_elem.get("href", "")
                if not href or not title:
                    continue
                apply_url = urllib.parse.urljoin(self.base_url, href)

                company_elem = item.select_one(".company, .employer, span[class*='company']")
                company = company_elem.get_text(strip=True) if company_elem else "Unknown Company"

                loc_elem = item.select_one(".location, span[class*='location']")
                loc = loc_elem.get_text(strip=True) if loc_elem else params.location
                metadata = _extract_card_metadata(item)

                listing_id = _make_scraped_id(apply_url)
                listings.append(
                    JobListing(
                        id=listing_id,
                        provider=self.site_name,
                        data_source="scrape",
                        title=title,
                        company=company,
                        company_slug=None,
                        location=loc,
                        is_remote=metadata["is_remote"],
                        employment_type=metadata["employment_type"],
                        work_model=metadata["work_model"],
                        department=metadata["department"],
                        posted_at=metadata["posted_at"],
                        scraped_at=now,
                        apply_url=apply_url,
                        source_url=apply_url,
                        query_used=params.job_title,
                        ats_source=self.site_name,
                    )
                )
        except BotBlockError as e:
            logger.warning(f"[{self.site_name}] Bot block detected: {e}")
        except Exception as e:
            logger.warning(f"[{self.site_name}] Scraper error: {e}")

        return listings


class HotNigerianJobsScraper(BaseScraper):
    site_name: str = "hotnigerianJobs"
    base_url: str = "https://www.hotnigerianjobs.com"

    async def search(
        self,
        client: httpx.AsyncClient,
        params: SearchParams,
    ) -> list[JobListing]:
        listings: list[JobListing] = []
        query_param = urllib.parse.quote_plus(params.job_title)
        url = f"{self.base_url}/?s={query_param}"

        try:
            html = await self.fetch_html(client, url)
            soup = BeautifulSoup(html, "lxml")
            items = soup.select(".mycase, div[class*='job'], article, .post")
            now = datetime.now(timezone.utc)

            for item in items:
                title_elem = item.select_one("h2 a, h3 a, a[rel='bookmark'], a[href*='hotnigerianjobs.com/hotjobs/']")
                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)
                href = title_elem.get("href", "")
                if not href or not title:
                    continue
                apply_url = urllib.parse.urljoin(self.base_url, href)
                metadata = _extract_card_metadata(item)

                listing_id = _make_scraped_id(apply_url)
                listings.append(
                    JobListing(
                        id=listing_id,
                        provider=self.site_name,
                        data_source="scrape",
                        title=title,
                        company="Various / HotNigerianJobs",
                        company_slug=None,
                        location=params.location,
                        is_remote=metadata["is_remote"],
                        employment_type=metadata["employment_type"],
                        work_model=metadata["work_model"],
                        department=metadata["department"],
                        posted_at=metadata["posted_at"],
                        scraped_at=now,
                        apply_url=apply_url,
                        source_url=apply_url,
                        query_used=params.job_title,
                        ats_source=self.site_name,
                    )
                )
        except BotBlockError as e:
            logger.warning(f"[{self.site_name}] Bot block detected: {e}")
        except Exception as e:
            logger.warning(f"[{self.site_name}] Scraper error: {e}")

        return listings


NIGERIAN_SCRAPERS: list[BaseScraper] = [
    JobbermanScraper(),
    MyJobMagScraper(),
    NgCareersScraper(),
    HotNigerianJobsScraper(),
]
