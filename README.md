# Bottom Pot — ATS Job Scraper

Bottom Pot searches applicant-tracking-system (ATS) sites directly — Greenhouse, Lever, Ashby, Workable, and 16 others — instead of relying on aggregators like LinkedIn or Indeed. It builds a targeted Google search ("dork") per platform, runs it through the [Serper.dev](https://serper.dev) API, and saves the matching job postings to JSON and CSV.

## Why search ATS platforms directly?

Aggregators re-index listings on their own schedule and often surface stale or duplicate postings. Most companies' actual job pages live on one of a small number of ATS platforms (`boards.greenhouse.io`, `jobs.lever.co`, `jobs.ashby.com`, etc.). By restricting a Google search to `site:<ats-domain>`, Bottom Pot finds postings closer to the source and closer to when they were published, using Google's own freshness/date filtering rather than an aggregator's.

## How it works

```
CLI args (main.py)
      │
      ▼
SearchParams (pydantic model, src/project_files/models.py)
      │
      ▼
QueryBuilder — one Google dork query per ATS platform (src/project_files/query_builder.py)
      │            e.g. site:greenhouse.io "frontend engineer" "remote" after:2026-04-03
      ▼
SerperSearcher — async POST to Serper.dev per platform, paginated (src/project_files/serper_searcher.py)
      │
      ▼
RawSearchResults parsed from Serper's "organic" results, filtered to https + non-empty title
      │
      ▼
outputs/json/<prefix>_results.json  +  outputs/csv/<prefix>_results.csv
```

Each ATS platform is queried independently and in sequence, up to `SERPER_MAX_PAGES` (3) pages per platform, 10 results per page. All results across platforms are collected, then truncated to `--max-results`.

## Supported platforms

Greenhouse, Greenhouse Boards, Lever, Ashby, Workable, BambooHR, Jobvite, Notion, SmartRecruiters, iCIMS, Personio, Teamtailor, Recruitee, Breezy HR, Workday, Taleo, JobAdder, JazzHR, Avature, SAP SuccessFactors.

Full list with domains lives in `src/project_files/config.py:ATS_PLATFORMS`.

## Project structure

```
main.py                          CLI entry point — arg parsing, orchestration, output writing
src/project_files/
  config.py                      ATS platform list, Serper API key/endpoint/page-budget
  models.py                      Pydantic models: SearchParams, ATSConfig, RawSearchResults
  query_builder.py                Builds the Google dork query + Serper payload per platform
  serper_searcher.py             Async Serper API client — pagination, parsing, error handling
outputs/
  json/, csv/                    Timestamped run outputs
```

## Installation

Requires Python 3.10+ (the codebase uses `str | None` union type hints).

```bash
git clone https://github.com/richmondsogo/bottom-pot-ats-scraper.git
cd bottom-pot-ats-scraper
python -m venv venv
source venv/bin/activate   # venv\Scripts\activate on Windows
pip install -r requirements.txt
```

Get a free API key at [serper.dev](https://serper.dev) (2,500 free credits — each paginated request costs 1 credit, so a full run across all 20 platforms at 3 pages each costs ~60 credits, or roughly 41 full runs on the free tier). Then create a `.env` file in the project root:

```
SERPER_API_KEY=your_key_here
```

## Usage

Basic search:

```bash
python main.py --job-title "Data Engineer"
```

Remote-only, senior, posted in the last 3 days, excluding contract roles, capped at 50 results:

```bash
python main.py \
  --job-title "Backend Engineer" \
  --remote \
  --experience-level senior \
  --days-back 3 \
  --exclude-keywords "contract,internship" \
  --max-results 50
```

Search only specific platforms:

```bash
python main.py --job-title "Product Designer" --platforms greenhouse,lever,ashby
```

### CLI options

| Flag | Default | Description |
|---|---|---|
| `--job-title` | *(required)* | Job title to search for |
| `--location` | `None` | City/region added to the query |
| `--country-code` | `None` | Restrict Google's index, e.g. `us`, `gb` |
| `--days-back` | `7` | Only listings posted within the last N days |
| `--remote` / `--no-remote` | both | Include-only or exclude remote roles (mutually exclusive) |
| `--salary-min` | `None` | Minimum salary hint added to the query |
| `--experience-level` | `None` | `entry`, `mid`, `senior`, or `lead` |
| `--exclude-keywords` | `""` | Comma-separated terms to exclude, e.g. `intern,contract` |
| `--max-results` | `100` | Cap on total results across all platforms |
| `--platforms` | all | Comma-separated platform names to restrict the search to |
| `--output-dir` | `outputs` | Base directory for JSON/CSV output |
| `--output-prefix` | `results` | Filename prefix for output files |
| `--verbose` | off | DEBUG-level logging |

## Output format

Each result is a `RawSearchResults` record:

```json
{
  "url": "https://job-boards.greenhouse.io/postscript/jobs/8488222002",
  "title": "Job Application for Senior Frontend Engineer at Postscript",
  "snippet": "Senior Frontend Engineer · Primary duties. Build and maintain frontend experiences...",
  "ats_source": "greenhouse",
  "query_used": "site:greenhouse.io \"frontend Engineer\" after:2026-04-03",
  "scraped_at": "2026-04-10T12:01:09.327202Z"
}
```

Written to `outputs/json/<prefix>_results.json` (pretty-printed) and `outputs/csv/<prefix>_results.csv`.

## Design notes

- **Google dorking over per-platform scraping or official APIs.** Rather than writing a separate scraper (or integrating a separate API) for each ATS, every platform is queried the same way through one Google-search interface via Serper — one `QueryBuilder`/`SerperSearcher` pair handles all 20 platforms.
- **Async HTTP client (`httpx.AsyncClient`).** Requests across platforms and pages are I/O-bound, so `asyncio` keeps the run fast without threading.
- **Pydantic models throughout.** `SearchParams`, `ATSConfig`, and `RawSearchResults` validate input and output shape rather than passing raw dicts around.
- **Page budget capped at 3 per platform (`SERPER_MAX_PAGES`).** Each page costs 1 Serper credit; this bounds cost predictably regardless of how many platforms or how broad the search is.
- **`--platforms` and mutually-exclusive `--remote`/`--no-remote` flags.** Kept the CLI usable for narrow, cheap test runs instead of always hitting every platform.

## Known limitations

- **No deduplication yet.** The same posting sometimes appears via more than one query (e.g. a company cross-posted on Greenhouse and their own careers page). Results are currently written as-is; deduplication (e.g. by URL) isn't implemented yet.
- **Single search strategy.** `--strategy` currently only supports `serper`; the flag exists for a planned alternative backend that isn't built.
- **Recency is bounded by Google's index**, not the ATS platform directly, so very fresh postings may lag by however long Google takes to crawl them.

## Requirements

- Python 3.10+
- A [Serper.dev](https://serper.dev) API key
