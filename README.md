# Bottom Pot — ATS Job Search

Bottom Pot searches applicant-tracking-system (ATS) sites directly — Greenhouse, Lever, Ashby, Workable, and 16 others — instead of relying on aggregators like LinkedIn or Indeed. It builds a targeted Google search ("dork") per platform, runs it through the [Serper.dev](https://serper.dev) API, then enriches each result by fetching structured data from the provider's public API or page metadata. Results appear in a browser UI (with live streaming) or save to JSON and CSV.

## Why search ATS platforms directly?

Aggregators re-index listings on their own schedule and often surface stale or duplicate postings. Most companies' actual job pages live on one of a small number of ATS platforms (`boards.greenhouse.io`, `jobs.lever.co`, `jobs.ashby.com`, etc.). By restricting a Google search to `site:<ats-domain>`, Bottom Pot finds postings closer to the source and closer to when they were published, using Google's own freshness/date filtering rather than an aggregator's.

## How it works

```
CLI args (main.py) or browser UI (frontend/)
      │
      ▼
SearchParams (pydantic model, src/project_files/models.py)
      │
      ├─── CLI path ───────────────────────────────────────────────┐
      │    QueryBuilder → SerperSearcher → JSON/CSV               │
      │                                                            │
      └─── Browser path (FastAPI) ─────────────────────────────────┤
           SearchOrchestrator                                      │
           QueryBuilder — one Google dork per ATS platform        │
           Serper.dev (paginated, 3 pages/platform)               │
                │                                                 │
                ▼                                                 │
           ATS URL Parser (ats_url_parser.py)                     │
                │                                                 │
                ├─ Known API provider → ats_api_client.py         │
           │       Greenhouse, Lever, Ashby, SmartRecruiters,    │
           │       Workable, BambooHR, Recruitee                 │
           │                                                     │
           ├─ Generic enrichment → ats_page_enricher.py          │
           │       SAP SuccessFactors, Taleo, Personio,         │
           │       JazzHR, Workday, TeamTailor, iCIMS, etc.      │
           │                                                     │
           └─ Field normalization → field_normalizer.py           │
                   work_model, employment_type, location          │
                                                                 │
           Deduplicate → Cache → SSE stream → browser JSON ──────┘
```

The CLI path uses `SerperSearcher` directly and writes JSON/CSV output. The browser path uses `SearchOrchestrator`, enriches each result via provider APIs or page metadata, normalizes fields, deduplicates by URL, and streams results via Server-Sent Events. Each ATS platform is queried independently up to `SERPER_MAX_PAGES` (3) pages, 10 results per page, then truncated to `--max-results`.

## Supported platforms

Greenhouse, Lever, Ashby, Workable, BambooHR, Jobvite, SmartRecruiters, iCIMS, Personio, Teamtailor, Recruitee, Breezy HR, Workday, Taleo, JobAdder, JazzHR, Avature, SAP SuccessFactors.

Full list with domains lives in `src/project_files/config.py:ATS_PLATFORMS`.

## Project structure

```
main.py                          CLI entry point — arg parsing, orchestration, output writing
frontend/
      index.html                     Search UI served by FastAPI
      app.js                         SSE client, result rendering, and CSV export
      styles.css                     Responsive browser styling
src/api/main.py                  FastAPI routes and static frontend mount
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

Get a free API key at [serper.dev](https://serper.dev) (2,500 free credits — each paginated request costs 1 credit, so a full run across all 18 platforms at 3 pages each costs up to 54 credits). Then create a `.env` file in the project root:

```
SERPER_API_KEY=your_key_here
```

## Usage

### Browser application

Start the FastAPI server from the project root:

```bash
uvicorn src.api.main:app --reload
```

Then open <http://127.0.0.1:8000/>. The UI sends the selected role, location, work model, freshness window, and Nigerian-board preference to `GET /search`. The browser pipeline now matches the CLI search budget: all 18 configured ATS domains, up to 3 Serper pages per domain, and a default cap of 100 results. Results arrive progressively over Server-Sent Events, and `Download CSV` or `Download JSON` creates a local export from the streamed records. No search data is uploaded to a third-party spreadsheet service.

The API also remains available at:

| Endpoint | Purpose |
|---|---|
| `GET /health` | Service health check |
| `GET /search` | Streaming search; required `q`, optional `location`, `remote`, `days_back`, and `include_nigerian` |
| `POST /subscribe` | Store an email subscription as configured by `SUBSCRIPTIONS_FILE` |

The frontend is mounted from `frontend/` by `src/api/main.py`, so local development only needs one process. For production, set `allow_origins` in the CORS middleware to the actual frontend origin instead of `*`.

The table displays normalized `Location`, `Job type`, `Work model`, and exact `Posted date` values when the provider exposes them. The seven ATS providers with structured API clients can supply richer metadata; the remaining configured platforms are enriched from their public `JobPosting` page metadata when available, then retained as snippet records if the page cannot be fetched. Fields unavailable in the source are shown as `Unknown` or `Date unavailable` rather than guessed. The broader search has a 90-second hard timeout because it may make up to 60 Serper requests plus page enrichment.

### Command line

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

- **Google dorking over per-platform scraping or official APIs.** Rather than writing a separate scraper (or integrating a separate API) for each ATS, every platform is queried the same way through one Google-search interface via Serper — one `QueryBuilder`/`SerperSearcher` pair handles all 18 platforms.
- **Async HTTP client (`httpx.AsyncClient`).** Requests across platforms and pages are I/O-bound, so `asyncio` keeps the run fast without threading.
- **Pydantic models throughout.** `SearchParams`, `ATSConfig`, and `RawSearchResults` validate input and output shape rather than passing raw dicts around.
- **Page budget capped at 3 per platform (`SERPER_MAX_PAGES`).** Each page costs 1 Serper credit; this bounds cost predictably regardless of how many platforms or how broad the search is.
- **Browser and CLI coverage.** The browser uses the same 18-platform registry and three-page budget as the CLI. Only seven providers currently have structured enrichment clients; the other platforms use generic page metadata before falling back to honest snippet records.
- **`--platforms` and mutually-exclusive `--remote`/`--no-remote` flags.** Kept the CLI usable for narrow, cheap test runs instead of always hitting every platform.

## Known limitations

- **Snippet-only fallback for some providers.** Platforms without a dedicated API client (iCIMS, Avature, JobAdder, and some Taleo/Workday pages) rely on generic page metadata or plain search snippets. Their results may have empty fields when the page doesn't publish structured JSON-LD.
- **Single search strategy.** `--strategy` currently only supports `serper`; the flag exists for a planned alternative backend that isn't built.
- **Recency is bounded by Google's index**, not the ATS platform directly, so very fresh postings may lag by however long Google takes to crawl them.
- **Process-local cache.** The search cache lives in process memory and is lost on restart; it is not shared between multiple server workers.

## Requirements

- Python 3.10+
- A [Serper.dev](https://serper.dev) API key
