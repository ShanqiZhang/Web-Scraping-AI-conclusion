# GCC Think Tank Intelligence Scraper

A Python-based pipeline for automated collection, full-text extraction, and AI-powered Chinese summarization of policy research from MENA think tanks, with a focus on Gulf Cooperation Council (GCC) affairs.

Developed by **shanqizhang** in 2026 for internal research and experimental purposes.

---

## What This Does

This tool automates a three-stage workflow:

1. **Scrape** — Collects article titles, dates, and URLs from target think tank websites (AJCS, Rasanah, and others)
2. **Extract** — Fetches full article text from each URL, with PDF fallback for report-style publications
3. **Summarize** — Calls the Gemini API to generate structured Chinese-language briefs, formatted as a Word document for policy audiences

---

## Project Structure

```
├── scrapers_v2.py       # Stage 1: Article list scraping
├── fetch_fulltext.py    # Stage 2: Full-text and PDF extraction
├── summarize.py         # Stage 3: AI summarization → Word output
└── requirements.txt
```

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Set your API key

**Do not hardcode your API key.** Pass it at runtime:

```bash
python summarize.py --input output/gcc_fulltext_YYYYMMDD_HHMM.csv --key YOUR_API_KEY
```

Or store it in a `.env` file (never commit this to version control):

```
GEMINI_API_KEY=your_key_here
```

### 3. Run the pipeline

```bash
# Stage 1: Scrape article listings
python scrapers_v2.py --all

# Stage 2: Fetch full text
python fetch_fulltext.py --input output/gcc_all_sources_YYYYMMDD_HHMM.csv

# Stage 3: Generate Chinese summaries → Word document
python summarize.py --input output/gcc_fulltext_YYYYMMDD_HHMM.csv --key YOUR_KEY
```

Use `--test` on any script to process only the first 3 items.

---

## ⚖️ License & Rights

This project is licensed under the **GNU Affero General Public License v3.0 (AGPL-3.0)**.

**Copyright (c) 2026 shanqizhang. All rights reserved.**

- Anyone (including colleagues and employers) may download, modify, and run this code under the terms of AGPLv3.
- If this software or any derivative work is used to provide a network service or distributed externally, the full source code must be made available and the original copyright notice must be retained.
- The organization holds the right to use this version internally. However, the core logic of this program may not be resold or commercialized as a standalone product without the author's prior written consent.

---

## ⚠️ Disclaimer

**Please read before use:**

- **Legal compliance**: Users (individuals and organizations) are solely responsible for ensuring that scraping activity complies with each target website's `robots.txt` and Terms of Service (ToS).
- **Liability**: This tool is provided as-is for technical purposes. The author accepts no liability for IP bans, legal disputes, or data privacy issues arising from misuse.
- **API costs**: This pipeline calls third-party AI APIs (Gemini). Users must supply their own API keys. The author is not responsible for any charges incurred during testing or production use.
- **Data accuracy**: Summaries are AI-generated and should be verified before use in official publications.

---

## Technical Support

For questions about the code logic, please reach out via your organization's internal communication channels.
