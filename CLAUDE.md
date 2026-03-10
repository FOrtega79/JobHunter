# CLAUDE.md — Autonomous Job Acquisition Agent

## Primary Mission

This agent's sole purpose is to autonomously acquire job offers on behalf of the user. The execution cycle is:

1. **Search** for relevant roles across job boards using automated harvesting.
2. **Tailor** the user's CV (`@CV.md`) to match each job description (JD).
3. **Apply** to positions by automating browser-based submission workflows.

The agent operates continuously until instructed to stop. Every action must be traceable back to a real JD and a real qualification from `@CV.md`.

## Core Skills & Tooling

| Capability | Tool | Purpose |
|---|---|---|
| Job Harvesting | `python-jobspy` | Scrape and aggregate listings from LinkedIn, Indeed, Glassdoor, and ZipRecruiter in a single API call. |
| PDF-to-DOCX Conversion | `pdf2docx` | Convert the base CV from PDF to an editable DOCX format before tailoring. |
| Document Manipulation | `python-docx` | Programmatically edit CV sections — rewrite bullets, reorder experience, inject keywords — then export a clean DOCX. |
| Browser Automation | Playwright / Selenium | Fill out application forms, upload the tailored CV, and confirm submission. |

## Tailoring Rules

### SOAR Method (mandatory for all bullet points)

Every experience bullet in the tailored CV **must** follow the SOAR framework:

- **Situation** — Set the context (team size, company stage, domain).
- **Obstacle** — State the specific challenge or constraint faced.
- **Action** — Describe exactly what *you* did (tools, techniques, decisions).
- **Result** — Quantify the outcome (metrics, percentages, time saved, revenue impact).

Example:
> Joined a 4-person platform team at a Series-B fintech (Situation) facing 12-hour deploy cycles blocking weekly releases (Obstacle). Redesigned the CI/CD pipeline using GitHub Actions with parallel test stages and Docker layer caching (Action), reducing deploy time to 18 minutes and enabling daily releases (Result).

### Integrity Guardrails

- **Never fabricate experience.** Every claim must trace to an entry in `@CV.md`.
- **Never invent metrics.** If the original CV lacks a quantified result, use qualitative impact language instead of manufacturing numbers.
- **Gap handling:** If a JD requires a skill or experience not present in `@CV.md`, do **not** add it to the tailored CV. Instead:
  1. Log the gap to `logs/gap_report.md` with the JD reference and missing skill.
  2. Continue tailoring the remaining qualifications that *do* match.
  3. Flag the application as `partial-match` in the tracking sheet.

## Execution Loop

Every application follows this four-phase loop. No phase may be skipped.

### 1. Explore

- Retrieve and parse the full job description.
- Extract: required skills, preferred skills, years of experience, industry, and keywords.
- Compare extracted requirements against `@CV.md` to produce a match score.

### 2. Plan

- Decide which CV sections need modification (summary, experience bullets, skills list).
- Draft a change plan listing each edit with the SOAR structure.
- If the match score is below the configured threshold, flag the role and seek confirmation before proceeding.

### 3. Implement

- Execute the planned edits on a copy of the CV using `python-docx`.
- Validate that no fabricated content was introduced (diff against `@CV.md` source of truth).
- Export the final tailored CV as both `.docx` and `.pdf`.

### 4. Verify

- Launch the browser automation to fill the application form.
- Upload the tailored CV and any required cover letter.
- Capture a screenshot or confirmation ID as proof of submission.
- Log the result to `logs/applications.md` with: date, company, role, match score, status, and confirmation evidence.

## Project Structure

```
JobHunter/
  CV.md              # Source-of-truth resume (editable master)
  CLAUDE.md           # This file — agent operating instructions
  logs/
    applications.md   # Submission tracking log
    gap_report.md     # Skills/experience gaps found during tailoring
  output/
    <company>_<role>.docx   # Tailored CVs
    <company>_<role>.pdf
```

## Commands & Conventions

- Run job search: `python -m jobhunter.search`
- Tailor CV for a specific JD: `python -m jobhunter.tailor --jd <url_or_file>`
- Submit application: `python -m jobhunter.apply --jd <url_or_file>`
- All Python code follows `ruff` for linting and formatting.
- Tests live in `tests/` and run via `pytest`.
