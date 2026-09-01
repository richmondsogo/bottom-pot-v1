import asyncio
import json
import sys
import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd
from loguru import logger

from src.project_files import ATS_PLATFORMS, SearchParams

# I imported all the necessary modules. asyncio for async, json for output, argparse for CLI,
# pandas for CSV export, loguru for logging, and my own modules.

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """
    I parse the command-line arguments. I use argparse to handle all the options
    the user can pass. This makes the script flexible.
    """
    parser = argparse.ArgumentParser(
        description="Bottom Pot — scrape ATS platforms for job listings via Google Search.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # I added the search strategy argument, but currently only serper is supported.
    parser.add_argument(
        "--strategy",
        default="serper",
        choices=["serper"],
        help="Search backend to use.",
    )

    # I added all the core search params that the user can specify.
    parser.add_argument(
        "--job-title",
        required=True,
        help="Job title to search for (e.g. 'React Native Engineer').",
    )
    parser.add_argument(
        "--location",
        default=None,
        help="Location context added to the query (e.g. 'New York', 'London').",
    )
    parser.add_argument(
        "--country-code",
        default=None,
        help=(
            "Restrict results to a country's Google index "
            "(e.g. 'us' for google.com, 'gb' for google.co.uk). "
            "Omit for a global search."
        ),
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=7,
        help="Only return listings posted within the last N days.",
    )
    # I used mutually exclusive group for remote options.
    remote_group = parser.add_mutually_exclusive_group()
    remote_group.add_argument(
        "--remote",
        action="store_true",
        default=False,
        help="Only return remote roles (adds '\"remote\"' to the query).",
    )
    remote_group.add_argument(
        "--no-remote",
        action="store_true",
        default=False,
        help="Exclude remote roles (adds '-\"remote\"' to the query).",
    )

    # I added filters like salary, experience, etc.
    parser.add_argument(
        "--salary-min",
        type=int,
        default=None,
        help="Minimum salary hint included in the query (e.g. 80000).",
    )
    parser.add_argument(
        "--experience-level",
        choices=["entry", "mid", "senior", "lead"],
        default=None,
        help="Filter by experience level.",
    )
    parser.add_argument(
        "--exclude-keywords",
        default="",
        help="Comma-separated keywords to exclude (e.g. 'intern,contract,part-time').",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=100,
        help="Cap on total results returned across all platforms.",
    )

    # I allowed selecting specific platforms.
    parser.add_argument(
        "--platforms",
        default=None,
        help=(
            "Comma-separated ATS platform names to search "
            "(e.g. 'greenhouse,lever'). Omit to search all platforms. "
            f"Available: {', '.join(p.name for p in ATS_PLATFORMS)}"
        ),
    )

    # I added output options.
    parser.add_argument(
        "--output-dir",
        default="outputs",
        help="Base directory for results (json/ and csv/ sub-dirs are created automatically).",
    )
    parser.add_argument(
        "--output-prefix",
        default="results",
        help="Filename prefix for output files (e.g. 'remote_senior_results').",
    )

    # I added logging option.
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    """
    I am the main entry point. I parse args, set up logging, build params, run the search,
    print results, and save outputs. This is where everything comes together.
    """
    args = parse_args()

    # I configured the logger before anything else logs, so I can control the output level.
    logger.remove()
    logger.add(
        sys.stderr,
        level="DEBUG" if args.verbose else "INFO",
        colorize=True,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    )

    # I built SearchParams from the CLI args. I mappped the remote flags to the enum.
    params = SearchParams(
        job_title=args.job_title,
        location=args.location,
        country_code=args.country_code,
        days_back=args.days_back,
        remote=True if args.remote else (False if args.no_remote else None),
        salary_min=args.salary_min,
        experience_level=args.experience_level,
        exclude_keywords=[
            kw.strip() for kw in args.exclude_keywords.split(",") if kw.strip()
        ],
        max_results=args.max_results,
    )

    # I resolved the platforms. If user specified, I filterd to those.
    platforms = None
    if args.platforms:
        requested = {name.strip().lower() for name in args.platforms.split(",")}
        platforms = [p for p in ATS_PLATFORMS if p.name in requested]
        if not platforms:
            logger.error(
                f"No matching platforms for: {args.platforms}. "
                f"Available names: {[p.name for p in ATS_PLATFORMS]}"
            )
            return

    # I logged all the params for debugging.
    logger.info(
        f"Bottom Pot | strategy={args.strategy} | job_title={params.job_title!r} | "
        f"location={params.location!r} | country_code={params.country_code} | "
        f"days_back={params.days_back} | remote={params.remote} | "
        f"salary_min={params.salary_min} | experience_level={params.experience_level} | "
        f"exclude_keywords={params.exclude_keywords} | max_results={params.max_results} | "
        f"platforms={[p.name for p in platforms] if platforms else 'all'}"
    )

    # I ran the search based on strategy. Currently only serper.
    results = []
    if args.strategy == "serper":
        from src.project_files.serper_searcher import SerperSearcher

        results = await SerperSearcher().run(params, platforms)

    # I printed a summary to stdout with a nice border.
    print(f"\n{'─' * 60}")
    print(f"  Found {len(results)} result(s)")
    print(f"{'─' * 60}\n")
    for r in results:
        print(f"[{r.ats_source.upper()}] {r.title}")
        if r.snippet:
            print(f"  {r.snippet}")
        print(f"  {r.url}")
        print(f"  Query: {r.query_used}\n")

    # I saved the outputs to JSON and CSV.
    output_dir = Path(args.output_dir)
    json_dir = output_dir / "json"
    csv_dir = output_dir / "csv"
    json_dir.mkdir(parents=True, exist_ok=True)
    csv_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    json_path = json_dir / f"{args.output_prefix}_results.json"
    csv_path = csv_dir / f"{args.output_prefix}_results.csv"

    # I wrote the JSON file with pretty printing.
    json_path.write_text(
        json.dumps(
            [r.model_dump(mode="json") for r in results], ensure_ascii=False, indent=4
        ),
        encoding="utf-8",
    )

    # I created the CSV if there are results.
    if results:
        pd.DataFrame([r.model_dump(mode="json") for r in results]).to_csv(
            csv_path, index=False, encoding="utf-8-sig"
        )

    # I printed the final summary.
    print(f"{'─' * 60}")
    print(f"  Saved {len(results)} result(s) at {timestamp}")
    print(f"  JSON → {json_path}")
    print(f"  CSV  → {csv_path}")
    print(f"{'─' * 60}\n")


if __name__ == "__main__":
    # I ran the main function with asyncio.
    asyncio.run(main())
