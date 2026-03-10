#!/usr/bin/env python3
"""Job harvester that scrapes product leadership roles using python-jobspy
and stores unique results in a local SQLite database."""

import sqlite3
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

SITES = ["indeed", "linkedin", "glassdoor", "google", "zip_recruiter"]


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


def save_jobs(conn: sqlite3.Connection, df) -> int:
    """Insert unique jobs into the database. Returns count of new rows."""
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
            # Duplicate job_url — skip
            pass
    conn.commit()
    return new_count


def harvest():
    """Run all search combinations and persist results."""
    conn = init_db(DB_PATH)
    total_new = 0

    for term in SEARCH_QUERIES:
        for location in LOCATIONS:
            print(f"Scraping: '{term}' in '{location}' …")
            try:
                df = scrape_jobs(
                    site_name=SITES,
                    search_term=term,
                    google_search_term=f"{term} remote jobs in {location} since yesterday",
                    location=location,
                    is_remote=True,
                    hours_old=24,
                    results_wanted=50,
                    description_format="markdown",
                )
                added = save_jobs(conn, df)
                total_new += added
                print(f"  Found {len(df)} result(s), {added} new.")
            except Exception as exc:
                print(f"  Error: {exc}")

    conn.close()
    print(f"\nDone. {total_new} new job(s) saved to {DB_PATH}.")


if __name__ == "__main__":
    harvest()
