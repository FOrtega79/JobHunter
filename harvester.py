#!/usr/bin/env python3
"""Job harvester that scrapes product leadership roles using python-jobspy
and custom scrapers for additional job boards, storing unique results in
a local SQLite database."""

import re
import sqlite3
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup
from jobspy import scrape_jobs

DB_PATH = "jobs.db"

SEARCH_QUERIES = [
    "Head of Product",
    "Senior Product Manager",
]

LOCATIONS = [
    "Remote",
    "Spain",
    "Europe",
]

# python-jobspy supported sites
JOBSPY_SITES = ["indeed", "linkedin", "glassdoor", "google", "zip_recruiter"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

CUTOFF = datetime.now(timezone.utc) - timedelta(hours=24)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def init_db(db_path: str) -> sqlite3.Connection:
    """Create the jobs table if it doesn't exist."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            job_url TEXT PRIMARY KEY,
            site TEXT,
            title TEXT,
            company TEXT,
            location TEXT,
            date_posted TEXT,
            description TEXT,
            status TEXT DEFAULT 'Not Applied'
        )
        """
    )
    conn.commit()
    return conn


def save_jobs_from_df(conn: sqlite3.Connection, df) -> int:
    """Insert unique jobs from a pandas DataFrame (python-jobspy output)."""
    if df is None or df.empty:
        return 0

    new_count = 0
    for _, row in df.iterrows():
        job_url = str(row.get("job_url", ""))
        if not job_url:
            continue
        try:
            conn.execute(
                """
                INSERT INTO jobs (job_url, site, title, company, location, date_posted, description)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_url,
                    str(row.get("site", "")),
                    str(row.get("title", "")),
                    str(row.get("company", "")),
                    str(row.get("location", "")),
                    str(row.get("date_posted", "")),
                    str(row.get("description", "")),
                ),
            )
            new_count += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    return new_count


def save_jobs_from_list(conn: sqlite3.Connection, jobs: list[dict]) -> int:
    """Insert unique jobs from a list of dicts with standard keys."""
    new_count = 0
    for job in jobs:
        job_url = job.get("job_url", "")
        if not job_url:
            continue
        try:
            conn.execute(
                """
                INSERT INTO jobs (job_url, site, title, company, location, date_posted, description)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_url,
                    job.get("site", ""),
                    job.get("title", ""),
                    job.get("company", ""),
                    job.get("location", ""),
                    job.get("date_posted", ""),
                    job.get("description", ""),
                ),
            )
            new_count += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    return new_count


def _matches_query(text: str, query: str) -> bool:
    """Case-insensitive check that all words in *query* appear in *text*."""
    text_lower = text.lower()
    return all(word.lower() in text_lower for word in query.split())


# ---------------------------------------------------------------------------
# Custom scrapers — one per additional site
# ---------------------------------------------------------------------------

def scrape_workingnomads(query: str) -> list[dict]:
    """Working Nomads exposes a public JSON API at /api/exposed_jobs/."""
    url = "https://www.workingnomads.com/api/exposed_jobs/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"  [workingnomads] API error: {exc}")
        return []

    results = []
    for item in data:
        title = item.get("title", "")
        if not _matches_query(title, query):
            continue

        pub = item.get("pub_date", "")
        if pub:
            try:
                posted = datetime.fromisoformat(pub.replace("Z", "+00:00"))
                if posted < CUTOFF:
                    continue
            except ValueError:
                pass

        results.append({
            "job_url": item.get("url", ""),
            "site": "workingnomads",
            "title": title,
            "company": item.get("company_name", ""),
            "location": item.get("location", "Remote"),
            "date_posted": pub,
            "description": item.get("description", ""),
        })
    return results


def scrape_wellfound(query: str) -> list[dict]:
    """Scrape Wellfound job listings via their search page.

    Wellfound is a JS-rendered SPA backed by GraphQL.  We attempt to
    extract the embedded Apollo / Next.js JSON payload that ships with
    the initial HTML.  If the page blocks us or the structure changes
    we return an empty list gracefully.
    """
    slug = query.lower().replace(" ", "-")
    url = f"https://wellfound.com/role/{slug}/remote"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        print(f"  [wellfound] Request error: {exc}")
        return []

    results = []
    soup = BeautifulSoup(resp.text, "html.parser")

    # Wellfound embeds a __NEXT_DATA__ JSON blob with job data
    script = soup.find("script", id="__NEXT_DATA__")
    if script and script.string:
        try:
            import json
            payload = json.loads(script.string)
            # Navigate the nested props to find job listings
            props = payload.get("props", {}).get("pageProps", {})
            listings = props.get("jobListings", props.get("listings", []))
            if isinstance(listings, dict):
                listings = listings.get("salariedListings", listings.get("results", []))
            for item in (listings if isinstance(listings, list) else []):
                startup = item.get("startup", item.get("company", {})) or {}
                title = item.get("title", item.get("jobTitle", ""))
                if not _matches_query(title, query):
                    continue
                job_url = item.get("url", "")
                if not job_url and item.get("slug"):
                    job_url = f"https://wellfound.com/jobs/{item['slug']}"
                results.append({
                    "job_url": job_url,
                    "site": "wellfound",
                    "title": title,
                    "company": startup.get("name", ""),
                    "location": "Remote",
                    "date_posted": item.get("postedAt", item.get("liveStartAt", "")),
                    "description": item.get("description", ""),
                })
        except Exception as exc:
            print(f"  [wellfound] JSON parse error: {exc}")

    # Fallback: parse raw HTML links
    if not results:
        for card in soup.select("a[href*='/jobs/']"):
            title_text = card.get_text(strip=True)
            if _matches_query(title_text, query):
                href = card.get("href", "")
                if not href.startswith("http"):
                    href = f"https://wellfound.com{href}"
                results.append({
                    "job_url": href,
                    "site": "wellfound",
                    "title": title_text,
                    "company": "",
                    "location": "Remote",
                    "date_posted": "",
                    "description": "",
                })
    return results


def scrape_euremotejobs(query: str) -> list[dict]:
    """Scrape EU Remote Jobs (WordPress site) using its search endpoint."""
    params = {"s": query}
    url = f"https://euremotejobs.com/?{urllib.parse.urlencode(params)}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        print(f"  [euremotejobs] Request error: {exc}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []

    # WordPress job listing cards — try common WP Job Manager selectors
    cards = soup.select("li.job_listing, article.job_listing, div.job_listing")
    if not cards:
        # Fallback: look for article or post entries
        cards = soup.select("article, div.entry-content li, div.post")

    for card in cards:
        link = card.find("a", href=True)
        if not link:
            continue
        title_text = link.get_text(strip=True)
        if not _matches_query(title_text, query):
            continue
        href = link["href"]
        company_el = card.select_one(".company, .company-name, .entry-company")
        location_el = card.select_one(".location, .job-location")
        date_el = card.select_one("time, .date, .entry-date")

        results.append({
            "job_url": href,
            "site": "euremotejobs",
            "title": title_text,
            "company": company_el.get_text(strip=True) if company_el else "",
            "location": location_el.get_text(strip=True) if location_el else "Remote / Europe",
            "date_posted": date_el.get("datetime", date_el.get_text(strip=True)) if date_el else "",
            "description": "",
        })
    return results


def scrape_remotecom(query: str) -> list[dict]:
    """Scrape remote.com job search results."""
    params = {"query": query}
    url = f"https://remote.com/jobs/search?{urllib.parse.urlencode(params)}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        print(f"  [remote.com] Request error: {exc}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []

    # Try embedded JSON (Next.js / Nuxt pattern)
    script = soup.find("script", id="__NEXT_DATA__")
    if script and script.string:
        try:
            import json
            payload = json.loads(script.string)
            jobs = (
                payload.get("props", {})
                .get("pageProps", {})
                .get("jobs", [])
            )
            for item in jobs:
                title = item.get("title", "")
                if not _matches_query(title, query):
                    continue
                results.append({
                    "job_url": f"https://remote.com/jobs/{item.get('slug', '')}",
                    "site": "remote.com",
                    "title": title,
                    "company": item.get("company", {}).get("name", ""),
                    "location": item.get("location", "Remote"),
                    "date_posted": item.get("publishedAt", ""),
                    "description": item.get("description", ""),
                })
        except Exception:
            pass

    # Fallback: HTML parsing
    if not results:
        for card in soup.select("a[href*='/jobs/']"):
            text = card.get_text(strip=True)
            if _matches_query(text, query):
                href = card.get("href", "")
                if not href.startswith("http"):
                    href = f"https://remote.com{href}"
                results.append({
                    "job_url": href,
                    "site": "remote.com",
                    "title": text,
                    "company": "",
                    "location": "Remote",
                    "date_posted": "",
                    "description": "",
                })
    return results


def scrape_remoteco(query: str) -> list[dict]:
    """Scrape remote.co job listings (WordPress / WP Job Manager)."""
    url = "https://remote.co/remote-jobs/search/?search_keywords=" + urllib.parse.quote_plus(query)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        print(f"  [remote.co] Request error: {exc}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []

    cards = soup.select("li.job_listing, article.job_listing, div.job_listing")
    if not cards:
        cards = soup.select("article, div.card, a.card")

    for card in cards:
        link = card.find("a", href=True) if card.name != "a" else card
        if not link:
            continue
        title_el = card.select_one(".position h2, .job_listing-title, h2, h3")
        title_text = title_el.get_text(strip=True) if title_el else link.get_text(strip=True)
        if not _matches_query(title_text, query):
            continue
        href = link["href"]
        if not href.startswith("http"):
            href = f"https://remote.co{href}"

        company_el = card.select_one(".company, .companyName, .company-name")
        date_el = card.select_one("time, .date, .job-date")

        results.append({
            "job_url": href,
            "site": "remote.co",
            "title": title_text,
            "company": company_el.get_text(strip=True) if company_el else "",
            "location": "Remote",
            "date_posted": date_el.get("datetime", date_el.get_text(strip=True)) if date_el else "",
            "description": "",
        })
    return results


def scrape_nodesk(query: str) -> list[dict]:
    """Scrape Nodesk remote job listings."""
    url = "https://nodesk.co/remote-jobs/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        print(f"  [nodesk] Request error: {exc}")
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []

    # Nodesk uses a simple list/table of job links
    for link in soup.select("a[href*='/remote-jobs/']"):
        text = link.get_text(strip=True)
        if not text or not _matches_query(text, query):
            continue
        href = link.get("href", "")
        if not href.startswith("http"):
            href = f"https://nodesk.co{href}"
        # Avoid category/navigation links
        if href.rstrip("/") == "https://nodesk.co/remote-jobs":
            continue

        parent = link.find_parent("tr") or link.find_parent("li") or link.find_parent("div")
        company = ""
        date_posted = ""
        if parent:
            company_el = parent.select_one(".company, td:nth-of-type(2), span.company")
            date_el = parent.select_one("time, .date, td:last-of-type")
            if company_el:
                company = company_el.get_text(strip=True)
            if date_el:
                date_posted = date_el.get("datetime", date_el.get_text(strip=True))

        results.append({
            "job_url": href,
            "site": "nodesk",
            "title": text,
            "company": company,
            "location": "Remote",
            "date_posted": date_posted,
            "description": "",
        })
    return results


# ---------------------------------------------------------------------------
# Main harvest orchestrator
# ---------------------------------------------------------------------------

CUSTOM_SCRAPERS = [
    ("workingnomads", scrape_workingnomads),
    ("wellfound", scrape_wellfound),
    ("euremotejobs", scrape_euremotejobs),
    ("remote.com", scrape_remotecom),
    ("remote.co", scrape_remoteco),
    ("nodesk", scrape_nodesk),
]


def harvest():
    """Run all search combinations across jobspy + custom scrapers."""
    conn = init_db(DB_PATH)
    total_new = 0

    # --- python-jobspy sites ---
    for term in SEARCH_QUERIES:
        for location in LOCATIONS:
            print(f"[jobspy] Scraping: '{term}' in '{location}' …")
            try:
                df = scrape_jobs(
                    site_name=JOBSPY_SITES,
                    search_term=term,
                    google_search_term=f"{term} remote jobs in {location} since yesterday",
                    location=location,
                    is_remote=True,
                    hours_old=24,
                    results_wanted=50,
                    description_format="markdown",
                )
                added = save_jobs_from_df(conn, df)
                total_new += added
                print(f"  Found {len(df)} result(s), {added} new.")
            except Exception as exc:
                print(f"  Error: {exc}")

    # --- Custom scrapers ---
    for site_name, scraper_fn in CUSTOM_SCRAPERS:
        for term in SEARCH_QUERIES:
            print(f"[{site_name}] Scraping: '{term}' …")
            try:
                jobs = scraper_fn(term)
                added = save_jobs_from_list(conn, jobs)
                total_new += added
                print(f"  Found {len(jobs)} result(s), {added} new.")
            except Exception as exc:
                print(f"  Error: {exc}")
            time.sleep(1)  # polite delay between requests

    conn.close()
    print(f"\nDone. {total_new} new job(s) saved to {DB_PATH}.")


if __name__ == "__main__":
    harvest()
